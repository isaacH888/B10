"""Credential-store failures remain safe and actionable without AWS access."""

from unittest.mock import Mock

import pytest
from app.automation.google import AwsSecrets, GoogleFailure
from botocore import exceptions as aws_errors

PRIVATE_DETAIL = "private-provider-message-and-credential"


def client_error(code, status=400):
    return aws_errors.ClientError(
        {
            "Error": {"Code": code, "Message": PRIVATE_DETAIL},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "GetSecretValue",
    )


@pytest.mark.parametrize(
    "failure",
    [
        aws_errors.NoCredentialsError(),
        aws_errors.PartialCredentialsError(provider="login", cred_var=PRIVATE_DETAIL),
        aws_errors.CredentialRetrievalError(provider="login", error_msg=PRIVATE_DETAIL),
        aws_errors.LoginRefreshRequired(),
        aws_errors.MissingDependencyException(msg=PRIVATE_DETAIL),
        client_error("ExpiredTokenException"),
        client_error("InvalidClientTokenId"),
    ],
)
def test_credentials_failures_are_safe_during_client_initialization(monkeypatch, failure):
    factory = Mock(side_effect=failure)
    monkeypatch.setattr("boto3.client", factory)
    with pytest.raises(GoogleFailure) as raised:
        AwsSecrets().get("oauth-client")
    assert raised.value.category == "invalid"
    assert raised.value.message == AwsSecrets._CREDENTIALS_MESSAGE
    assert PRIVATE_DETAIL not in str(raised.value)
    assert raised.value.__suppress_context__
    factory.assert_called_once()


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_expired_login_during_operation_is_safe(method):
    client = Mock()
    client.get_secret_value.side_effect = aws_errors.LoginRefreshRequired()
    client.put_secret_value.side_effect = aws_errors.LoginRefreshRequired()
    arguments = ("tokens", {"refresh_token": "private"}) if method == "put" else ("tokens",)
    with pytest.raises(GoogleFailure, match="Sign in with the configured AWS profile") as raised:
        getattr(AwsSecrets(client), method)(*arguments)
    assert raised.value.category == "invalid"


@pytest.mark.parametrize(
    "code,status,category,message",
    [
        (
            "AccessDeniedException",
            403,
            "invalid",
            "access to Google Calendar credentials was denied",
        ),
        ("ThrottlingException", 400, "transient", "temporarily unavailable"),
        ("InternalServiceError", 500, "transient", "temporarily unavailable"),
        ("UnexpectedProviderFailure", 503, "transient", "temporarily unavailable"),
        ("InvalidRequestException", 400, "invalid", "secret configuration"),
    ],
)
def test_service_errors_are_classified_without_provider_details(code, status, category, message):
    client = Mock()
    client.get_secret_value.side_effect = client_error(code, status)
    with pytest.raises(GoogleFailure, match=message) as raised:
        AwsSecrets(client).get("oauth-client")
    assert raised.value.category == category
    assert PRIVATE_DETAIL not in str(raised.value)


@pytest.mark.parametrize(
    "failure",
    [
        aws_errors.EndpointConnectionError(endpoint_url=PRIVATE_DETAIL),
        aws_errors.ReadTimeoutError(endpoint_url=PRIVATE_DETAIL),
    ],
)
def test_network_failures_are_retryable(failure):
    client = Mock()
    client.get_secret_value.side_effect = failure
    with pytest.raises(GoogleFailure) as raised:
        AwsSecrets(client).get("oauth-client")
    assert raised.value.category == "transient"
    assert PRIVATE_DETAIL not in str(raised.value)


def test_missing_secret_returns_none():
    client = Mock()
    client.get_secret_value.side_effect = client_error("ResourceNotFoundException")
    assert AwsSecrets(client).get("missing-client") is None


@pytest.mark.parametrize(
    "response",
    [
        {"SecretString": PRIVATE_DETAIL},
        {"SecretString": "[]"},
        {"SecretString": "null"},
        {"SecretString": None},
        {"SecretBinary": b"private"},
    ],
)
def test_malformed_credentials_are_safe_configuration_errors(response):
    client = Mock()
    client.get_secret_value.return_value = response
    with pytest.raises(GoogleFailure, match="must be a JSON object") as raised:
        AwsSecrets(client).get("oauth-client")
    assert raised.value.category == "invalid"
    assert PRIVATE_DETAIL not in str(raised.value)


def test_secret_json_is_returned():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": '{"client_id":"test-client"}'}
    assert AwsSecrets(client).get("oauth-client") == {"client_id": "test-client"}
    client.get_secret_value.assert_called_once_with(SecretId="oauth-client")


def test_put_updates_existing_secret():
    client = Mock()
    client.put_secret_value.return_value = {"ARN": "existing-secret"}
    assert AwsSecrets(client).put("tokens", {"refresh_token": "private"}) == "existing-secret"
    client.put_secret_value.assert_called_once_with(
        SecretId="tokens", SecretString='{"refresh_token":"private"}'
    )
    client.create_secret.assert_not_called()


def test_put_creates_only_when_secret_is_missing():
    client = Mock()
    client.put_secret_value.side_effect = client_error("ResourceNotFoundException")
    client.create_secret.return_value = {"ARN": "new-secret"}
    assert AwsSecrets(client).put("tokens", {"refresh_token": "private"}) == "new-secret"
    client.create_secret.assert_called_once_with(
        Name="tokens", SecretString='{"refresh_token":"private"}'
    )


def test_create_failure_uses_the_same_safe_boundary():
    client = Mock()
    client.put_secret_value.side_effect = client_error("ResourceNotFoundException")
    client.create_secret.side_effect = client_error("AccessDeniedException", 403)
    with pytest.raises(GoogleFailure, match="access to Google Calendar credentials was denied"):
        AwsSecrets(client).put("tokens", {"refresh_token": "private"})


def test_disconnect_empties_secret_without_deleting_resource():
    client = Mock()
    client.put_secret_value.return_value = {"ARN": "existing-secret"}
    AwsSecrets(client).delete("tokens")
    client.put_secret_value.assert_called_once_with(SecretId="tokens", SecretString="{}")
    client.delete_secret.assert_not_called()


def test_other_sdk_setup_errors_have_safe_configuration_guidance(monkeypatch):
    monkeypatch.setattr("boto3.client", Mock(side_effect=aws_errors.NoRegionError()))
    with pytest.raises(GoogleFailure, match="AWS region, profile") as raised:
        AwsSecrets().get("oauth-client")
    assert raised.value.category == "invalid"
