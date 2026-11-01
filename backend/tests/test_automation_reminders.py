from datetime import datetime, timezone

import pytest

from app.automation.reminders import (AwsScheduler, MemoryScheduler, ReminderService,
                                      reminder_time)
from app.automation.store import MemoryStore


UTC = timezone.utc


def booking(**changes):
    value = {"id": "booking1", "status": "confirmed", "revision": 3, "schedule_revision": 1,
             "start": "2026-11-20T18:00:00+00:00", "end": "2026-11-20T19:00:00+00:00",
             "timezone": "America/Chicago", "remaining_minor": 5001, "count_finalized": False}
    return value | changes


def seed(store, value):
    with store.transaction() as tx:
        tx.save_booking(value)


def test_calendar_days_preserve_local_time_across_dst():
    # November 1 contains the clock change; October 29 is still CDT.
    assert reminder_time("2026-11-05T18:00:00+00:00", "America/Chicago") == datetime(2026, 10, 29, 17, tzinfo=UTC)


def test_spring_gap_shifts_forward_by_gap():
    assert reminder_time("2026-03-15T07:30:00Z", "America/Chicago") == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)


def test_autumn_fold_chooses_first_occurrence():
    assert reminder_time("2026-11-08T07:30:00Z", "America/Chicago") == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_non_hour_dst_gap_is_explicitly_normalized():
    assert reminder_time("2026-10-10T15:15:00Z", "Australia/Lord_Howe") == datetime(2026, 10, 3, 15, 45, tzinfo=UTC)


@pytest.mark.parametrize("paid,count_finalized,expected", [(True, False, ["count"]),
                                                          (True, True, []),
                                                          (False, True, ["payment"]),
                                                          (False, False, ["payment", "count"])])
def test_execution_rechecks_balance_and_final_count(paid, count_finalized, expected):
    store = MemoryStore()
    service = ReminderService({}, store, MemoryScheduler())
    current = booking(remaining_minor=0 if paid else 5001, count_finalized=count_finalized)
    assert service.outstanding(current, {"schedule_revision": 1, "items": ["payment", "count"]}) == expected


def test_cancelled_and_obsolete_jobs_are_harmless():
    service = ReminderService({}, MemoryStore(), MemoryScheduler())
    assert service.outstanding(booking(status="cancelled"), {"schedule_revision": 1}) == []
    assert service.outstanding(booking(schedule_revision=2), {"schedule_revision": 1}) == []


def test_inside_seven_days_queues_one_immediate_combined_message():
    store, scheduler = MemoryStore(), MemoryScheduler()
    seed(store, booking())
    service = ReminderService({}, store, scheduler, clock=lambda: datetime(2026, 11, 18, tzinfo=UTC))
    service.replace("booking1")
    service.replace("booking1")
    assert scheduler.schedules == {}
    with store.transaction() as tx:
        jobs = tx.list_outbox()
    assert len(jobs) == 1
    assert jobs[0]["payload"] == {"schedule_revision": 1, "items": ["count", "payment"], "immediate": True}


def test_count_timing_independent_and_reschedule_deletes_old_schedules():
    store, scheduler = MemoryStore(), MemoryScheduler()
    seed(store, booking())
    service = ReminderService({"AUTOMATION_COUNT_REMINDER_DAYS": 3}, store, scheduler,
                              clock=lambda: datetime(2026, 11, 1, tzinfo=UTC))
    service.replace("booking1")
    assert len(scheduler.schedules) == 2
    old_names = set(scheduler.schedules)
    old_payload = next(iter(scheduler.schedules.values()))["payload"]
    seed(store, booking(schedule_revision=2, reminder_schedule_names=list(old_names)))
    service.replace("booking1")
    assert len(scheduler.schedules) == 2
    assert old_names.isdisjoint(scheduler.schedules)
    assert service.materialize(old_payload) is None
    seed(store, booking(status="cancelled", schedule_revision=3,
                        reminder_schedule_names=list(scheduler.schedules)))
    service.replace("booking1")
    assert scheduler.schedules == {}


def test_scheduler_retries_materialize_one_job():
    store = MemoryStore()
    seed(store, booking())
    service = ReminderService({}, store, MemoryScheduler())
    payload = {"booking_id": "booking1", "schedule_revision": 1, "items": ["payment", "count"]}
    assert service.materialize(payload) == service.materialize(payload)
    with store.transaction() as tx:
        assert len(tx.list_outbox()) == 1


def test_reconciling_after_scheduled_date_reuses_delivery_key():
    store, scheduler = MemoryStore(), MemoryScheduler()
    seed(store, booking())
    now = [datetime(2026, 11, 1, tzinfo=UTC)]
    service = ReminderService({}, store, scheduler, clock=lambda: now[0])
    service.replace("booking1")
    payload = next(iter(scheduler.schedules.values()))["payload"]
    key = service.materialize(payload)
    now[0] = datetime(2026, 11, 18, tzinfo=UTC)
    service.replace("booking1")
    with store.transaction() as tx:
        assert [job["key"] for job in tx.list_outbox()] == [key]


def test_boto_scheduler_uses_utc_one_time_and_fifo_booking_group():
    class Client:
        def create_schedule(self, **kwargs):
            self.options = kwargs
    client = Client()
    adapter = AwsScheduler({"AUTOMATION_QUEUE_ARN": "arn:queue", "AUTOMATION_SCHEDULER_ROLE_ARN": "arn:role",
                            "AUTOMATION_SCHEDULER_GROUP": "staging"}, client)
    adapter.put("pops-example", datetime(2026, 11, 13, 18, tzinfo=UTC), {"booking_id": "b"}, "b")
    assert client.options["ScheduleExpression"] == "at(2026-11-13T18:00:00)"
    assert client.options["ScheduleExpressionTimezone"] == "UTC"
    assert client.options["ActionAfterCompletion"] == "DELETE"
    assert client.options["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert client.options["Target"]["SqsParameters"] == {"MessageGroupId": "b"}
