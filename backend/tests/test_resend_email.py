"""Resend payloads, private error boundaries and durable booking email retries."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
import requests
from app.email.provider import MailFailure, create_mailer
from app.email.resend import ResendClient, ResendMail, ResendMailer
from app.email.settings import validate_settings
from test_automation_delivery import setup as delivery_setup


@pytest.fixture
def settings():
    return {
        "AUTH_ENABLED": True,
        "EMAIL_ENABLED": True,
        "EMAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "re_synthetic_private_key_for_offline_tests",
        "EMAIL_FROM_ADDRESS": "notifications@example.test",
        "EMAIL_REPLY_TO_ADDRESS": "owner@example.test",
        "AUTOMATION_FROM_EMAIL": "bookings@example.test",
    }


def response(status=200, data=None):
    result = Mock(status_code=status)
    result.json.return_value = {"id": "resend-message-id"} if data is None else data
    return result


def test_resend_uses_fixed_host_one_recipient_and_stable_private_idempotency(settings):
    http = Mock()
    http.post.return_value = response()
    client = ResendClient(settings, http=http)
    for _ in range(2):
        assert (
            client.send(
                settings["AUTOMATION_FROM_EMAIL"],
                "customer@example.test",
                "Deposit payment",
                "Pay at https://example.test/payment/pay?checkout=opaque",
                "private-outbox-key",
            )
            == "resend-message-id"
        )
    first, second = http.post.call_args_list
    assert first == second
    assert first.args == ("https://api.resend.com/emails",)
    assert first.kwargs["json"]["to"] == ["customer@example.test"]
    assert first.kwargs["headers"]["Authorization"] == "Bearer " + settings["RESEND_API_KEY"]
    assert first.kwargs["headers"]["Idempotency-Key"].startswith("b10-")
    assert "private-outbox-key" not in first.kwargs["headers"]["Idempotency-Key"]
    assert first.kwargs["allow_redirects"] is False
    assert first.kwargs["timeout"] == (3, 8)


@pytest.mark.parametrize(
    "recipient", ["a@example.test,b@example.test", "a@example.test\r\nBcc: other@example.test"]
)
def test_invalid_recipient_cannot_expand_delivery(settings, recipient):
    http = Mock()
    with pytest.raises(MailFailure) as failure:
        ResendClient(settings, http=http).send(
            settings["EMAIL_FROM_ADDRESS"], recipient, "Deposit", "Body", "job"
        )
    assert failure.value.kind == "rejected"
    http.post.assert_not_called()


@pytest.mark.parametrize(
    "status,name,kind",
    [
        (403, "validation_error", "rejected"),
        (429, "rate_limit_exceeded", "unavailable"),
        (503, "application_error", "uncertain"),
        (302, "redirect", "uncertain"),
        (409, "concurrent_idempotent_requests", "unavailable"),
        (409, "invalid_idempotent_request", "rejected"),
    ],
)
def test_resend_errors_are_private_and_have_no_hidden_retry(settings, status, name, kind):
    http = Mock()
    http.post.return_value = response(
        status, {"name": name, "message": "private-email@example.test and secret-token"}
    )
    with pytest.raises(MailFailure) as failure:
        ResendClient(settings, http=http).send(
            settings["EMAIL_FROM_ADDRESS"], "customer@example.test", "Deposit", "Body", "job"
        )
    assert failure.value.kind == kind
    assert "private-email" not in str(failure.value)
    assert "secret-token" not in str(failure.value)
    assert http.post.call_count == 1


def test_timeout_and_invalid_success_are_uncertain(settings):
    http = Mock()
    http.post.side_effect = requests.ReadTimeout("private token and recipient")
    client = ResendClient(settings, http=http)
    with pytest.raises(MailFailure, match="uncertain"):
        client.send(
            settings["EMAIL_FROM_ADDRESS"], "customer@example.test", "Deposit", "Body", "job"
        )
    http.post.side_effect = None
    http.post.return_value = response(data={})
    with pytest.raises(MailFailure) as failure:
        client.send(
            settings["EMAIL_FROM_ADDRESS"], "customer@example.test", "Deposit", "Body", "job"
        )
    assert failure.value.safe_code == "resend_response_invalid"


def test_customer_and_booking_adapters_select_their_sender_and_persistent_key(settings):
    validate_settings(settings)
    assert isinstance(create_mailer(settings), ResendMailer)
    client = Mock()
    client.send.return_value = "accepted-id"
    assert (
        ResendMailer(settings, client=client).send("customer@example.test", "Customer", "TEST-1234")
        == "accepted-id"
    )
    args, kwargs = client.send.call_args
    assert args[0] == settings["EMAIL_FROM_ADDRESS"]
    assert args[-1] == "customer-test:TEST-1234"
    assert "html" in kwargs and kwargs["reply_to"] == settings["EMAIL_REPLY_TO_ADDRESS"]
    ResendMail(settings, client=client).send(
        "customer@example.test", "Deposit", "Pay here", "job:0"
    )
    assert client.send.call_args.args == (
        settings["AUTOMATION_FROM_EMAIL"],
        "customer@example.test",
        "Deposit",
        "Pay here",
        "automation:job:0",
    )


def test_booking_resend_configuration_is_checked_even_if_customer_test_email_disabled(settings):
    settings.update(EMAIL_ENABLED=False, AUTOMATION_ENABLED=True, AUTOMATION_MODE="aws")
    validate_settings(settings)
    settings["RESEND_API_KEY"] = ""
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        validate_settings(settings)


def test_disabled_customer_mail_does_not_send(settings):
    settings["EMAIL_ENABLED"] = False
    client = Mock()
    with pytest.raises(MailFailure) as failure:
        ResendMailer(settings, client=client).send("customer@example.test", "Customer", "TEST-1234")
    assert failure.value.safe_code == "email_disabled"
    client.send.assert_not_called()


def test_uncertain_resend_retry_reuses_key_and_duplicate_queue_messages_do_not_resend():
    store, _, _, _, clock, worker, _ = delivery_setup()
    worker.settings["EMAIL_PROVIDER"] = "resend"
    mail = worker.mail = Mock()
    mail.send.side_effect = [MailFailure("uncertain", "resend_delivery_uncertain"), "accepted-id"]
    from app.automation.delivery import RetryLater

    with pytest.raises(RetryLater):
        worker.process({"job_key": "job1"})
    clock[0] += timedelta(seconds=3)
    worker.process({"job_key": "job1"})
    worker.process({"job_key": "job1"})
    assert mail.send.call_count == 2
    assert mail.send.call_args_list[0] == mail.send.call_args_list[1]
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "sent"


def test_lab_restart_after_provider_window_requires_review_and_explicit_replay():
    store, _, _, _, clock, worker, _ = delivery_setup()
    worker.settings["EMAIL_PROVIDER"] = "resend"
    mail = worker.mail = Mock()
    mail.send.side_effect = MailFailure("uncertain", "resend_delivery_uncertain")
    from app.automation.delivery import RetryLater

    with pytest.raises(RetryLater):
        worker.process({"job_key": "job1"})
    first_key = mail.send.call_args.args[-1]
    clock[0] += timedelta(days=2)
    worker.process({"job_key": "job1"})
    assert mail.send.call_count == 1
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "failed"
        assert "Resend" in tx.get_delivery("job1")["last_error"]
    worker.replay("job1", "owner")
    mail.send.side_effect = None
    mail.send.return_value = "accepted-after-owner-review"
    worker.process({"job_key": "job1", "delivery_generation": 1})
    assert mail.send.call_count == 2
    assert mail.send.call_args.args[-1] != first_key


def test_rejected_mail_is_not_retried_until_owner_corrects_configuration():
    store, _, _, _, _, worker, _ = delivery_setup()
    worker.settings["EMAIL_PROVIDER"] = "resend"
    mail = worker.mail = Mock()
    mail.send.side_effect = MailFailure("rejected", "resend_rejected")
    worker.process({"job_key": "job1"})
    worker.process({"job_key": "job1"})
    assert mail.send.call_count == 1
    with store.transaction() as tx:
        assert tx.get_delivery("job1")["status"] == "failed"
