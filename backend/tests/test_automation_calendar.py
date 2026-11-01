"""Calendar convergence tests with a stateful fake Google server."""

import copy
from contextlib import contextmanager
import re

import pytest

from app.automation.calendar import CalendarWorker, event_id
from app.automation.google import GoogleFailure, MemoryGoogle
from app.automation.store import MemoryStore


class Tokens:
    def __init__(self, google):
        self.google = google
    def access_token(self, owner_id):
        return "mock-access"


@pytest.fixture
def projection():
    store, google = MemoryStore(), MemoryGoogle()
    google.calendars["calendar"] = {"id": "calendar"}
    booking = {"id": "booking-123", "owner_id": "owner", "reference": "POP-123", "status": "confirmed",
               "revision": 1, "schedule_revision": 1, "timezone": "America/Chicago", "venue": "Houston venue",
               "service_type": "full_service", "start": "2027-03-14T18:00:00+00:00", "end": "2027-03-14T20:00:00+00:00",
               "calendar_status": "pending", "synced_revision": None}
    with store.transaction() as tx:
        tx.save_booking(booking)
        tx.save_connection({"owner_id": "owner", "status": "connected", "calendar_id": "calendar"})
    worker = CalendarWorker({"AUTOMATION_DASHBOARD_URL": "https://example.test/admin/automation"}, store, Tokens(google), clock=lambda: 1900000000)
    return worker, store, google, booking


def current(store, booking_id="booking-123"):
    with store.transaction() as tx:
        return tx.get_booking(booking_id)


def mutate(store, **values):
    with store.transaction() as tx:
        booking = tx.get_booking("booking-123")
        booking.update(values)
        tx.save_booking(booking)


def active(google):
    return [event for event in google.events.values() if event.get("status") != "cancelled"]


def test_duplicate_jobs_create_one_minimal_private_event(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"], revision=1)
    worker.run(booking["id"], revision=0)
    assert len(active(google)) == 1
    event = active(google)[0]
    assert re.fullmatch("[0-9a-v]{64}", event["id"])
    assert event["id"] == event_id(booking)
    assert event["start"]["dateTime"] == "2027-03-14T13:00:00-05:00"
    assert event["start"]["timeZone"] == "America/Chicago"
    assert "attendees" not in event
    assert event["visibility"] == "private"
    assert "https://example.test/admin/automation/booking-123" in event["description"]
    assert current(store)["synced_revision"] == 1


def test_reschedule_updates_existing_event_using_latest_revision(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    original_id = active(google)[0]["id"]
    mutate(store, revision=2, schedule_revision=2, start="2027-03-15T18:00:00+00:00", end="2027-03-15T20:00:00+00:00")
    worker.run(booking["id"], revision=1)
    assert len(active(google)) == 1
    assert active(google)[0]["id"] == original_id
    assert active(google)[0]["start"]["dateTime"].startswith("2027-03-15")
    assert current(store)["synced_revision"] == 2


def test_cancellation_during_google_insert_converges_and_never_syncs_stale_revision(projection):
    worker, store, google, booking = projection
    original = google.insert_event
    def racing_insert(*args):
        result = original(*args)
        mutate(store, status="cancelled", revision=2, schedule_revision=2)
        assert current(store)["synced_revision"] is None
        return result
    google.insert_event = racing_insert
    worker.run(booking["id"], revision=1)
    assert active(google) == []
    assert current(store)["synced_revision"] == 2
    assert current(store)["calendar_status"] == "synced"


def test_reschedule_during_google_update_converges(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    mutate(store, revision=2, venue="intermediate venue")
    original = google.update_event
    def racing_update(*args):
        result = original(*args)
        if current(store)["revision"] == 2:
            mutate(store, revision=3, venue="latest venue")
            assert current(store)["synced_revision"] == 1
        return result
    google.update_event = racing_update
    worker.run(booking["id"], revision=1)
    assert active(google)[0]["location"] == "latest venue"
    assert current(store)["synced_revision"] == 3


def test_crash_after_insert_retries_same_id(projection):
    worker, store, google, booking = projection
    transaction = store.transaction
    crash = [True]
    @contextmanager
    def failing_transaction(*args, **kwargs):
        with transaction(*args, **kwargs) as tx:
            save = tx.save_booking
            def crash_on_synced(value):
                if value.get("calendar_status") == "synced" and crash[0]:
                    crash[0] = False
                    raise RuntimeError("simulated persistence failure after Google success")
                save(value)
            tx.save_booking = crash_on_synced
            yield tx
    store.transaction = failing_transaction
    with pytest.raises(RuntimeError):
        worker.run(booking["id"])
    assert len(active(google)) == 1
    worker.run(booking["id"])
    assert len(active(google)) == 1
    assert current(store)["synced_revision"] == 1


def test_conflicting_id_never_overwrites_an_unowned_event(projection):
    worker, store, google, booking = projection
    identifier = event_id(booking)
    google.events["calendar", identifier] = {"id": identifier, "summary": "unrelated event"}
    before = copy.deepcopy(google.events)
    with pytest.raises(GoogleFailure, match="ownership"):
        worker.run(booking["id"])
    assert google.events == before
    assert current(store)["calendar_status"] == "repair_required"


def test_insert_conflict_checks_ownership_before_update(projection):
    worker, store, google, booking = projection
    original = google.insert_event
    def conflict(*args):
        event = copy.deepcopy(args[2])
        event["extendedProperties"] = {"private": {"booking_id": "somebody-else"}}
        original(args[0], args[1], event)
        raise GoogleFailure("conflict", "Already exists.", status=409)
    google.insert_event = conflict
    with pytest.raises(GoogleFailure, match="ownership"):
        worker.run(booking["id"])
    assert not any(call[0] == "update" for call in google.calls)


def test_manual_delete_requires_repair_and_persisted_generation_survives_retry(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    old_id = active(google)[0]["id"]
    google.events["calendar", old_id] = {"id": old_id, "status": "cancelled"}
    with pytest.raises(GoogleFailure, match="deleted"):
        worker.run(booking["id"])
    mutate(store, calendar_repair_requested=True)
    worker.run(booking["id"])
    assert len(active(google)) == 1
    assert active(google)[0]["id"] != old_id
    assert current(store)["event_generation"] == 1
    worker.run(booking["id"])
    assert len(active(google)) == 1
    assert current(store)["calendar_repair_requested"] is False


def test_calendar_change_requires_explicit_repair_removes_old_event(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    google.calendars["new-calendar"] = {"id": "new-calendar"}
    with store.transaction() as tx:
        tx.save_connection({"owner_id": "owner", "status": "connected", "calendar_id": "new-calendar"})
    with pytest.raises(GoogleFailure, match="calendar changed"):
        worker.run(booking["id"])
    worker.run(booking["id"], repair=True)
    assert len(active(google)) == 1
    assert current(store)["google_calendar_id"] == "new-calendar"
    assert google.events["calendar", event_id(booking)]["status"] == "cancelled"


def test_reopen_restores_same_owned_event(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    identifier = active(google)[0]["id"]
    mutate(store, status="cancelled", revision=2)
    worker.run(booking["id"])
    assert not active(google)
    mutate(store, status="confirmed", revision=3)
    worker.run(booking["id"])
    assert len(active(google)) == 1
    assert active(google)[0]["id"] == identifier


def test_underpaid_reopen_before_pending_cancellation_still_removes_old_event(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    mutate(store, status="cancelled", revision=2)
    # An owner reopens for a new deposit before the queued deletion runs.
    mutate(store, status="awaiting_deposit", revision=3)
    worker.run(booking["id"], revision=2)
    assert not active(google)
    assert current(store)["synced_revision"] == 3


def test_manual_deleted_event_with_ownership_still_requires_owner_repair(projection):
    worker, store, google, booking = projection
    worker.run(booking["id"])
    identifier = active(google)[0]["id"]
    google.delete_event("mock-access", "calendar", identifier)
    with pytest.raises(GoogleFailure, match="deleted"):
        worker.run(booking["id"])
    assert not active(google)
    worker.run(booking["id"], repair=True)
    assert len(active(google)) == 1
    assert active(google)[0]["id"] == identifier


@pytest.mark.parametrize("category,state", [("transient", "pending"), ("reconnect_required", "reconnect_required")])
def test_google_failures_mark_useful_state(projection, category, state):
    worker, store, google, booking = projection
    def failed(*args):
        raise GoogleFailure(category, "Safe useful owner message.")
    google.check_calendar = failed
    with pytest.raises(GoogleFailure):
        worker.run(booking["id"])
    assert current(store)["calendar_status"] == state
    assert current(store)["calendar_error"] == "Safe useful owner message."
    if category == "reconnect_required":
        with store.transaction() as tx:
            assert tx.get_connection("owner")["status"] == "reconnect_required"


def test_invalid_event_has_actionable_error_and_no_insert(projection):
    worker, store, google, booking = projection
    mutate(store, timezone="not/an/IANA-zone")
    with pytest.raises(GoogleFailure, match="IANA time zone"):
        worker.run(booking["id"])
    assert current(store)["calendar_status"] == "failed"
    assert not active(google)


def test_old_grant_failure_cannot_mark_same_calendar_reconnection_broken(projection):
    worker, store, google, booking = projection
    check = google.check_calendar
    first = [True]
    def reconnect_during_check(*args):
        if first[0]:
            first[0] = False
            with store.transaction() as tx:
                connection = tx.get_connection("owner")
                connection.update(connection_revision=1, status="connected", last_error=None)
                tx.save_connection(connection)
            raise GoogleFailure("reconnect_required", "The old grant was revoked.")
        return check(*args)
    google.check_calendar = reconnect_during_check
    worker.run(booking["id"])
    with store.transaction() as tx:
        connection = tx.get_connection("owner")
        assert connection["status"] == "connected"
        assert connection["last_error"] is None
    assert current(store)["calendar_status"] == "synced"
    assert len(active(google)) == 1


def test_same_calendar_reconnect_during_insert_rechecks_new_grant_before_synced(projection):
    worker, store, google, booking = projection
    insert = google.insert_event
    def reconnect_during_insert(*args):
        result = insert(*args)
        with store.transaction() as tx:
            connection = tx.get_connection("owner")
            connection.update(connection_revision=1, status="connected")
            tx.save_connection(connection)
        return result
    google.insert_event = reconnect_during_insert
    worker.run(booking["id"])
    assert len(active(google)) == 1
    # Success from the previous grant was not enough to mark the projection
    # synced: the worker reloaded the new connection and reconciled once more.
    assert any(call[0] == "update" for call in google.calls)
    assert current(store)["synced_revision"] == booking["revision"]


def test_old_grant_error_cannot_overwrite_explicit_disconnect(projection):
    worker, store, google, booking = projection
    def disconnect_during_check(*args):
        with store.transaction() as tx:
            connection = tx.get_connection("owner")
            connection.update(connection_revision=1, status="disconnected", last_error=None)
            tx.save_connection(connection)
        raise GoogleFailure("reconnect_required", "The old grant was revoked.")
    google.check_calendar = disconnect_during_check
    with pytest.raises(GoogleFailure, match="Connect Google"):
        worker.run(booking["id"])
    with store.transaction() as tx:
        assert tx.get_connection("owner")["status"] == "disconnected"
    assert current(store)["calendar_status"] == "reconnect_required"
