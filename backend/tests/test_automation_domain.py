"""Offline business invariants; no AWS or Google credentials are used."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading

import pytest

from app.automation.domain import BookingService, DomainError, MAX_MONEY
from app.automation.store import MemoryStore


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def setup():
    store, clock = MemoryStore(), [NOW]
    return store, BookingService(store, clock=lambda: clock[0], capacity=100), clock


def payload(**overrides):
    return {"start": "2030-02-20T14:00:00-06:00", "end": "2030-02-20T16:00:00-06:00",
            "timezone": "America/Chicago", "venue": "Houston venue", "quantity": 50,
            "service_type": "delivery", "customer_email": "customer@example.invalid",
            "total_minor": 10001, "currency": "USD", "contract_url": "https://example.invalid/contract", **overrides}


def payment(reference="provider-123", amount=5001, **overrides):
    return {"reference": reference, "amount_minor": amount, "currency": "USD",
            "verification_details": "Owner checked settled Venmo account transaction", "provider": "venmo", **overrides}


def approved(service, **overrides):
    booking = service.create(payload(**overrides), "owner")
    return service.approve(booking["id"], {}, "owner")


def test_deposit_rounded_up_confirms_with_balance_and_atomic_outbox(setup):
    store, service, _ = setup
    booking = approved(service)
    assert booking["deposit_minor"] == 5001
    booking = service.verify_payment(booking["id"], payment(), "owner")
    assert (booking["status"], booking["payment_status"], booking["remaining_minor"]) == ("confirmed", "deposit_paid", 5000)
    with store.transaction() as tx:
        kinds = {j["kind"] for j in tx.list_outbox()}
        assert kinds == {"deposit_request", "calendar", "confirmation_customer", "confirmation_owner", "reminder_schedule"}
        assert len(tx.payments(booking["id"])) == 1


def test_payment_after_cancellation_is_retained_and_flags_review(setup):
    store, service, _ = setup
    booking = approved(service)
    service.cancel(booking["id"], "owner")
    result = service.verify_payment(booking["id"], payment(), "owner")
    assert result["status"] == "cancelled"
    assert result["paid_minor"] == 5001
    assert "owner review" in result["owner_review_reason"]
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1


def test_confirmation_generation_survives_reschedule_and_changes_on_reopen(setup):
    store, service, _ = setup
    booking = approved(service)
    confirmed = service.verify_payment(booking["id"], payment(), "owner")
    rescheduled = service.reschedule(booking["id"], payload(start="2030-02-21T14:00:00-06:00", end="2030-02-21T16:00:00-06:00"), "owner")
    assert rescheduled["confirmation_generation"] == confirmed["confirmation_generation"]
    service.cancel(booking["id"], "owner")
    reopened = service.reopen(booking["id"], {"reason": "Customer requested another reservation"}, "owner")
    assert reopened["confirmation_generation"] == confirmed["confirmation_generation"] + 1
    with store.transaction() as tx:
        generations = [job["payload"]["confirmation_generation"] for job in tx.list_outbox() if job["kind"] == "confirmation_customer"]
        assert generations == [1, 2]


def test_duplicate_reference_is_global_and_identical_payment_noop(setup):
    store, service, _ = setup
    booking = approved(service)
    first = service.verify_payment(booking["id"], payment(), "owner")
    assert service.verify_payment(booking["id"], payment(), "owner") == first
    second = approved(service)
    with pytest.raises(DomainError, match="different payment"):
        service.verify_payment(second["id"], payment(), "owner")
    with pytest.raises(DomainError):
        service.verify_payment(booking["id"], payment(amount=5002), "owner")
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1
        assert not tx.payments(second["id"])


def test_late_deposit_preserved_without_overbooking_and_explicit_reapproval(setup):
    store, service, clock = setup
    first = approved(service, quantity=100)
    clock[0] += 172801
    second = approved(service, quantity=100)
    late = service.verify_payment(first["id"], payment(), "owner")
    assert late["status"] == "owner_review" and late["paid_minor"] == 5001
    with pytest.raises(DomainError, match="Capacity"):
        service.approve(first["id"], {}, "owner")
    service.cancel(second["id"], "owner")
    assert service.approve(first["id"], {}, "owner")["status"] == "confirmed"
    with store.transaction() as tx:
        assert tx.payments(first["id"])[0]["reference"] == "provider-123"


def test_simultaneous_approvals_cannot_overbook(setup):
    _, service, _ = setup
    bookings = [service.create(payload(quantity=100), "owner") for _ in range(2)]
    barrier = threading.Barrier(2)

    def approve(booking):
        barrier.wait()
        try:
            service.approve(booking["id"], {}, "owner")
            return True
        except DomainError as error:
            assert error.code == "capacity_unavailable"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(approve, bookings)) == 1


def test_capacity_uses_peak_overlap_and_back_to_back_events(setup):
    _, service, _ = setup
    approved(service, quantity=50, start="2030-02-20T10:00:00-06:00", end="2030-02-20T11:00:00-06:00")
    approved(service, quantity=50, start="2030-02-20T11:00:00-06:00", end="2030-02-20T12:00:00-06:00")
    long = approved(service, quantity=50, start="2030-02-20T10:00:00-06:00", end="2030-02-20T12:00:00-06:00")
    assert long["status"] == "awaiting_deposit"


def test_cancellation_preserves_payment_and_reopen_rechecks_capacity(setup):
    store, service, _ = setup
    booking = approved(service, quantity=100)
    booking = service.verify_payment(booking["id"], payment(), "owner")
    cancelled = service.cancel(booking["id"], "owner", expected_revision=booking["revision"])
    assert cancelled["status"] == "cancelled" and cancelled["paid_minor"] == 5001
    another = approved(service, quantity=100)
    with pytest.raises(DomainError, match="Capacity"):
        service.reopen(booking["id"], {"reason": "Owner approved reopening"}, "owner")
    service.cancel(another["id"], "owner")
    reopened = service.reopen(booking["id"], {"reason": "Owner approved reopening"}, "owner")
    assert reopened["status"] == "confirmed" and reopened["paid_minor"] == 5001
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1


def test_recording_payment_after_cancel_does_not_reopen(setup):
    _, service, _ = setup
    booking = approved(service)
    service.cancel(booking["id"], "owner")
    result = service.verify_payment(booking["id"], payment(amount=10001), "owner")
    assert (result["status"], result["payment_status"]) == ("cancelled", "paid")


def test_financial_and_count_changes_preserve_schedule_revision(setup):
    _, service, _ = setup
    booking = approved(service)
    booking = service.verify_payment(booking["id"], payment(), "owner")
    schedule_revision = booking["schedule_revision"]
    booking = service.verify_payment(booking["id"], payment("balance", 5000), "owner")
    booking = service.finalize_count(booking["id"], {}, "owner")
    assert booking["schedule_revision"] == schedule_revision
    assert booking["payment_status"] == "paid" and booking["count_finalized"]
    moved = service.reschedule(booking["id"], payload(start="2030-02-21T14:00:00-06:00", end="2030-02-21T16:00:00-06:00"), "owner")
    assert moved["schedule_revision"] == schedule_revision + 1


def test_repair_job_is_explicit_and_reopen_keeps_event_owner(setup):
    store, service, _ = setup
    booking = approved(service)
    booking = service.verify_payment(booking["id"], payment(), "owner")
    repaired = service.retry(booking["id"], "second-owner", repair=True)
    with store.transaction() as tx:
        job = tx.get_outbox(f"calendar:{booking['id']}:{repaired['revision']}")
        assert job["payload"]["repair"] is True
    service.cancel(booking["id"], "second-owner")
    reopened = service.reopen(booking["id"], {"reason": "Authorized reopening"}, "second-owner")
    assert reopened["owner_id"] == "owner"


def test_stale_owner_edit_rejected_without_side_effects(setup):
    store, service, _ = setup
    booking = approved(service)
    before = booking.copy()
    with pytest.raises(DomainError, match="Booking changed"):
        service.verify_payment(booking["id"], payment(expected_revision=booking["revision"] - 1), "owner")
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"]) == before
        assert tx.payments(booking["id"]) == []


@pytest.mark.parametrize("action", ["cancel", "reschedule", "payment", "count"])
def test_owner_changes_wait_for_reminder_booking_lock(setup, action):
    store, service, _ = setup
    booking = approved(service)
    booking = service.verify_payment(booking["id"], payment(), "owner")
    sending, release, attempted, completed = (threading.Event() for _ in range(4))

    def send():
        with store.booking_lock(booking["id"]):
            sending.set()
            assert release.wait(5)

    def mutate():
        attempted.set()
        if action == "cancel":
            service.cancel(booking["id"], "owner")
        elif action == "reschedule":
            service.reschedule(booking["id"], payload(start="2030-02-21T14:00:00-06:00", end="2030-02-21T16:00:00-06:00"), "owner")
        elif action == "payment":
            service.verify_payment(booking["id"], payment("balance", 5000), "owner")
        else:
            service.finalize_count(booking["id"], {}, "owner")
        completed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        sent = pool.submit(send)
        assert sending.wait(5)
        mutation = pool.submit(mutate)
        assert attempted.wait(5)
        try:
            assert not completed.wait(0.05)
        finally:
            release.set()
        sent.result(timeout=5)
        mutation.result(timeout=5)
    assert completed.is_set()


def test_outbox_failure_rolls_back_booking_payment_and_audit(setup, monkeypatch):
    store, service, _ = setup
    booking = approved(service)
    from app.automation.store import MemoryTransaction

    def fail(*args, **kwargs):
        raise RuntimeError("outbox storage failed")

    monkeypatch.setattr(MemoryTransaction, "enqueue", fail)
    with pytest.raises(RuntimeError):
        service.verify_payment(booking["id"], payment(), "owner")
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"]) == booking
        assert tx.payments(booking["id"]) == []


@pytest.mark.parametrize("overrides", [
    {"quantity": 49}, {"quantity": True}, {"start": "2030-02-20T14:00:00"},
    {"timezone": "Not/AZone"}, {"end": "2030-02-20T13:00:00-06:00"},
    {"total_minor": 3.14}, {"total_minor": MAX_MONEY + 1}, {"currency": "usd"},
    {"contract_url": "http://example.invalid/contract"}, {"customer_email": "invalid"},
    {"service_type": "unknown"},
])
def test_required_booking_validation(setup, overrides):
    _, service, _ = setup
    with pytest.raises(DomainError):
        service.create(payload(**overrides), "owner")


@pytest.mark.parametrize("overrides", [{"verification_details": ""}, {"verified": True}, {"currency": "EUR"}, {"amount_minor": 0}])
def test_manual_adapter_requires_independent_verification(setup, overrides):
    _, service, _ = setup
    booking = approved(service)
    with pytest.raises(DomainError):
        service.verify_payment(booking["id"], payment(**overrides), "owner")
