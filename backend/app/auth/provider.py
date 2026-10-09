"""Maintained OAuth/JOSE clients with Cognito-specific assurance validation."""

import hmac
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
        parameters = {"state": state, "nonce": nonce, "code_verifier": verifier}
        if self.area == "admin" and provider == "password":
            parameters.update(identity_provider="COGNITO", prompt="login", max_age=0, acr_values="urn:cognito:loa:4")
        elif provider == "google":
            parameters["identity_provider"] = "Google"
            if self.area == "admin":
                parameters["prompt"] = "select_account"
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

    @staticmethod
    def google_identity(identity):
        # An identities attribute alone is not proof of a Google sign-in:
        # Cognito also places it on native accounts linked at the provider.
        identities = identity.get("identities")
        if not isinstance(identities, list) or len(identities) != 1 or not isinstance(identities[0], dict):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        entry = identities[0]
        subject = entry.get("userId")
        if (entry.get("providerName") != "Google" or entry.get("providerType") != "Google"
                or not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject)
                or identity.get("cognito:username") not in {"Google_" + subject, "google_" + subject.lower()}):
            raise AuthError("authentication_failed", "Invalid authentication response.")
        return subject

    def validate(self, tokens, now, nonce=None, started_at=None, provider="password"):
        if provider not in {"password", "google"}:
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
        google_subject = None
        if self.area == "admin" and provider == "google":
            google_subject = self.google_identity(identity)
        elif self.area == "admin":
            if (assurance["acr"] != "urn:cognito:loa:4" or not isinstance(assurance["amr"], list)
                    or not all(isinstance(method, str) for method in assurance["amr"])
                    or not {"pwd", "otp", "mfa"}.issubset(set(assurance["amr"]))
                    or (started_at is not None and authenticated_at < started_at - 60)):
                raise AuthError("mfa_required", "Complete authenticator setup, then sign in again.", 403)
        return {"issuer": self.issuer, "subject": identity["sub"], "email": email,
                "name": str(identity.get("name") or email)[:150], "auth_time": authenticated_at,
                "assurance": assurance, "token_expires_at": min(access["exp"], identity["exp"]),
                "provider": provider, "google_subject": google_subject,
                "provider_username": identity.get("cognito:username")}

    def current_user(self, access_token, subject, provider="password", google_subject=None):
        try:
            response = requests.post(f"https://cognito-idp.{self.region}.amazonaws.com/",
                                     headers={"Content-Type": "application/x-amz-json-1.1",
                                              "X-Amz-Target": "AWSCognitoIdentityProviderService.GetUser"},
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
        if self.area == "admin" and provider == "google":
            if not google_subject or body.get("Username") not in {"Google_" + google_subject, "google_" + google_subject.lower()}:
                raise AuthError("authentication_failed", "Invalid authentication response.")
        elif self.area == "admin" and "SOFTWARE_TOKEN_MFA" not in methods:
            raise AuthError("mfa_required", "Complete authenticator setup, then sign in again.", 403)

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
