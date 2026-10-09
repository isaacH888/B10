"""Cryptographic provider checks use signed local JWTs rather than decoded mocks."""

from contextlib import contextmanager
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

from joserfc import jwt
from joserfc.jwk import RSAKey
import pytest
import requests

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


@pytest.mark.parametrize("missing", ["acr", "amr", "both"])
def test_missing_signed_mfa_claims_have_private_diagnostic(provider, key, missing):
    identity, access = claims()
    for field in ("acr", "amr") if missing == "both" else (missing,):
        identity.pop(field)
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)
    assert failure.value.code == "mfa_required"
    assert failure.value.status == 403
    assert failure.value.reason == "mfa_assurance_missing"
    assert "mfa_assurance_missing" not in failure.value.message
    assert identity["email"] not in failure.value.message


@pytest.mark.parametrize("access_changes,assured", [
    ({}, False),
    ({"acr": "urn:cognito:loa:4", "amr": ["pwd", "otp", "mfa"]}, True),
    ({"acr": "urn:cognito:loa:4", "amr": ["pwd"]}, False),
    ({"acr": "urn:cognito:loa:4", "amr": ["pwd", "otp", "mfa", {}]}, False),
])
def test_mfa_diagnostics_record_only_signed_claim_presence_booleans(provider, key, access_changes, assured):
    identity, access = claims()
    identity.pop("acr")
    identity.pop("amr")
    access.update(access_changes)
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)
    assert failure.value.code == "mfa_required"
    assert failure.value.reason == "mfa_assurance_missing"
    assert failure.value.diagnostics == {"id_acr_present": False, "id_amr_present": False,
                                        "access_acr_present": "acr" in access_changes,
                                        "access_amr_present": "amr" in access_changes,
                                        "access_totp_assured": assured}
    assert all(type(value) is bool for value in failure.value.diagnostics.values())
    assert identity["sub"] not in str(failure.value.diagnostics)
    assert identity["email"] not in str(failure.value.diagnostics)


@pytest.mark.parametrize("changes", [
    {"acr": "urn:cognito:loa:1", "amr": ["pwd"]},
    {"acr": "urn:cognito:loa:3", "amr": ["pwd", "sms", "mfa"]},
    {"amr": ["pwd", "otp"]}, {"amr": []}, {"amr": "pwd otp mfa"},
    {"amr": ["pwd", "otp", "mfa", {}]},
])
def test_insufficient_signed_mfa_claims_have_private_diagnostic(provider, key, changes):
    identity, access = claims()
    identity.update(changes)
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)
    assert failure.value.code == "mfa_required"
    assert failure.value.reason == "mfa_assurance_insufficient"
    assert "mfa_assurance_insufficient" not in failure.value.message


def test_signed_mfa_freshness_has_private_diagnostic_and_keeps_clock_skew_boundary(provider, key):
    identity, access = claims()
    identity["auth_time"] = NOW - 61
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)
    assert failure.value.code == "mfa_required"
    assert failure.value.reason == "mfa_authentication_stale"
    identity["auth_time"] = NOW - 60
    assert provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)["auth_time"] == NOW - 60


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


@pytest.mark.parametrize("operation", ["authorize", "validate", "get_user"])
def test_admin_google_is_rejected_before_provider_io(provider, monkeypatch, operation):
    def unexpected(*args, **kwargs):
        raise AssertionError("A removed admin login method must not contact the provider.")
    monkeypatch.setattr(provider, "oauth", unexpected)
    monkeypatch.setattr(provider, "_decode", unexpected)
    monkeypatch.setattr("app.auth.provider.requests.post", unexpected)
    with pytest.raises(AuthError) as failure:
        if operation == "authorize":
            provider.authorization_url("state", "nonce", "v" * 64, "google")
        elif operation == "validate":
            provider.validate({}, NOW, provider="google")
        else:
            provider.current_user("private-token", "fixture-subject", provider="google")
    assert failure.value.code == ("validation_error" if operation == "authorize" else "authentication_failed")


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
    Response.json = lambda self: {"Username": "approved-password-user", "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}],
                                 "UserMFASettingList": [], "ConfiguredUserAuthFactors": ["PASSWORD"]}
    with pytest.raises(AuthError) as error:
        provider.current_user("private-access-token", "fixture-subject")
    assert error.value.code == "mfa_required"


def test_password_current_user_continues_to_require_native_totp(provider, monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"Username": "approved-password-user", "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}], "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"]}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    assert provider.current_user("private-access-token", "fixture-subject", provider="password") is None


@pytest.mark.parametrize("methods", [None, [], ["SMS_MFA"]])
def test_missing_native_totp_registration_has_private_diagnostic(provider, monkeypatch, methods):
    class Response:
        status_code = 200
        def json(self):
            body = {"Username": "approved-password-user", "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}],
                    "ConfiguredUserAuthFactors": ["PASSWORD"]}
            if methods is not None:
                body["UserMFASettingList"] = methods
            return body
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.code == "mfa_required"
    assert failure.value.status == 403
    assert failure.value.reason == "mfa_enrollment_missing"
    assert "mfa_enrollment_missing" not in failure.value.message
    assert "private-access-token" not in failure.value.message


@pytest.fixture
def user_operations(monkeypatch):
    responses = {"GetUser": {"status": 200, "body": {"Username": "approved-password-user",
                    "UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}]}},
                 "GetUserAuthFactors": {"status": 200, "body": {"Username": "approved-password-user",
                    "ConfiguredUserAuthFactors": ["PASSWORD", "SOFTWARE_TOKEN"]}}}
    calls = []

    class Response:
        def __init__(self, data):
            self.data = data
            self.status_code = data["status"]
        def json(self):
            return self.data["body"]

    def post(url, **kwargs):
        operation = kwargs["headers"]["X-Amz-Target"].split(".")[-1]
        calls.append((operation, url, kwargs))
        if responses[operation].get("exception"):
            raise responses[operation]["exception"]
        return Response(responses[operation])

    monkeypatch.setattr("app.auth.provider.requests.post", post)
    return responses, calls


def test_registered_totp_without_preference_supports_a_signed_mfa_login(provider, key, user_operations):
    _, calls = user_operations
    signed = tokens(key)
    identity = provider.validate(signed, NOW, nonce="fixture-nonce", started_at=NOW)
    assert provider.current_user(signed["access_token"], identity["subject"]) is None
    assert [call[0] for call in calls] == ["GetUser", "GetUserAuthFactors"]
    for _, url, arguments in calls:
        assert url == "https://cognito-idp.us-east-1.amazonaws.com/"
        assert arguments["json"] == {"AccessToken": signed["access_token"]}
        assert arguments["timeout"] == (3, 5)
        assert "Authorization" not in arguments["headers"]
        assert set(arguments["headers"]) == {"Content-Type", "X-Amz-Target"}


def test_registered_factor_does_not_bypass_missing_signed_mfa_proof(provider, key, user_operations):
    _, calls = user_operations
    identity, access = claims()
    identity.pop("acr")
    identity.pop("amr")
    with pytest.raises(AuthError) as failure:
        verified = provider.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", started_at=NOW)
        provider.current_user("private-access-token", verified["subject"])
    assert failure.value.code == "mfa_required"
    assert failure.value.reason == "mfa_assurance_missing"
    assert not calls


def test_activated_native_totp_does_not_need_factor_query(provider, user_operations):
    responses, calls = user_operations
    responses["GetUser"]["body"]["UserMFASettingList"] = ["SOFTWARE_TOKEN_MFA"]
    assert provider.current_user("private-access-token", "fixture-subject") is None
    assert [call[0] for call in calls] == ["GetUser"]


def test_customer_without_totp_does_not_query_admin_factor_state(customer, user_operations):
    _, calls = user_operations
    assert customer.current_user("private-access-token", "fixture-subject", provider="google") is None
    assert [call[0] for call in calls] == ["GetUser"]


@pytest.mark.parametrize("configured", [[], ["PASSWORD"], ["PASSWORD", "SMS_OTP", "EMAIL_OTP"]])
def test_removed_software_factor_still_denies_access(provider, user_operations, configured):
    responses, calls = user_operations
    responses["GetUserAuthFactors"]["body"]["ConfiguredUserAuthFactors"] = configured
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.code == "mfa_required"
    assert failure.value.reason == "mfa_enrollment_missing"
    assert [call[0] for call in calls] == ["GetUser", "GetUserAuthFactors"]


@pytest.mark.parametrize("body,status", [
    ([], 503), (None, 503), ({}, 503),
    ({"Username": "approved-password-user", "ConfiguredUserAuthFactors": None}, 503),
    ({"Username": "approved-password-user", "ConfiguredUserAuthFactors": "SOFTWARE_TOKEN"}, 503),
    ({"Username": "approved-password-user", "ConfiguredUserAuthFactors": ["SOFTWARE_TOKEN", {}]}, 503),
    ({"Username": "different-password-user", "ConfiguredUserAuthFactors": ["SOFTWARE_TOKEN"]}, 401),
    ({"ConfiguredUserAuthFactors": ["SOFTWARE_TOKEN"]}, 401),
])
def test_factor_response_fails_closed_on_malformed_or_wrong_user(provider, user_operations, body, status):
    responses, _ = user_operations
    responses["GetUserAuthFactors"]["body"] = body
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.status == status


@pytest.mark.parametrize("username", [None, "", 12])
def test_factor_lookup_requires_the_get_user_username(provider, user_operations, username):
    responses, calls = user_operations
    responses["GetUser"]["body"]["Username"] = username
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.status == 503
    assert [call[0] for call in calls] == ["GetUser"]


@pytest.mark.parametrize("code,status", [("NotAuthorizedException", 401), ("UserNotFoundException", 401),
                                         ("PasswordResetRequiredException", 401), ("InternalErrorException", 503),
                                         ("TooManyRequestsException", 503), ("OperationNotEnabledException", 503)])
def test_factor_provider_errors_preserve_revocation_and_outage_handling(provider, user_operations, code, status):
    responses, _ = user_operations
    responses["GetUserAuthFactors"].update(status=400, body={"__type": code, "message": "private-provider-details"})
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.status == status
    assert "private" not in failure.value.message


def test_factor_network_outage_grants_no_access(provider, user_operations):
    responses, _ = user_operations
    responses["GetUserAuthFactors"]["exception"] = requests.Timeout("private-provider-details")
    with pytest.raises(AuthError) as failure:
        provider.current_user("private-access-token", "fixture-subject")
    assert failure.value.status == 503
    assert "private" not in failure.value.message


@pytest.fixture
def customer(provider):
    # The provider fixture installs a local public key for both pools.
    return CognitoProvider({"AUTH_ORIGIN": "http://localhost:5173",
                           "COGNITO_CUSTOMER_ISSUER": ISSUER.replace("fixture", "customer"),
                           "COGNITO_CUSTOMER_CLIENT_ID": "customer-client",
                           "COGNITO_CUSTOMER_CLIENT_SECRET": "private-customer-secret",
                           "COGNITO_CUSTOMER_DOMAIN": "https://customers.auth.us-east-1.amazoncognito.com"}, "customer")


def customer_claims(customer, method="google"):
    identity, access = google_claims() if method == "google" else claims()
    identity.pop("acr", None)
    identity.pop("amr", None)
    identity.update(iss=customer.issuer, aud=customer.client_id)
    access.update(iss=customer.issuer, client_id=customer.client_id)
    return identity, access


@pytest.mark.parametrize("method", ["password", "google"])
def test_customer_pool_login_preserves_existing_non_admin_assurance(customer, provider, key, method):
    identity, access = customer_claims(customer, method)
    result = customer.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", provider=method)
    assert result["issuer"] == customer.issuer
    assert result["provider"] == method
    assert result["assurance"] == {"acr": None, "amr": []}
    with pytest.raises(AuthError):
        provider.validate(tokens(key, identity, access), NOW, provider=method)
    verifier = "private-pkce-verifier" * 4
    query = parse_qs(urlsplit(customer.authorization_url("customer-state", "customer-nonce", verifier, method)).query)
    assert query["client_id"] == ["customer-client"]
    assert query["redirect_uri"] == ["http://localhost:5173/api/v1/customer/callback"]
    assert query["state"] == ["customer-state"]
    assert query["nonce"] == ["customer-nonce"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")]
    assert "acr_values" not in query
    if method == "google":
        assert query["identity_provider"] == ["Google"]


@pytest.mark.parametrize("field,value", [
    ("iss", ISSUER), ("aud", "fixture-client"), ("nonce", "another-browser"),
    ("exp", NOW), ("iat", NOW + 61), ("nbf", NOW + 61), ("email_verified", False),
    ("email_verified", "true"), ("email", ""), ("email", None), ("auth_time", NOW + 61),
])
def test_customer_google_checks_signed_identity_claims(customer, key, field, value):
    identity, access = customer_claims(customer)
    identity[field] = value
    with pytest.raises(AuthError):
        customer.validate(tokens(key, identity, access), NOW, nonce="fixture-nonce", provider="google")


@pytest.mark.parametrize("field,value", [
    ("sub", "someone-else"), ("client_id", "fixture-client"), ("iss", ISSUER),
    ("exp", NOW), ("scope", "openid email"), ("token_use", "id"),
])
def test_customer_google_checks_access_token_binding(customer, key, field, value):
    identity, access = customer_claims(customer)
    access[field] = value
    with pytest.raises(AuthError):
        customer.validate(tokens(key, identity, access), NOW, provider="google")


def test_customer_google_rejects_wrong_signature(customer):
    wrong_key = RSAKey.generate_key(parameters={"kid": "fixture-key"})
    identity, access = customer_claims(customer)
    with pytest.raises(AuthError):
        customer.validate(tokens(wrong_key, identity, access), NOW, provider="google")


@pytest.mark.parametrize("code", ["NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException"])
def test_customer_google_rejects_disabled_or_revoked_provider_user(customer, monkeypatch, code):
    class Response:
        status_code = 400
        def json(self):
            return {"__type": code, "message": "private-provider-details"}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(AuthError) as failure:
        customer.current_user("private-access-token", "fixture-subject", provider="google")
    assert failure.value.code == "session_expired"
    assert "private" not in failure.value.message


def test_customer_google_get_user_requires_same_subject_without_admin_mfa(customer, monkeypatch):
    class Response:
        status_code = 200
        def json(self):
            return {"UserAttributes": [{"Name": "sub", "Value": "fixture-subject"}]}
    monkeypatch.setattr("app.auth.provider.requests.post", lambda *args, **kwargs: Response())
    assert customer.current_user("private-access-token", "fixture-subject", provider="google") is None
    with pytest.raises(AuthError):
        customer.current_user("private-access-token", "someone-else", provider="google")


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


NATIVE_SESSION = 'fixture-cognito-challenge-session-0001'
NATIVE_USERNAME = 'fixture-subject'


def native_response(challenge, **parameters):
    return {'ChallengeName': challenge, 'Session': NATIVE_SESSION, 'ChallengeParameters': parameters}


def test_native_public_password_totp_sequence_uses_secret_hash_without_iam(provider, monkeypatch):
    observed = []
    responses = [native_response('SOFTWARE_TOKEN_MFA'),
                 {'AuthenticationResult': {'AccessToken': 'fixture-access', 'IdToken': 'fixture-id',
                                          'RefreshToken': 'fixture-refresh', 'TokenType': 'Bearer', 'ExpiresIn': 300}}]
    class Response:
        status_code = 200
        def json(self):
            return responses.pop(0)
    def call(url, **kwargs):
        observed.append((url, kwargs))
        assert 'Authorization' not in kwargs['headers']
        return Response()
    monkeypatch.setattr('app.auth.provider.requests.post', call)
    challenge = provider.native_password(NATIVE_USERNAME, 'fixture-password')
    assert challenge['challenge'] == 'SOFTWARE_TOKEN_MFA'
    result = provider.native_totp(challenge['session'], NATIVE_USERNAME, '123456')
    assert result['refresh_token'] == 'fixture-refresh'
    assert [c[1]['headers']['X-Amz-Target'].split('.')[-1] for c in observed] == [
        'InitiateAuth', 'RespondToAuthChallenge']
    initial = observed[0][1]['json']
    assert initial['AuthFlow'] == 'USER_AUTH'
    assert initial['AuthParameters']['PREFERRED_CHALLENGE'] == 'PASSWORD'
    assert initial['AuthParameters']['PASSWORD'] == 'fixture-password'
    for _, request in observed:
        parameters = request['json'].get('AuthParameters') or request['json']['ChallengeResponses']
        assert parameters['USERNAME'] == NATIVE_USERNAME
        expected = base64.b64encode(__import__('hmac').new(provider.client_secret.encode(),
                     (NATIVE_USERNAME + provider.client_id).encode(), hashlib.sha256).digest()).decode()
        assert parameters['SECRET_HASH'] == expected
        assert 'DEVICE_KEY' not in parameters
    assert observed[1][1]['json']['ChallengeResponses']['SOFTWARE_TOKEN_MFA_CODE'] == '123456'


@pytest.mark.parametrize('body', [
    {'AuthenticationResult': {}}, native_response('SMS_MFA'), native_response('EMAIL_OTP'),
    native_response('SELECT_CHALLENGE'), native_response('CUSTOM_CHALLENGE'),
    native_response('SOFTWARE_TOKEN_MFA', USERNAME='other-subject'),
    native_response('SOFTWARE_TOKEN_MFA', USER_ID_FOR_SRP='other-subject'),
    {'ChallengeName': 'SOFTWARE_TOKEN_MFA', 'Session': 'short'},
    native_response('SOFTWARE_TOKEN_MFA', unexpected={}),
])
def test_native_unexpected_challenges_or_identity_switch_rejected(provider, body):
    with pytest.raises(AuthError):
        provider._native_challenge(body, NATIVE_USERNAME, {'SOFTWARE_TOKEN_MFA'})


@pytest.mark.parametrize('setup', ['["SMS_MFA"]', 'null', '{}', '["SOFTWARE_TOKEN_MFA", {}]'])
def test_native_setup_must_offer_software_token(provider, setup):
    with pytest.raises(AuthError):
        provider._native_challenge(native_response('MFA_SETUP', MFAS_CAN_SETUP=setup), NATIVE_USERNAME, {'MFA_SETUP'})


def test_native_new_password_and_enrollment_sessions_advance_and_setup_tokens_are_revoked(provider, monkeypatch):
    observed = []
    def call(operation, payload, **kwargs):
        observed.append((operation, payload))
        if operation == 'RespondToAuthChallenge' and payload['ChallengeName'] == 'NEW_PASSWORD_REQUIRED':
            return native_response('MFA_SETUP', MFAS_CAN_SETUP='["SOFTWARE_TOKEN_MFA"]')
        if operation == 'AssociateSoftwareToken':
            return {'SecretCode': 'JBSWY3DPEHPK3PXP', 'Session': NATIVE_SESSION + '-enrollment'}
        if operation == 'VerifySoftwareToken':
            return {'Status': 'SUCCESS', 'Session': NATIVE_SESSION + '-verified'}
        if operation == 'RespondToAuthChallenge':
            return {'AuthenticationResult': {'AccessToken': 'setup-access', 'IdToken': 'setup-id',
                    'RefreshToken': 'setup-refresh', 'TokenType': 'Bearer', 'ExpiresIn': 300}}
        assert operation == 'RevokeToken'
        return {}
    monkeypatch.setattr(provider, '_native_operation', call)
    challenge = provider.native_new_password(NATIVE_SESSION, NATIVE_USERNAME, 'fixture-new-password', {'email': 'fixture@example.invalid'})
    secret, session = provider.native_associate(challenge['session'])
    assert secret == 'JBSWY3DPEHPK3PXP'
    assert provider.native_enroll(session, NATIVE_USERNAME, '123456') is None
    assert observed[0][1]['ChallengeResponses']['userAttributes.email'] == 'fixture@example.invalid'
    assert observed[2][1] == {'Session': session, 'UserCode': '123456'}
    assert observed[3][1]['Session'] == NATIVE_SESSION + '-verified'
    assert observed[4][0] == 'RevokeToken' and observed[4][1]['Token'] == 'setup-refresh'


@pytest.mark.parametrize('body', [{'Status': 'ERROR', 'Session': NATIVE_SESSION}, {'Status': 'SUCCESS'},
                                  {'Status': 'SUCCESS', 'Session': 'short'}])
def test_native_failed_enrollment_never_finishes_setup(provider, monkeypatch, body):
    calls = []
    monkeypatch.setattr(provider, '_native_operation', lambda op, payload, **kw: calls.append(op) or body)
    with pytest.raises(AuthError):
        provider.native_enroll(NATIVE_SESSION, NATIVE_USERNAME, '123456')
    assert calls == ['VerifySoftwareToken']


def test_native_rotating_refresh_and_revoke_use_only_confidential_client(provider, monkeypatch):
    calls = []
    def invoke(op, payload, **kwargs):
        calls.append((op, payload, kwargs))
        if op == 'RevokeToken':
            return {}
        return {'AuthenticationResult': {'AccessToken': 'new-access', 'IdToken': 'new-id',
                'RefreshToken': 'new-refresh', 'TokenType': 'Bearer', 'ExpiresIn': 300}}
    monkeypatch.setattr(provider, '_native_operation', invoke)
    assert provider.native_refresh('old-refresh')['refresh_token'] == 'new-refresh'
    provider.native_revoke('new-refresh')
    assert calls[0] == ('GetTokensFromRefreshToken', {'ClientId': provider.client_id,
                          'ClientSecret': provider.client_secret, 'RefreshToken': 'old-refresh'}, {'refresh': True})
    assert calls[1][1]['Token'] == 'new-refresh'


def test_native_token_validation_does_not_fabricate_mfa_or_relax_oauth(provider, key):
    identity, access = claims()
    identity.pop('acr'); identity.pop('amr'); identity.pop('nonce')
    result = provider.validate_native(tokens(key, identity, access), NOW, started_at=NOW)
    assert result['subject'] == NATIVE_USERNAME
    assert 'assurance' not in result and 'acr' not in result and 'amr' not in result
    with pytest.raises(AuthError) as failure:
        provider.validate(tokens(key, identity, access), NOW, started_at=NOW)
    assert failure.value.reason == 'mfa_assurance_missing'


@pytest.mark.parametrize('field,value', [('iss', 'https://evil.example.invalid'), ('aud', 'other-client'),
    ('sub', 'other-subject'), ('email_verified', False), ('auth_time', NOW - 61), ('iat', NOW - 61),
    ('exp', NOW), ('identities', [{'providerName': 'Google'}])])
def test_native_signed_but_wrong_claims_rejected(provider, key, field, value):
    identity, access = claims(); identity[field] = value
    with pytest.raises(AuthError):
        provider.validate_native(tokens(key, identity, access), NOW, started_at=NOW)


def test_native_jwt_signature_and_access_audience_still_checked(provider, key):
    other = RSAKey.generate_key(parameters={'kid': 'fixture-key'})
    with pytest.raises(AuthError):
        provider.validate_native(tokens(other), NOW, started_at=NOW)
    identity, access = claims(); access['client_id'] = 'foreign-client'
    with pytest.raises(AuthError):
        provider.validate_native(tokens(key, identity, access), NOW, started_at=NOW)


@pytest.mark.parametrize('code,status', [('CodeMismatchException', 401), ('TooManyRequestsException', 429),
    ('InternalErrorException', 503), ('InvalidPasswordException', 422), ('PasswordResetRequiredException', 403)])
def test_native_errors_never_expose_private_provider_messages(provider, monkeypatch, code, status):
    class Response:
        status_code = 400
        def json(self):
            return {'__type': code, 'message': 'PRIVATE_PASSWORD_CODE_TOKEN_SECRET'}
    monkeypatch.setattr('app.auth.provider.requests.post', lambda *a, **kw: Response())
    with pytest.raises(AuthError) as failure:
        provider._native_operation('RespondToAuthChallenge', {'Session': NATIVE_SESSION})
    assert failure.value.status == status
    assert 'PRIVATE_' not in str(failure.value)


@pytest.mark.parametrize('returned', [{'AuthenticationResult': {}}, native_response('PASSWORD'),
                                     native_response('SMS_MFA'), native_response('EMAIL_OTP')])
def test_native_password_never_accepts_tokens_or_an_unexpected_second_factor(provider, monkeypatch, returned):
    monkeypatch.setattr(provider, '_native_operation', lambda *args, **kwargs: returned)
    with pytest.raises(AuthError):
        provider.native_password(NATIVE_USERNAME, 'fixture-password')
