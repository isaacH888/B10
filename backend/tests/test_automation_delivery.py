import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from app.automation.delivery import (
    JobProcessor,
    MemoryMail,
    MemoryQueue,
    OutboxDispatcher,
    RetryLater,
    SesMail,
)
from app.automation.google import GoogleFailure
from app.automation.reminders import MemoryScheduler, ReminderService
from app.automation.store import MemoryStore

UTC = timezone.utc


class Calendar:
    def __init__(self):
        self.calls = []
        self.failure = None

    def run(self, booking_id, revision, repair=False):
        self.calls.append((booking_id, revision, repair))
        if self.failure:
            raise self.failure


def setup(kind="confirmation_customer", **changes):
    store, queue, mail, calendar = MemoryStore(), MemoryQueue(), MemoryMail(), Calendar()
    now = [datetime(2026, 11, 18, tzinfo=UTC)]
    settings = {
        "AUTOMATION_OWNER_EMAIL": "owner@example.test",
        "AUTOMATION_DASHBOARD_URL": "https://example.test/admin/bookings",
        "AUTOMATION_MAX_ATTEMPTS": 3,
        "AUTOMATION_RETRY_BASE_SECONDS": 2,
        "AUTOMATION_RETRY_MAX_SECONDS": 10,
        "AUTOMATION_LEASE_SECONDS": 120,
    }
    booking = {
        "id": "b1",
        "reference": "P-1",
        "status": "confirmed",
        "revision": 3,
        "schedule_revision": 1,
        "start": "2026-11-20T18:00:00Z",
        "end": "2026-11-20T19:00:00Z",
        "timezone": "America/Chicago",
        "customer_email": "customer@example.test",
        "service_type": "delivery",
        "venue": "Event Hall",
        "quantity": 100,
        "currency": "USD",
        "total_minor": 10001,
        "deposit_minor": 5001,
        "remaining_minor": 5000,
        "count_finalized": False,
        "contract_url": "https://example.test/contract",
        "calendar_status": "pending",
    } | changes
    with store.transaction() as tx:
        tx.save_booking(booking)
        tx.enqueue("job1", kind, "b1", 3, {"schedule_revision": 1, "items": ["payment", "count"]})
    reminder = ReminderService(settings, store, MemoryScheduler(), clock=lambda: now[0])
    worker = JobProcessor(settings, store, queue, mail, reminder, calendar, clock=lambda: now[0])
    dispatcher = OutboxDispatcher(settings, store, queue, clock=lambda: now[0])
    return store, queue, mail, calendar, now, worker, dispatcher


def test_duplicate_delivery_sends_one_customer_summary_and_contract():
    store, queue, mail, _, _, worker, dispatcher = setup()
    assert dispatcher.dispatch() == 1
    assert dispatcher.dispatch() == 0
    message = queue.messages[0]["body"]
    worker.process(message)
    worker.process(message)
    assert len(mail.messages) == 1
    assert "USD 50.00" in mail.messages[0]["body"]
    assert "https://example.test/contract" in mail.messages[0]["body"]
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "sent"


def test_fully_paid_booking_still_gets_count_only_email():
    _, _, mail, _, _, worker, _ = setup("reminder", remaining_minor=0)
    worker.process({"job_key": "job1"})
    assert len(mail.messages) == 1
    assert "final popsicle count" in mail.messages[0]["body"]
    assert "remaining payment" not in mail.messages[0]["body"]


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "cancelled"},
        {"schedule_revision": 2},
        {"remaining_minor": 0, "count_finalized": True},
    ],
)
def test_obsolete_cancelled_or_completed_reminder_does_not_send(changes):
    store, _, mail, _, _, worker, _ = setup("reminder", **changes)
    worker.process({"job_key": "job1"})
    assert mail.messages == []
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "skipped"


def test_expired_reservation_suppresses_deposit_request():
    _, _, mail, _, now, worker, _ = setup(
        "deposit_request", status="awaiting_deposit", reservation_expires_at=1
    )
    worker.process({"job_key": "job1"})
    assert mail.messages == []


def test_obsolete_confirmation_after_reopen_is_suppressed():
    _, _, mail, _, _, worker, _ = setup(schedule_revision=4, confirmation_generation=2)
    worker.process({"job_key": "job1"})
    assert mail.messages == []


def test_confirmation_after_reschedule_sends_current_summary_and_contract():
    _, _, mail, _, _, worker, _ = setup(schedule_revision=2, venue="Rescheduled Hall")
    worker.process({"job_key": "job1"})
    assert len(mail.messages) == 1
    assert "Rescheduled Hall" in mail.messages[0]["body"]
    assert "https://example.test/contract" in mail.messages[0]["body"]


def test_queue_send_then_db_crash_republishes_with_stable_id():
    store, queue, mail, _, now, worker, dispatcher = setup()
    original_transaction, original_send = store.transaction, queue.send
    crash = [False]

    @contextmanager
    def transaction(*args, **kwargs):
        if crash[0]:
            crash[0] = False
            raise RuntimeError("simulated process crash")
        with original_transaction(*args, **kwargs) as tx:
            yield tx

    def send(*args):
        result = original_send(*args)
        crash[0] = True
        return result

    store.transaction = transaction
    queue.send = send
    with pytest.raises(RuntimeError):
        dispatcher.dispatch()
    queue.send = original_send
    now[0] += timedelta(seconds=121)
    assert dispatcher.dispatch() == 1
    assert len(queue.messages) == 2
    assert queue.messages[0]["dedup_id"] == queue.messages[1]["dedup_id"]
    for message in queue.messages:
        worker.process(message["body"])
    assert len(mail.messages) == 1


def test_ready_job_not_starved_by_older_delayed_jobs():
    store, queue, _, _, now, _, dispatcher = setup()
    with store.transaction() as tx:
        job = tx.get_outbox("job1")
        job["next_attempt_at"] = (now[0] + timedelta(hours=1)).isoformat()
        tx.save_outbox(job)
        tx.enqueue("ready", "calendar", "b1", 3)
    assert dispatcher.dispatch(limit=1) == 1
    assert queue.messages[0]["body"]["job_key"] == "ready"


def test_transient_failures_backoff_then_dead_letter_and_authorized_replay():
    store, queue, _, calendar, now, worker, dispatcher = setup("calendar")
    calendar.failure = GoogleFailure(
        "transient", "secret provider message should never be persisted"
    )
    for delay in (2, 4):
        with pytest.raises(RetryLater) as failure:
            worker.process({"job_key": "job1"})
        assert failure.value.seconds == delay
        now[0] += timedelta(seconds=delay)
    worker.process({"job_key": "job1"})
    assert len(queue.dead_letters) == 1
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "dead_letter"
        assert "secret provider" not in tx.get_delivery("job1")["last_error"]
    worker.replay("job1", "owner-id")
    calendar.failure = None
    assert dispatcher.dispatch() == 1
    assert queue.messages[0]["body"]["delivery_generation"] == 1
    # Delayed original-generation messages cannot execute the replay prematurely.
    worker.process({"job_key": "job1", "delivery_generation": 0})
    worker.process(queue.messages[0]["body"])
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "sent"
    assert len(calendar.calls) == 4


def test_revoked_consent_terminal_failure_awaits_explicit_retry():
    store, queue, _, calendar, _, worker, _ = setup("calendar")
    calendar.failure = GoogleFailure("reconnect_required", "Reconnect Google")
    worker.process({"job_key": "job1"})
    worker.process({"job_key": "job1"})
    assert len(calendar.calls) == 1
    assert queue.dead_letters == []
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "failed"


def test_exhausted_old_calendar_job_does_not_mark_newer_revision_failed():
    store, queue, _, calendar, now, worker, _ = setup("calendar", revision=4)
    calendar.failure = GoogleFailure("transient", "Temporary service failure")
    for delay in (2, 4):
        with pytest.raises(RetryLater):
            worker.process({"job_key": "job1"})
        now[0] += timedelta(seconds=delay)
    worker.process({"job_key": "job1"})
    assert len(queue.dead_letters) == 1
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "dead_letter"
        current = tx.get_booking("b1")
        assert current["revision"] == 4
        assert current["calendar_status"] == "pending"


def test_fifo_batch_blocks_later_records_in_failed_group_only():
    _, _, _, _, _, worker, _ = setup()
    calls = []

    def process(payload):
        calls.append(payload["job_key"])
        if payload["job_key"] == "first":
            raise RetryLater(30)

    worker.process = process
    records = [
        {
            "messageId": key,
            "body": json.dumps({"job_key": key}),
            "attributes": {"MessageGroupId": group},
        }
        for key, group in (("first", "a"), ("blocked", "a"), ("other", "b"))
    ]
    assert worker.handle_batch({"Records": records}) == {
        "batchItemFailures": [{"itemIdentifier": "first"}, {"itemIdentifier": "blocked"}]
    }
    assert calls == ["first", "other"]


def test_ses_adapter_uses_configured_sender_text_and_safe_correlation_tag():
    class Client:
        def send_email(self, **kwargs):
            self.options = kwargs
            return {"MessageId": "ses-id"}

    client = Client()
    mail = SesMail({"AUTOMATION_FROM_EMAIL": "orders@example.test"}, client)
    assert mail.send("customer@example.test", "Confirmed", "Contract link", "job-key") == "ses-id"
    assert client.options["Destination"] == {"ToAddresses": ["customer@example.test"]}
    assert client.options["Source"] == "orders@example.test"
    assert client.options["Message"]["Body"]["Text"]["Charset"] == "UTF-8"
