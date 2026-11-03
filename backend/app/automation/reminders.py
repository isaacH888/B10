"""Calendar-day reminders with explicit DST handling and stale-job guards."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

UTC = timezone.utc


def instant(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if result.tzinfo is None:
        raise ValueError("An instant must include an offset")
    return result.astimezone(UTC)


def local_wall_time(naive, zone):
    """Choose the first fold; shift nonexistent times forward by the DST gap."""
    candidates = []
    for fold in (0, 1):
        proposed = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = proposed.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive:
            candidates.append(proposed)
    if candidates:
        return min(candidates, key=lambda value: value.astimezone(UTC))
    # ZoneInfo's round trip normalizes spring-forward gaps, including non-hour gaps.
    shifted = [
        naive.replace(tzinfo=zone, fold=fold).astimezone(UTC).astimezone(zone) for fold in (0, 1)
    ]
    forward = [value for value in shifted if value.replace(tzinfo=None) > naive]
    if not forward:
        raise ValueError("Could not resolve local reminder time")
    return min(forward, key=lambda value: value.replace(tzinfo=None))


def reminder_time(start, timezone_name, days=7):
    local = instant(start).astimezone(ZoneInfo(timezone_name))
    wall = local.replace(tzinfo=None) - timedelta(days=days)
    return local_wall_time(wall, local.tzinfo).astimezone(UTC)


def schedule_name(booking_id, revision, label):
    return "pops-" + sha256(f"{booking_id}:{revision}:{label}".encode()).hexdigest()[:48]


class MemoryScheduler:
    """Inspectable local adapter. It never claims to invoke AWS or send email."""

    def __init__(self):
        self.schedules = {}

    def put(self, name, when, payload, booking_id):
        self.schedules[name] = {"when": when, "payload": payload, "booking_id": booking_id}

    def delete(self, name):
        self.schedules.pop(name, None)


class AwsScheduler:
    def __init__(self, settings, client=None):
        self.settings, self._client = settings, client

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("scheduler")
        return self._client

    def put(self, name, when, payload, booking_id):
        import json

        target = {
            "Arn": self.settings["AUTOMATION_QUEUE_ARN"],
            "RoleArn": self.settings["AUTOMATION_SCHEDULER_ROLE_ARN"],
            "Input": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            "SqsParameters": {"MessageGroupId": booking_id},
            "RetryPolicy": {"MaximumEventAgeInSeconds": 86400, "MaximumRetryAttempts": 10},
        }
        if self.settings.get("AUTOMATION_SCHEDULER_DLQ_ARN"):
            target["DeadLetterConfig"] = {"Arn": self.settings["AUTOMATION_SCHEDULER_DLQ_ARN"]}
        options = {
            "Name": name,
            "GroupName": self.settings["AUTOMATION_SCHEDULER_GROUP"],
            "ScheduleExpression": "at(" + instant(when).strftime("%Y-%m-%dT%H:%M:%S") + ")",
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "Target": target,
        }
        try:
            self.client.create_schedule(**options, ClientToken=sha256(name.encode()).hexdigest())
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConflictException":
                raise
            # Revision-specific names make an existing schedule immutable and idempotent.

    def delete(self, name):
        try:
            self.client.delete_schedule(
                Name=name, GroupName=self.settings["AUTOMATION_SCHEDULER_GROUP"]
            )
        except Exception as error:
            if (
                getattr(error, "response", {}).get("Error", {}).get("Code")
                != "ResourceNotFoundException"
            ):
                raise


class ReminderService:
    def __init__(self, settings, store, scheduler, clock=None):
        self.settings, self.store, self.scheduler = settings, store, scheduler
        self.clock = clock or (lambda: datetime.now(UTC))

    def replace(self, booking_id):
        """Reconcile current revision; replays use the same schedules and message keys."""
        with self.store.booking_lock(booking_id):
            with self.store.transaction() as tx:
                booking = tx.get_booking(booking_id)
                if not booking:
                    return
                revision = booking["schedule_revision"]
                if booking.get("reminder_plan_revision") == revision:
                    plan = booking.get("reminder_plan", [])
                else:
                    plan, slots, immediate = [], {}, []
                    if booking["status"] == "confirmed":
                        now = instant(self.clock())
                        offsets = {
                            "payment": 7,
                            "count": self.settings.get("AUTOMATION_COUNT_REMINDER_DAYS", 7),
                        }
                        for item, days in offsets.items():
                            due = reminder_time(booking["start"], booking["timezone"], days)
                            if due <= now:
                                immediate.append(item)
                            else:
                                slots.setdefault(due, []).append(item)
                        if immediate:
                            plan.append({"items": sorted(immediate), "immediate": True})
                        for due, items in slots.items():
                            label = "+".join(sorted(items))
                            plan.append(
                                {
                                    "name": schedule_name(booking_id, revision, label),
                                    "when": due.isoformat(),
                                    "items": sorted(items),
                                }
                            )
                    booking["reminder_obsolete_names"] = list(
                        set(
                            booking.get("reminder_obsolete_names", [])
                            + booking.get("reminder_schedule_names", [])
                        )
                    )
                    booking["reminder_plan_revision"] = revision
                    booking["reminder_plan"] = plan
                    booking["reminder_schedule_names"] = [
                        slot["name"] for slot in plan if "name" in slot
                    ]
                    tx.save_booking(booking)
                obsolete = list(booking.get("reminder_obsolete_names", []))
            # The durable plan prevents a retry after the reminder date from creating
            # an additional immediate message. Every slot keeps the same delivery key.
            for name in obsolete:
                self.scheduler.delete(name)
            for slot in plan:
                if slot.get("immediate"):
                    with self.store.transaction() as tx:
                        tx.enqueue(
                            f"reminder:{booking_id}:{revision}:{'+'.join(slot['items'])}",
                            "reminder",
                            booking_id,
                            booking["revision"],
                            {
                                "schedule_revision": revision,
                                "items": slot["items"],
                                "immediate": True,
                            },
                        )
                else:
                    # Once a one-time schedule has run, replaying a schedule job should
                    # not recreate a past date; its existing durable job handles retries.
                    if instant(slot["when"]) > instant(self.clock()):
                        self.scheduler.put(
                            slot["name"],
                            instant(slot["when"]),
                            {
                                "kind": "scheduled_reminder",
                                "booking_id": booking_id,
                                "schedule_revision": revision,
                                "items": slot["items"],
                            },
                            booking_id,
                        )
                    else:
                        self.materialize(
                            {
                                "booking_id": booking_id,
                                "schedule_revision": revision,
                                "items": slot["items"],
                            }
                        )
            with self.store.transaction() as tx:
                current = tx.get_booking(booking_id)
                if current and current["schedule_revision"] == booking["schedule_revision"]:
                    current["reminder_obsolete_names"] = []
                    tx.save_booking(current)

    def materialize(self, payload):
        """Scheduler retries create one durable job; payload contains no customer data."""
        booking_id, revision = payload["booking_id"], int(payload["schedule_revision"])
        items = sorted(set(payload.get("items", [])) & {"payment", "count"})
        key = f"reminder:{booking_id}:{revision}:{'+'.join(items)}"
        with self.store.transaction() as tx:
            booking = tx.get_booking(booking_id)
            if (
                not booking
                or booking["status"] != "confirmed"
                or booking["schedule_revision"] != revision
            ):
                return None
            tx.enqueue(
                key,
                "reminder",
                booking_id,
                booking["revision"],
                {"schedule_revision": revision, "items": items},
            )
        return key

    def outstanding(self, booking, payload):
        if booking["status"] != "confirmed" or booking["schedule_revision"] != payload.get(
            "schedule_revision"
        ):
            return []
        items = payload.get("items", ["payment", "count"])
        result = []
        if "payment" in items and booking["remaining_minor"] > 0:
            result.append("payment")
        if "count" in items and not booking.get("count_finalized", False):
            result.append("count")
        return result
