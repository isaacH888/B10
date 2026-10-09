"""Maintained OAuth/JOSE clients with Cognito-specific assurance validation."""

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from urllib.parse import urlencode

import requests
from authlib.integrations.requests_client import OAuth2Session
from joserfc import jwt
from joserfc.jwk import KeySet

from .errors import AuthError, unavailable
from .settings import ISSUER_PATTERN


class CognitoProvider:
    def __init__(self, settings, area):
        prefix = f"COGNITO_{area.upper()}_"
        self.area = area
        self.issuer = settings[prefix + "ISSUER"]
        self.client_id = settings[prefix + "CLIENT_ID"]
        self.client_secret = settings[prefix + "CLIENT_SECRET"]
        self.domain = settings[prefix + "DOMAIN"]
        self.origin = settings["AUTH_ORIGIN"]
        self.callback = f"{self.origin}/api/v1/{area}/callback"
        self.region = ISSUER_PATTERN.fullmatch(self.issuer).group(1)
        self._keys = None
        self._keys_at = 0
        self._key_lock = threading.Lock()

    def oauth(self):
        return OAuth2Session(self.client_id, self.client_secret,
                             token_endpoint_auth_method="client_secret_basic",
                             scope="openid email profile aws.cognito.signin.user.admin",
                             redirect_uri=self.callback, code_challenge_method="S256",
                             default_timeout=(3, 8))

    def authorization_url(self, state, nonce, verifier, provider):
        if provider not in ({"password"} if self.area == "admin" else {"password", "google"}):
            raise AuthError("validation_error", "Choose a supported login method.", 422)
        parameters = {"state": state, "nonce": nonce, "code_verifier": verifier}
        if self.area == "admin" and provider == "password":
            parameters.update(identity_provider="COGNITO", prompt="login", max_age=0, acr_values="urn:cognito:loa:4")
        elif provider == "google":
            parameters["identity_provider"] = "Google"
        with self.oauth() as client:
            url, _ = client.create_authorization_url(self.domain + "/oauth2/authorize", **parameters)
            return url

    def exchange(self, code, verifier):
        try:
            with self.oauth() as client:
                return dict(client.fetch_token(self.domain + "/oauth2/token", code=code, code_verifier=verifier))
        except requests.RequestException:
            raise unavailable() from None
        except Exception as error:
            if getattr(error, "error", None) in {"server_error", "temporarily_unavailable"}:
                raise unavailable() from None
            raise AuthError("authentication_failed", "Sign-in could not be completed. Please start again.") from None

    def refresh(self, refresh_token):
        try:
            with self.oauth() as client:
                tokens = dict(client.fetch_token(self.domain + "/oauth2/token", grant_type="refresh_token",
                                                 refresh_token=refresh_token))
                tokens.setdefault("refresh_token", refresh_token)
                return tokens
        except requests.RequestException:
            raise unavailable() from None
        except Exception as error:
            if getattr(error, "error", None) in {"server_error", "temporarily_unavailable"}:
                raise unavailable() from None
            raise AuthError("session_expired", "Your session has expired. Please sign in again.") from None

    def _key_set(self, force=False):
        with self._key_lock:
            now = time.time()
            if self._keys is not None and now - self._keys_at < (15 if force else 300):
                return self._keys
            try:
                response = requests.get(self.issuer + "/.well-known/jwks.json", timeout=(3, 5))
                response.raise_for_status()
                payload = response.json()
                if len(payload.get("keys", [])) > 10:
                    raise ValueError("Unexpected key set")
                self._keys = KeySet.import_key_set(payload)
                self._keys_at = now
                return self._keys
            except Exception:
                raise unavailable() from None

    def _decode(self, encoded, token_use, now):
        if not isinstance(encoded, str) or len(encoded) > 20000:
            raise AuthError("authentication_failed", "Invalid authentication response.")
        keys = self._key_set()
        try:
            claims = jwt.decode(encoded, keys, algorithms=["RS256"]).claims
        except Exception:
            try:
                claims = jwt.decode(encoded, self._key_set(force=True), algorithms=["RS256"]).claims
            except AuthError:
                raise
            except Exception:
                raise AuthError("authentication_failed", "Invalid authentication response.") from None
        expected_client = claims.get("aud") if token_use == "id" else claims.get("client_id")
        if (claims.get("iss") != self.issuer or claims.get("token_use") != token_use
                or expected_client != self.client_id or not isinstance(claims.get("sub"), str)
                or not claims["sub"] or len(claims["sub"]) > 128
                or type(claims.get("exp")) is not int or claims["exp"] <= now
                or type(claims.get("iat")) is not int or claims["iat"] > now + 60
                or ("nbf" in claims and (type(claims["nbf"]) is not int or claims["nbf"] > now + 60))):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        return claims

    def validate(self, tokens, now, nonce=None, started_at=None, provider="password"):
        if provider not in ({"password"} if self.area == "admin" else {"password", "google"}):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        identity = self._decode(tokens.get("id_token"), "id", now)
        access = self._decode(tokens.get("access_token"), "access", now)
        scope = access.get("scope")
        if identity["sub"] != access["sub"] or not isinstance(scope, str) or "aws.cognito.signin.user.admin" not in scope.split():
            raise AuthError("authentication_failed", "Invalid authentication response.")
        if nonce is not None and not hmac.compare_digest(str(identity.get("nonce", "")).encode(), nonce.encode()):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        email = identity.get("email")
        if identity.get("email_verified") is not True or not isinstance(email, str) or not email or len(email) > 254:
            raise AuthError("email_verification_required", "Verify your email address before signing in.", 403)
        authenticated_at = identity.get("auth_time")
        if type(authenticated_at) is not int or authenticated_at > now + 60:
            raise AuthError("authentication_failed", "Invalid authentication response.")
        assurance = {"acr": identity.get("acr"), "amr": identity.get("amr", [])}
        if self.area == "admin":
            access_methods = access.get("amr")
            diagnostics = {"id_acr_present": identity.get("acr") is not None,
                           "id_amr_present": identity.get("amr") is not None,
                           "access_acr_present": access.get("acr") is not None,
                           "access_amr_present": access_methods is not None,
                           "access_totp_assured": (access.get("acr") == "urn:cognito:loa:4"
                               and isinstance(access_methods, list)
                               and all(isinstance(method, str) for method in access_methods)
                               and {"pwd", "otp", "mfa"}.issubset(set(access_methods)))}
            if (assurance["acr"] != "urn:cognito:loa:4" or not isinstance(assurance["amr"], list)
                    or not all(isinstance(method, str) for method in assurance["amr"])
                    or not {"pwd", "otp", "mfa"}.issubset(set(assurance["amr"]))):
                reason = ("mfa_assurance_missing" if identity.get("acr") is None or identity.get("amr") is None
                          else "mfa_assurance_insufficient")
                raise AuthError("mfa_required", "Complete authenticator setup, then sign in again.", 403,
                                reason=reason, diagnostics=diagnostics)
            if started_at is not None and authenticated_at < started_at - 60:
                raise AuthError("mfa_required", "Complete authenticator setup, then sign in again.", 403,
                                reason="mfa_authentication_stale", diagnostics=diagnostics)
        return {"issuer": self.issuer, "subject": identity["sub"], "email": email,
                "name": str(identity.get("name") or email)[:150], "auth_time": authenticated_at,
                "assurance": assurance, "token_expires_at": min(access["exp"], identity["exp"]),
                "provider": provider}

    def _user_operation(self, access_token, operation):
        try:
            response = requests.post(f"https://cognito-idp.{self.region}.amazonaws.com/",
                                     headers={"Content-Type": "application/x-amz-json-1.1",
                                              "X-Amz-Target": "AWSCognitoIdentityProviderService." + operation},
                                     json={"AccessToken": access_token}, timeout=(3, 5))
            body = response.json()
        except (requests.RequestException, ValueError):
            raise unavailable() from None
        if not isinstance(body, dict):
            raise unavailable()
        if response.status_code != 200:
            code = str(body.get("__type", "")).split("#")[-1]
            if code in {"NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException"}:
                raise AuthError("session_expired", "Your session has expired. Please sign in again.")
            raise unavailable()
        return body

    def current_user(self, access_token, subject, provider="password"):
        if provider not in ({"password"} if self.area == "admin" else {"password", "google"}):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        body = self._user_operation(access_token, "GetUser")
        values = body.get("UserAttributes", [])
        methods = body.get("UserMFASettingList", [])
        if (not isinstance(values, list) or not isinstance(methods, list)
                or not all(isinstance(attribute, dict) and isinstance(attribute.get("Name"), str)
                           and isinstance(attribute.get("Value"), str) for attribute in values)
                or not all(isinstance(method, str) for method in methods)):
            raise unavailable()
        attributes = {attribute["Name"]: attribute["Value"] for attribute in values}
        if attributes.get("sub") != subject:
            raise AuthError("authentication_failed", "Invalid authentication response.")
        if self.area == "admin" and "SOFTWARE_TOKEN_MFA" not in methods:
            # A required-MFA pool can challenge a registered TOTP without a
            # user preference. Signed ACR/AMR still prove the completed login;
            # this access-token query checks that its factor remains configured.
            username = body.get("Username")
            if not isinstance(username, str) or not username or len(username) > 128:
                raise unavailable()
            factors = self._user_operation(access_token, "GetUserAuthFactors")
            configured = factors.get("ConfiguredUserAuthFactors")
            if not isinstance(configured, list) or not all(isinstance(factor, str) for factor in configured):
                raise unavailable()
            if factors.get("Username") != username:
                raise AuthError("authentication_failed", "Invalid authentication response.")
            if "SOFTWARE_TOKEN" not in configured:
                raise AuthError("mfa_required", "Complete authenticator setup, then sign in again.", 403,
                                reason="mfa_enrollment_missing")

    def _native_operation(self, operation, payload, *, refresh=False):
        """Public Cognito operations use app-client proof, never operator IAM credentials."""
        if self.area != "admin":
            raise AuthError("authentication_failed", "Invalid authentication response.")
        try:
            response = requests.post(f"https://cognito-idp.{self.region}.amazonaws.com/",
                                     headers={"Content-Type": "application/x-amz-json-1.1",
                                              "X-Amz-Target": "AWSCognitoIdentityProviderService." + operation},
                                     json=payload, timeout=(3, 8))
            body = response.json()
        except (requests.RequestException, ValueError):
            raise unavailable() from None
        if not isinstance(body, dict):
            raise unavailable()
        if response.status_code != 200:
            code = str(body.get("__type", "")).split("#")[-1]
            if code in {"TooManyRequestsException", "LimitExceededException"}:
                raise AuthError("rate_limited", "Too many sign-in attempts. Please wait a minute and try again.", 429)
            if code == "UserNotConfirmedException":
                raise AuthError("email_verification_required", "Verify your email address before signing in.", 403)
            if code == "PasswordResetRequiredException":
                raise AuthError("password_reset_required", "Contact the administrator operator to recover your account.", 403)
            if code in {"InvalidPasswordException", "PasswordHistoryPolicyViolationException"}:
                raise AuthError("validation_error", "Choose a password that meets the administrator password policy.", 422)
            if code in {"NotAuthorizedException", "UserNotFoundException", "CodeMismatchException",
                        "ExpiredCodeException", "EnableSoftwareTokenMFAException"}:
                if refresh:
                    raise AuthError("session_expired", "Your session has expired. Please sign in again.")
                raise AuthError("authentication_failed", "Sign-in could not be completed. Please start again.")
            raise unavailable()
        return body

    def _secret_hash(self, username):
        return base64.b64encode(hmac.new(self.client_secret.encode(),
                                        (username + self.client_id).encode(), hashlib.sha256).digest()).decode("ascii")

    @staticmethod
    def _native_failure():
        return AuthError("authentication_failed", "Sign-in could not be completed. Please start again.")

    def _native_challenge(self, body, username, allowed):
        # Only the expected native challenge sequence may advance. In particular,
        # a direct token result cannot stand in for an observed TOTP response.
        name, session = body.get("ChallengeName"), body.get("Session")
        parameters = body.get("ChallengeParameters", {})
        if ("AuthenticationResult" in body or name not in allowed
                or not isinstance(session, str) or not 20 <= len(session) <= 4096
                or not isinstance(parameters, dict)
                or not all(isinstance(key, str) and isinstance(value, str) for key, value in parameters.items())):
            raise self._native_failure()
        for field in ("USERNAME", "USER_ID_FOR_SRP"):
            if field in parameters and parameters[field] != username:
                raise self._native_failure()
        result = {"challenge": name, "session": session, "username": username}
        try:
            if name == "NEW_PASSWORD_REQUIRED":
                required = json.loads(parameters.get("requiredAttributes", "[]"))
                if (not isinstance(required, list) or len(required) > 2
                        or not all(attribute in {"userAttributes.email", "userAttributes.name", "email", "name"}
                                   for attribute in required)):
                    raise ValueError()
                result["required_attributes"] = [attribute.removeprefix("userAttributes.") for attribute in required]
            if name == "MFA_SETUP":
                methods = json.loads(parameters.get("MFAS_CAN_SETUP", "null"))
                if (not isinstance(methods, list) or not all(isinstance(method, str) for method in methods)
                        or "SOFTWARE_TOKEN_MFA" not in methods):
                    raise ValueError()
        except (TypeError, ValueError):
            raise self._native_failure() from None
        return result

    def _native_respond(self, challenge, session, username, answers):
        responses = {"USERNAME": username, "SECRET_HASH": self._secret_hash(username), **answers}
        return self._native_operation("RespondToAuthChallenge", {
            "ClientId": self.client_id, "ChallengeName": challenge,
            "Session": session, "ChallengeResponses": responses})

    def native_password(self, username, password):
        response = self._native_operation("InitiateAuth", {
            "ClientId": self.client_id, "AuthFlow": "USER_AUTH",
            "AuthParameters": {"USERNAME": username, "PREFERRED_CHALLENGE": "PASSWORD",
                               "PASSWORD": password, "SECRET_HASH": self._secret_hash(username)}})
        return self._native_challenge(response, username, {"NEW_PASSWORD_REQUIRED", "MFA_SETUP", "SOFTWARE_TOKEN_MFA"})

    def native_new_password(self, session, username, password, attributes):
        answers = {"NEW_PASSWORD": password}
        answers.update({"userAttributes." + key: value for key, value in attributes.items()})
        response = self._native_respond("NEW_PASSWORD_REQUIRED", session, username, answers)
        return self._native_challenge(response, username, {"MFA_SETUP", "SOFTWARE_TOKEN_MFA"})

    def native_associate(self, session):
        body = self._native_operation("AssociateSoftwareToken", {"Session": session})
        secret, next_session = body.get("SecretCode"), body.get("Session")
        if (not isinstance(secret, str) or not re.fullmatch(r"[A-Z2-7]{16,256}", secret)
                or not isinstance(next_session, str) or not 20 <= len(next_session) <= 4096):
            raise self._native_failure()
        return secret, next_session

    @staticmethod
    def _native_tokens(body, *, require_refresh=True):
        result = body.get("AuthenticationResult")
        if ("ChallengeName" in body or not isinstance(result, dict) or result.get("TokenType") != "Bearer"
                or type(result.get("ExpiresIn")) is not int or not 1 <= result["ExpiresIn"] <= 86400):
            raise CognitoProvider._native_failure()
        tokens = {}
        for source, target in (("AccessToken", "access_token"), ("IdToken", "id_token"), ("RefreshToken", "refresh_token")):
            value = result.get(source)
            if source == "RefreshToken" and not require_refresh and value is None:
                continue
            if not isinstance(value, str) or not value or len(value) > 20000:
                raise CognitoProvider._native_failure()
            tokens[target] = value
        return tokens

    def native_enroll(self, session, username, code):
        body = self._native_operation("VerifySoftwareToken", {"Session": session, "UserCode": code})
        verified_session = body.get("Session")
        if (body.get("Status") != "SUCCESS" or not isinstance(verified_session, str)
                or not 20 <= len(verified_session) <= 4096):
            raise self._native_failure()
        result = self._native_respond("MFA_SETUP", verified_session, username, {})
        if "AuthenticationResult" in result:
            # Setup-issued tokens are never usable by this application. Revoke
            # them and demand a new password + SOFTWARE_TOKEN_MFA transaction.
            self.native_revoke(self._native_tokens(result)["refresh_token"])
        else:
            self._native_challenge(result, username, {"SOFTWARE_TOKEN_MFA"})

    def native_totp(self, session, username, code):
        return self._native_tokens(self._native_respond("SOFTWARE_TOKEN_MFA", session, username,
                                                       {"SOFTWARE_TOKEN_MFA_CODE": code}))

    def native_refresh(self, refresh_token):
        body = self._native_operation("GetTokensFromRefreshToken", {
            "ClientId": self.client_id, "ClientSecret": self.client_secret,
            "RefreshToken": refresh_token}, refresh=True)
        tokens = self._native_tokens(body, require_refresh=False)
        tokens.setdefault("refresh_token", refresh_token)
        return tokens

    def native_revoke(self, refresh_token):
        self._native_operation("RevokeToken", {"ClientId": self.client_id,
                                              "ClientSecret": self.client_secret, "Token": refresh_token}, refresh=True)

    def validate_native(self, tokens, now, *, started_at=None):
        """Verify JWT identity only; the bound BFF challenge supplies native MFA proof.

        Calling this method never establishes assurance. The service may create
        native proof only after its consumed SOFTWARE_TOKEN_MFA response succeeds.
        """
        if self.area != "admin":
            raise self._native_failure()
        identity = self._decode(tokens.get("id_token"), "id", now)
        access = self._decode(tokens.get("access_token"), "access", now)
        if identity.get("identities") not in (None, []):
            raise self._native_failure()
        scope = access.get("scope")
        if (identity["sub"] != access["sub"] or not isinstance(scope, str)
                or "aws.cognito.signin.user.admin" not in scope.split()):
            raise self._native_failure()
        email = identity.get("email")
        if identity.get("email_verified") is not True or not isinstance(email, str) or not email or len(email) > 254:
            raise AuthError("email_verification_required", "Verify your email address before signing in.", 403)
        authenticated_at = identity.get("auth_time")
        if (type(authenticated_at) is not int or authenticated_at < 0 or authenticated_at > now + 60
                or (started_at is not None and (authenticated_at < started_at - 60
                    or identity["iat"] < started_at - 60 or access["iat"] < started_at - 60))):
            raise self._native_failure()
        return {"issuer": self.issuer, "subject": identity["sub"], "email": email,
                "name": str(identity.get("name") or email)[:150], "auth_time": authenticated_at,
                "token_expires_at": min(access["exp"], identity["exp"]), "provider": "password"}

    def revoke(self, refresh_token):
        try:
            with self.oauth() as client:
                response = client.revoke_token(self.domain + "/oauth2/revoke", token=refresh_token,
                                               token_type_hint="refresh_token")
                response.raise_for_status()
        except Exception:
            raise unavailable() from None

    def logout_url(self):
        landing = self.origin + ("/admin/login" if self.area == "admin" else "/login")
        return self.domain + "/logout?" + urlencode({"client_id": self.client_id, "logout_uri": landing})
