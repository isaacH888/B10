"""Cryptographic provider checks use signed local JWTs rather than decoded mocks."""

from contextlib import contextmanager
import base64
import hashlib
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


def google_claims():
    identity, access = claims()
    identity.pop("acr")
    identity.pop("amr")
    identity["identities"] = [{"providerName": "Google", "providerType": "Google", "userId": "123456789012345678901"}]
    identity["cognito:username"] = "Google_123456789012345678901"
    return identity, access


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
    assert query["identity_provider"] == ["COGNITO"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["nonce"] == ["nonce-value"]
    assert "private-client-secret" not in result and "v" * 64 not in result


def test_google_oauth_uses_separate_admin_client_and_preserves_browser_binding(provider):
    verifier = "private-pkce-verifier" * 4
    result = provider.authorization_url("private-state", "private-nonce", verifier, "google")
    url = urlsplit(result)
    query = parse_qs(url.query)
    assert url.netloc == "staff.auth.us-east-1.amazoncognito.com"
    assert query["client_id"] == ["fixture-client"]
    assert query["redirect_uri"] == ["http://localhost:5173/api/v1/admin/callback"]
    assert query["identity_provider"] == ["Google"]
    assert query["prompt"] == ["select_account"]
    assert query["state"] == ["private-state"]
    assert query["nonce"] == ["private-nonce"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")]
    assert set(query["scope"][0].split()) == {"openid", "email", "profile", "aws.cognito.signin.user.admin"}
    assert "acr_values" not in query
    assert "private-client-secret" not in result and verifier not in result


@pytest.mark.parametrize("username", ["Google_123456789012345678901", "google_123456789012345678901"])
def test_signed_google_identity_is_pinned_without_claiming_cognito_mfa(provider, key, username):
    identity, access = google_claims()
    identity["cognito:username"] = username
    result = provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW, provider="google")
    assert result["subject"] == "fixture-subject"
    assert result["google_subject"] == "123456789012345678901"
    assert result["provider"] == "google"
    assert result["provider_username"] == username
    assert result["assurance"] == {"acr": None, "amr": []}


@pytest.mark.parametrize("identity_changes", [
    {"identities": None}, {"identities": []}, {"identities": "Google"},
    {"identities": [None]}, {"identities": [{"providerName": "Google", "providerType": "Google", "userId": ""}]},
    {"identities": [{"providerName": "google", "providerType": "Google", "userId": "123456789012345678901"}]},
    {"identities": [{"providerName": "Google", "providerType": "OIDC", "userId": "123456789012345678901"}]},
    {"identities": [{"providerName": "Google", "providerType": "Google", "userId": 123456789012345678901}]},
    {"identities": [{"providerName": "Google", "providerType": "Google", "userId": "different-subject"}]},
    {"identities": [{"providerName": "Google", "providerType": "Google", "userId": "123456789012345678901"}] * 2},
    {"cognito:username": "approved-password-user"}, {"cognito:username": "Google_someone-else"},
    {"cognito:username": "fixture@example.invalid"}, {"cognito:username": None},
])
def test_google_signed_identity_rejects_ambiguous_links_and_mismatched_profiles(provider, key, identity_changes):
    identity, access = google_claims()
    identity.update(identity_changes)
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, provider="google")
    assert failure.value.code == "authentication_failed"


@pytest.mark.parametrize("field,value", [
    ("iss", "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_customer"),
    ("aud", "customer-client"), ("nonce", "another-browser"), ("exp", NOW), ("iat", NOW + 61),
    ("nbf", NOW + 61), ("email_verified", False), ("email_verified", "true"),
    ("email", ""), ("email", None), ("auth_time", NOW + 61),
])
def test_google_signed_tokens_still_require_issuer_client_nonce_expiry_and_verified_email(provider, key, field, value):
    identity, access = google_claims()
    identity[field] = value
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", provider="google")


@pytest.mark.parametrize("field,value", [
    ("sub", "someone-else"), ("client_id", "customer-client"),
    ("iss", "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_customer"),
    ("exp", NOW), ("scope", "openid email"), ("token_use", "id"),
])
def test_google_access_token_is_bound_to_signed_admin_identity(provider, key, field, value):
    identity, access = google_claims()
    access[field] = value
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW, provider="google")


def test_google_token_with_wrong_signature_is_rejected(provider):
    wrong_key = RSAKey.generate_key(parameters={"kid": "fixture-key"})
    identity, access = google_claims()
    with pytest.raises(AuthError):
        provider.validate(tokens(wrong_key, identity, access), NOW, provider="google")


def test_google_identity_cannot_use_password_route_to_skip_native_mfa(provider, key):
    identity, access = google_claims()
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, provider="password")
    assert failure.value.code == "mfa_required"


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


def test_google_current_user_pins_external_username_without_native_cognito_mfa(provider, monkeypatch):
    captured = {}
    class Response:
        status_code = 200
        def json(self):
            return {"Username": "Google_123456789012345678901", "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}]}
    def request(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr("app.auth.provider.requests.post", request)
    provider.current_user("private-access-token", "fixture-subject", provider="google", google_subject="123456789012345678901")
    assert captured["url"] == "https://cognito-idp.us-east-1.amazonaws.com/"
    assert captured["json"] == {"AccessToken": "private-access-token"}
    assert captured["headers"]["X-Amz-Target"].endswith(".GetUser")
    assert "Authorization" not in captured["headers"]


@pytest.mark.parametrize("username,subject,google_subject", [
    ("Google_123456789012345678901", "different-subject", "123456789012345678901"),
    ("Google_another-google-user", "fixture-subject", "123456789012345678901"),
    ("approved-password-user", "fixture-subject", "123456789012345678901"),
    (None, "fixture-subject", "123456789012345678901"),
    ("Google_123456789012345678901", "fixture-subject", None),
])
def test_google_get_user_rejects_wrong_identity_and_native_linked_accounts(provider, monkeypatch, username, subject, google_subject):
    class Response:
        status_code = 200
        def json(self):
            return {"Username": username, "UserAttributes": [{"Name": "sub", "Value": subject}], "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"]}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject", provider="google", google_subject=google_subject)
    assert failure.value.code == "authentication_failed"


@pytest.mark.parametrize("code", ["NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException"])
def test_google_get_user_rejects_disabled_and_revoked_profiles(provider, monkeypatch, code):
    class Response:
        status_code = 400
        def json(self):
            return {"__type": code, "message": "private-provider-details"}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject", provider="google", google_subject="123456789012345678901")
    assert failure.value.code == "session_expired"
    assert "private" not in failure.value.message


def test_password_current_user_continues_to_require_native_totp(provider, monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"Username": "approved-password-user", "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}], "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"]}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    assert provider.current_user("private-access-token", "fixture-subject", provider="password") is None


@pytest.mark.parametrize("method", ["password", "google"])
def test_customer_pool_login_preserves_existing_non_admin_assurance(provider, key, method):
    issuer = ISSUER.replace("fixture", "customer")
    customer = CognitoProvider({"AUTH_ORIGIN": "http://localhost:5173", "COGNITO_CUSTOMER_ISSUER": issuer,
                               "COGNITO_CUSTOMER_CLIENT_ID": "customer-client", "COGNITO_CUSTOMER_CLIENT_SECRET": "private-customer-secret",
                               "COGNITO_CUSTOMER_DOMAIN": "https://customers.auth.us-east-1.amazoncognito.com"}, "customer")
    identity, access = google_claims() if method == "google" else claims()
    identity.pop("acr", None)
    identity.pop("amr", None)
    identity.update(iss=issuer, aud="customer-client")
    access.update(iss=issuer, client_id="customer-client")
    result = customer.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", provider=method)
    assert result["issuer"] == issuer
    assert result["provider"] == method
    assert result["assurance"] == {"acr": None, "amr": []}
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW, provider=method)
    query = parse_qs(urlsplit(customer.authorization_url("customer-state", "customer-nonce", "v" * 64, method)).query)
    assert query["client_id"] == ["customer-client"]
    assert query["redirect_uri"] == ["http://localhost:5173/api/v1/customer/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert "acr_values" not in query
    if method == "google":
        assert query["identity_provider"] == ["Google"]


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
