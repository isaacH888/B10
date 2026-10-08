"""Cryptographic provider checks use signed local JWTs rather than decoded mocks."""

from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey
import pytest

from app.auth.errors import AuthError
from app.auth.provider import CognitoProvider


NOW = 1791410400
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_fixture"


@pytest.fixture
def key():
    return RSAKey.generate_key(parameters={"kid": "fixture-key"})


@pytest.fixture
def provider(key, monkeypatch):
    provider = CognitoProvider({"AUTH_ORIGIN": "http://localhost:5173", "COGNITO_ADMIN_ISSUER": ISSUER,
                               "COGNITO_ADMIN_CLIENT_ID": "fixture-client", "COGNITO_ADMIN_CLIENT_SECRET": "private-client-secret",
                               "COGNITO_ADMIN_DOMAIN": "https://staff.auth.us-east-1.amazoncognito.com"}, "admin")
    class KeysResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"keys": [key.as_dict()]}
    monkeypatch.setattr("app.auth.provider.requests.get", lambda *args, **kwargs: KeysResponse())
    return provider


def claims():
    identity = {"iss": ISSUER, "sub": "fixture-subject", "aud": "fixture-client", "token_use": "id",
                "exp": NOW + 300, "iat": NOW, "auth_time": NOW, "email": "fixture@example.invalid",
                "email_verified": True, "nonce": "fixture-nonce", "acr": "urn:cognito:loa:4", "amr": ["pwd", "otp", "mfa"]}
    access = {"iss": ISSUER, "sub": "fixture-subject", "client_id": "fixture-client", "token_use": "access",
              "exp": NOW + 300, "iat": NOW, "scope": "openid aws.cognito.signin.user.admin"}
    return identity, access


def tokens(key, identity=None, access=None):
    original_id, original_access = claims()
    return {"id_token": jwt.encode({"alg": "RS256", "kid": "fixture-key"}, identity or original_id, key),
            "access_token": jwt.encode({"alg": "RS256", "kid": "fixture-key"}, access or original_access, key),
            "refresh_token": "private-refresh-token"}


def test_valid_signed_mfa_identity(provider, key):
    result = provider.validate(tokens(key), NOW, nonce="fixture-nonce", started_at=NOW)
    assert result["subject"] == "fixture-subject"
    assert result["auth_time"] == NOW


@pytest.mark.parametrize("field,value", [
    ("iss", "https://evil.example.invalid"), ("aud", "different-client"), ("sub", ""),
    ("token_use", "access"), ("exp", NOW), ("iat", NOW + 61), ("nbf", NOW + 61),
    ("email_verified", False), ("auth_time", NOW - 61), ("acr", "urn:cognito:loa:1"),
    ("amr", ["pwd"]), ("nonce", "other-browser"),
])
def test_signed_but_unacceptable_claims_rejected(provider, key, field, value):
    identity, access = claims()
    identity[field] = value
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)


@pytest.mark.parametrize("field,value", [("sub", "other-subject"), ("client_id", "other-client"),
                                         ("iss", "https://evil.example.invalid"), ("scope", "openid"), ("token_use", "id")])
def test_access_token_also_bound_to_client_subject_and_scope(provider, key, field, value):
    identity, access = claims()
    access[field] = value
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW)


def test_wrong_signing_key_rejected(provider):
    wrong = RSAKey.generate_key(parameters={"kid": "fixture-key"})
    with pytest.raises(AuthError):
        provider.validate(tokens(wrong), NOW)


def test_oauth_request_requests_fresh_totp_with_pkce_and_no_secret(provider):
    result = provider.authorization_url("state-value", "nonce-value", "v" * 64, "password")
    query = parse_qs(urlsplit(result).query)
    assert query["prompt"] == ["login"]
    assert query["max_age"] == ["0"]
    assert query["acr_values"] == ["urn:cognito:loa:4"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["nonce"] == ["nonce-value"]
    assert "private-client-secret" not in result and "v" * 64 not in result


def test_current_user_rejects_revocation_and_removed_mfa(provider, monkeypatch):
    class Response:
        status_code = 400
        def json(self):
            return {"__type": "NotAuthorizedException", "message": "private-provider-detail"}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as error:
        provider.current_user("private-access-token", "fixture-subject")
    assert error.value.code == "session_expired"
    assert "private" not in error.value.message
    Response.status_code = 200
    Response.json = lambda self: {"UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}], "UserMFASettingList": []}
    with pytest.raises(AuthError) as error:
        provider.current_user("private-access-token", "fixture-subject")
    assert error.value.code == "mfa_required"


@pytest.mark.parametrize("operation", ["exchange", "refresh"])
@pytest.mark.parametrize("code,status", [("server_error", 503), ("temporarily_unavailable", 503), ("invalid_grant", 401)])
def test_oauth_errors_preserve_transient_outage_semantics(provider, monkeypatch, operation, code, status):
    from authlib.oauth2.rfc6749.errors import OAuth2Error
    class FailedClient:
        def fetch_token(self, *args, **kwargs):
            raise OAuth2Error(error=code, description="Private provider details")
    @contextmanager
    def oauth():
        yield FailedClient()
    monkeypatch.setattr(provider, "oauth", oauth)
    with pytest.raises(AuthError) as failure:
        if operation == "exchange":
            provider.exchange("private-code", "private-verifier")
        else:
            provider.refresh("private-refresh")
    assert failure.value.status == status
    assert "Private" not in failure.value.message


@pytest.mark.parametrize("body", [[], {"UserAttributes": None}, {"UserAttributes": [{}]},
                                    {"UserMFASettingList": "SOFTWARE_TOKEN_MFA"}])
def test_malformed_current_user_response_fails_safely(provider, monkeypatch, body):
    class Response:
        status_code = 200
        def json(self):
            return body
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.status == 503
