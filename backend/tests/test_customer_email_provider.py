"""SES payloads and error boundaries are checked offline; these are not live AWS tests."""

from unittest.mock import Mock

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from botocore.stub import Stubber
import pytest

from app.email.provider import MailFailure, SESMailer, _session
from app.email.settings import environment_settings, valid_address, validate_settings
from app.email.templates import render_confirmation


@pytest.fixture
def settings():
    return {
        "AUTH_ENABLED": True,
        "EMAIL_ENABLED": True,
        "EMAIL_PROVIDER": "ses",
        "EMAIL_AWS_REGION": "us-east-1",
        "EMAIL_FROM_ADDRESS": "orders@example.invalid",
        "EMAIL_REPLY_TO_ADDRESS": "support@example.invalid",
        "EMAIL_SES_CONFIGURATION_SET": "customer-test",
        "EMAIL_AWS_ACCESS_KEY_ID": "",
        "EMAIL_AWS_SECRET_ACCESS_KEY": "",
        "EMAIL_AWS_SESSION_TOKEN": "",
    }


def test_template_is_a_sample_with_no_charge_or_booking():
    message = render_confirmation("Customer", "TEST-1234")
    assert message["subject"] == "[TEST] Popssibilities order confirmation - TEST-1234"
    for body in (message["html"], message["text"]):
        assert "Sample catering package" in body
        assert "50 (sample)" in body
        assert "no payment has been processed" in body
        assert "no booking has been confirmed" in body


def test_profile_name_is_escaped_and_cannot_inject_subject_or_headers():
    message = render_confirmation('<script>alert("x")</script>\r\nBcc: other@example.invalid', "TEST-1234")
    assert "<script>" not in message["html"]
    assert "&lt;script&gt;" in message["html"]
    assert "\r" not in message["text"]
    assert message["subject"] == "[TEST] Popssibilities order confirmation - TEST-1234"


@pytest.mark.parametrize("reference", [None, "", "a" * 81, "id\r\nBcc: other@example.invalid", "<script>"])
def test_reference_cannot_inject_headers_or_markup(reference):
    with pytest.raises(ValueError):
        render_confirmation("Customer", reference)


def test_missing_profile_name_uses_safe_greeting():
    assert "Hi there," in render_confirmation(None, "TEST-1234")["text"]


@pytest.mark.parametrize("address", ["a@example.invalid", "first.last+test@example.invalid"])
def test_bare_mailboxes_accepted(address):
    assert valid_address(address)


@pytest.mark.parametrize("address", [None, "", "Name <a@example.invalid>", "a@example.invalid,b@example.invalid",
                                      "a@example.invalid\nBcc: b@example.invalid", "a@localhost", "a@ex..invalid"])
def test_unsafe_or_multiple_mailboxes_rejected(address):
    assert not valid_address(address)


def test_environment_defaults_disabled(monkeypatch):
    monkeypatch.delenv("EMAIL_ENABLED", raising=False)
    assert environment_settings()["EMAIL_ENABLED"] is False
    validate_settings({"EMAIL_ENABLED": False})


def test_environment_boolean_must_be_explicit(monkeypatch):
    monkeypatch.setenv("EMAIL_ENABLED", "yes")
    with pytest.raises(ValueError):
        environment_settings()


@pytest.mark.parametrize("changes", [
    {"AUTH_ENABLED": False}, {"EMAIL_PROVIDER": "smtp"}, {"EMAIL_FROM_ADDRESS": ""},
    {"EMAIL_REPLY_TO_ADDRESS": "bad\r\nheader"}, {"EMAIL_AWS_REGION": "https://elsewhere.invalid"},
    {"EMAIL_SES_CONFIGURATION_SET": "bad/set"}, {"EMAIL_AWS_ACCESS_KEY_ID": "partial"},
    {"EMAIL_AWS_SESSION_TOKEN": "orphan-token"},
])
def test_enabled_configuration_fails_closed(settings, changes):
    settings.update(changes)
    with pytest.raises(ValueError):
        validate_settings(settings)


def test_disabled_mailer_never_constructs_client_or_sends(settings):
    settings["EMAIL_ENABLED"] = False
    client = Mock()
    mailer = SESMailer(settings, client=client)
    with pytest.raises(MailFailure) as failure:
        mailer.send("customer@example.invalid", "Customer", "TEST-1234")
    assert failure.value.safe_code == "email_disabled"
    client.send_email.assert_not_called()


def test_ses_payload_has_exactly_one_recipient_fixed_sender_and_both_bodies(settings):
    client = boto3.client("sesv2", region_name="us-east-1", aws_access_key_id="fixture-access",
                          aws_secret_access_key="fixture-secret")
    message = render_confirmation("Customer", "TEST-1234")
    expected = {
        "FromEmailAddress": "orders@example.invalid",
        "Destination": {"ToAddresses": ["customer@example.invalid"]},
        "ReplyToAddresses": ["support@example.invalid"],
        "ConfigurationSetName": "customer-test",
        "EmailTags": [{"Name": "kind", "Value": "customer-test-confirmation"}],
        "Content": {"Simple": {
            "Subject": {"Charset": "UTF-8", "Data": message["subject"]},
            "Body": {"Text": {"Charset": "UTF-8", "Data": message["text"]},
                     "Html": {"Charset": "UTF-8", "Data": message["html"]}},
        }},
    }
    with Stubber(client) as stubber:
        stubber.add_response("send_email", {"MessageId": "fixture-ses-id"}, expected)
        assert SESMailer(settings, client=client).send("customer@example.invalid", "Customer", "TEST-1234") == "fixture-ses-id"
        stubber.assert_no_pending_responses()


def test_configuration_set_is_optional(settings):
    settings["EMAIL_SES_CONFIGURATION_SET"] = ""
    client = Mock()
    client.send_email.return_value = {"MessageId": "fixture-ses-id"}
    SESMailer(settings, client=client).send("customer@example.invalid", "Customer", "TEST-1234")
    assert "ConfigurationSetName" not in client.send_email.call_args.kwargs


@pytest.mark.parametrize("status,code,kind,safe_code", [
    (400, "MessageRejected", "rejected", "ses_rejected"),
    (403, "AccessDeniedException", "rejected", "ses_rejected"),
    (429, "TooManyRequestsException", "unavailable", "ses_throttled"),
    (500, "InternalServiceError", "uncertain", "ses_delivery_uncertain"),
])
def test_error_responses_do_not_leak_provider_details_or_retry(settings, status, code, kind, safe_code):
    client = Mock()
    client.send_email.side_effect = ClientError({
        "Error": {"Code": code, "Message": "private-customer@example.invalid and private-credential"},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }, "SendEmail")
    with pytest.raises(MailFailure) as failure:
        SESMailer(settings, client=client).send("customer@example.invalid", "Customer", "TEST-1234")
    assert failure.value.kind == kind
    assert failure.value.safe_code == safe_code
    assert "private-" not in str(failure.value)
    assert failure.value.__suppress_context__ is True
    client.send_email.assert_called_once()


@pytest.mark.parametrize("error", [ReadTimeoutError(endpoint_url="https://email.us-east-1.amazonaws.com"),
                                  EndpointConnectionError(endpoint_url="https://email.us-east-1.amazonaws.com")])
def test_network_errors_are_uncertain_and_never_automatically_resent(settings, error):
    client = Mock()
    client.send_email.side_effect = error
    with pytest.raises(MailFailure) as failure:
        SESMailer(settings, client=client).send("customer@example.invalid", "Customer", "TEST-1234")
    assert failure.value.kind == "uncertain"
    client.send_email.assert_called_once()


@pytest.mark.parametrize("response", [{}, {"MessageId": ""}, {"MessageId": None}, {"MessageId": "a" * 257}, None])
def test_missing_acceptance_id_is_uncertain(settings, response):
    client = Mock()
    client.send_email.return_value = response
    with pytest.raises(MailFailure) as failure:
        SESMailer(settings, client=client).send("customer@example.invalid", "Customer", "TEST-1234")
    assert failure.value.kind == "uncertain"


def test_mailer_ignores_operator_profiles_and_generic_aws_keys(settings, monkeypatch, tmp_path):
    shared = tmp_path / "private-operator-credentials"
    shared.write_text("[private-operator]\naws_access_key_id=operator-access\naws_secret_access_key=operator-secret\n")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(shared))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(shared))
    monkeypatch.setenv("AWS_PROFILE", "private-operator")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "another-private-operator")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "operator-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "operator-secret")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for key in ("AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        monkeypatch.delenv(key, raising=False)
    session = _session(settings)
    assert session.get_credentials() is None
    methods = {p.METHOD for p in session._session.get_component("credential_provider").providers}
    assert methods == {"container-role", "iam-role", "assume-role-with-web-identity"}


def test_dedicated_email_credentials_are_used_without_operator_credentials(settings, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "private-operator")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "another-private-operator")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "operator-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "operator-secret")
    settings.update(EMAIL_AWS_ACCESS_KEY_ID="mailer-access", EMAIL_AWS_SECRET_ACCESS_KEY="mailer-secret",
                    EMAIL_AWS_SESSION_TOKEN="mailer-token")
    session = _session(settings)
    credentials = session.get_credentials().get_frozen_credentials()
    assert (credentials.access_key, credentials.secret_key, credentials.token) == ("mailer-access", "mailer-secret", "mailer-token")
    assert session.client("sesv2").meta.region_name == "us-east-1"


def test_client_has_bounded_timeouts_no_hidden_send_retry_and_no_environment_endpoint_override(settings, monkeypatch):
    session = Mock()
    client = Mock()
    client.send_email.return_value = {"MessageId": "fixture-ses-id"}
    session.client.return_value = client
    monkeypatch.setattr("app.email.provider._session", lambda settings: session)
    mailer = SESMailer(settings)
    mailer.send("customer@example.invalid", "Customer", "TEST-1234")
    config = session.client.call_args.kwargs["config"]
    assert config.connect_timeout == 3
    assert config.read_timeout == 5
    assert config.retries["total_max_attempts"] == 1
    assert config.ignore_configured_endpoint_urls is True
    mailer.send("customer@example.invalid", "Customer", "TEST-5678")
    session.client.assert_called_once()
