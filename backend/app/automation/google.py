"""Bounded Google HTTP calls and server-only credential storage.

Only static, actionable messages cross this boundary. Provider responses can
contain credentials or customer data and must never become logs or API errors.
"""

import copy
import json
from urllib.parse import quote

import requests
from botocore import exceptions as aws_errors


class GoogleFailure(Exception):
    def __init__(self, category, message, *, status=None):
        super().__init__(message)
        self.category, self.message, self.status = category, message, status


class MemorySecrets:
    """Explicit test/local adapter; never selected automatically in hosted use."""

    def __init__(self, values=None):
        self.values = copy.deepcopy(values or {})

    def get(self, name):
        return copy.deepcopy(self.values.get(name))

    def put(self, name, value):
        self.values[name] = copy.deepcopy(value)
        return name

    def delete(self, name):
        self.values.pop(name, None)


class _MissingSecret(Exception):
    pass


class AwsSecrets:
    _CREDENTIALS_MESSAGE = (
        "AWS credentials are unavailable or expired. Sign in with the configured AWS profile, "
        "then retry connecting Google Calendar."
    )
    _TRANSIENT_MESSAGE = (
        "AWS Secrets Manager is temporarily unavailable. Retry connecting Google Calendar."
    )

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "secretsmanager",
                config=Config(
                    connect_timeout=5,
                    read_timeout=20,
                    retries={"mode": "standard", "total_max_attempts": 3},
                ),
            )
        return self._client

    def _call(self, operation, **kwargs):
        try:
            return getattr(self.client, operation)(**kwargs)
        except aws_errors.ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code == "ResourceNotFoundException":
                raise _MissingSecret from None
            if code in {
                "ExpiredToken",
                "ExpiredTokenException",
                "InvalidClientTokenId",
                "UnrecognizedClientException",
                "InvalidSignatureException",
                "SignatureDoesNotMatch",
                "RequestExpired",
            }:
                raise GoogleFailure("invalid", self._CREDENTIALS_MESSAGE) from None
            if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
                raise GoogleFailure(
                    "invalid",
                    (
                        "AWS access to Google Calendar credentials was denied. Allow the configured AWS "
                        "profile to read the OAuth client secret and create or update token secrets, then retry."
                    ),
                ) from None
            if (
                code
                in {
                    "Throttling",
                    "ThrottlingException",
                    "TooManyRequestsException",
                    "RequestLimitExceeded",
                    "ServiceUnavailable",
                    "ServiceUnavailableException",
                    "InternalFailure",
                    "InternalServiceError",
                    "InternalServiceErrorException",
                }
                or status == 429
                or (isinstance(status, int) and status >= 500)
            ):
                raise GoogleFailure("transient", self._TRANSIENT_MESSAGE) from None
            raise GoogleFailure(
                "invalid",
                (
                    "Check the Google Calendar secret configuration and AWS Secrets Manager permissions, then retry."
                ),
            ) from None
        except (aws_errors.ConnectionError, aws_errors.HTTPClientError):
            raise GoogleFailure("transient", self._TRANSIENT_MESSAGE) from None
        except (
            aws_errors.NoCredentialsError,
            aws_errors.PartialCredentialsError,
            aws_errors.CredentialRetrievalError,
            aws_errors.TokenRetrievalError,
            aws_errors.LoginError,
            aws_errors.SSOError,
            aws_errors.ProfileNotFound,
            aws_errors.MissingDependencyException,
        ):
            raise GoogleFailure("invalid", self._CREDENTIALS_MESSAGE) from None
        except aws_errors.BotoCoreError:
            raise GoogleFailure(
                "invalid",
                ("Check the AWS region, profile, and Secrets Manager configuration, then retry."),
            ) from None

    def get(self, name):
        try:
            result = self._call("get_secret_value", SecretId=name)
        except _MissingSecret:
            return None
        try:
            value = json.loads(result["SecretString"])
            if not isinstance(value, dict):
                raise ValueError
        except (KeyError, ValueError, TypeError, UnicodeError):
            raise GoogleFailure(
                "invalid",
                (
                    "Google Calendar credentials in Secrets Manager must be a JSON object. "
                    "Check the configured secret, then retry."
                ),
            ) from None
        return value

    def put(self, name, value):
        payload = json.dumps(value, separators=(",", ":"))
        try:
            return self._call("put_secret_value", SecretId=name, SecretString=payload)["ARN"]
        except _MissingSecret:
            return self._call("create_secret", Name=name, SecretString=payload)["ARN"]

    def delete(self, name):
        # Empty immediately; retain the resource so reconnect can safely reuse
        # its deterministic name without a deletion recovery window.
        self.put(name, {})


class GoogleHTTPAdapter:
    BASE = "https://www.googleapis.com/calendar/v3"

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _request(self, method, url, *, token=None, form=None, body=None, params=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                data=form,
                json=body,
                params=params,
                timeout=(5, 20),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise GoogleFailure(
                "transient", "Google Calendar is temporarily unavailable. Retry synchronization."
            ) from None
        try:
            value = response.json() if response.content else {}
        except (ValueError, TypeError):
            value = {}
        status = response.status_code
        if 200 <= status < 300:
            return value
        error = value.get("error", {}) if isinstance(value, dict) else {}
        oauth_error = error if isinstance(error, str) else ""
        provider_errors = error.get("errors", []) if isinstance(error, dict) else []
        reasons = (
            [item.get("reason") for item in provider_errors if isinstance(item, dict)]
            if isinstance(provider_errors, list)
            else []
        )
        details = error.get("details", []) if isinstance(error, dict) else []
        service_disabled = "accessNotConfigured" in reasons or any(
            isinstance(item, dict)
            and item.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo"
            and item.get("reason") == "SERVICE_DISABLED"
            for item in (details if isinstance(details, list) else [])
        )
        if service_disabled:
            raise GoogleFailure(
                "invalid",
                (
                    "The Google Calendar API is disabled for this OAuth project. Enable Google Calendar API "
                    "in Google Cloud Console, wait a few minutes, then connect again."
                ),
                status=status,
            )
        if oauth_error in {"invalid_grant", "invalid_token"} or status == 401:
            raise GoogleFailure(
                "reconnect_required", "Reconnect Google Calendar to restore access.", status=status
            )
        if (
            status == 429
            or status >= 500
            or any(
                reason in {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}
                for reason in reasons
            )
        ):
            raise GoogleFailure(
                "transient",
                "Google Calendar is temporarily unavailable. Retry synchronization.",
                status=status,
            )
        if status == 404 or status == 410:
            raise GoogleFailure(
                "missing",
                "The calendar or event is no longer available. Use the repair action.",
                status=status,
            )
        if status == 409:
            raise GoogleFailure(
                "conflict",
                "The event identifier already exists. Ownership must be checked.",
                status=status,
            )
        if status == 403:
            raise GoogleFailure(
                "reconnect_required",
                "Calendar access was denied. Check the selected calendar and reconnect Google.",
                status=status,
            )
        if status == 400 or status == 422:
            raise GoogleFailure(
                "invalid",
                "Check the booking start, end, IANA time zone, and selected calendar, then retry.",
                status=status,
            )
        raise GoogleFailure(
            "invalid",
            "Google rejected the operation. Check the integration configuration and retry.",
            status=status,
        )

    def exchange(self, code, credentials, redirect_uri):
        return self._request(
            "POST",
            "https://oauth2.googleapis.com/token",
            form={
                "code": code,
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    def refresh(self, refresh_token, credentials):
        return self._request(
            "POST",
            "https://oauth2.googleapis.com/token",
            form={
                "refresh_token": refresh_token,
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "grant_type": "refresh_token",
            },
        )

    def revoke(self, token):
        return self._request("POST", "https://oauth2.googleapis.com/revoke", form={"token": token})

    def create_calendar(self, token):
        return self._request(
            "POST",
            self.BASE + "/calendars",
            token=token,
            body={"summary": "Popssibilities Catering", "timeZone": "America/Chicago"},
        )

    def check_calendar(self, token, calendar_id):
        return self._request(
            "GET", self._calendar(calendar_id) + "/events", token=token, params={"maxResults": 1}
        )

    def _calendar(self, calendar_id):
        return self.BASE + "/calendars/" + quote(calendar_id, safe="")

    def get_event(self, token, calendar_id, event_id):
        return self._request(
            "GET", self._calendar(calendar_id) + "/events/" + quote(event_id, safe=""), token=token
        )

    def insert_event(self, token, calendar_id, event):
        return self._request(
            "POST",
            self._calendar(calendar_id) + "/events",
            token=token,
            body=event,
            params={"sendUpdates": "none"},
        )

    def update_event(self, token, calendar_id, event_id, event):
        return self._request(
            "PUT",
            self._calendar(calendar_id) + "/events/" + quote(event_id, safe=""),
            token=token,
            body=event,
            params={"sendUpdates": "none"},
        )

    def delete_event(self, token, calendar_id, event_id):
        return self._request(
            "DELETE",
            self._calendar(calendar_id) + "/events/" + quote(event_id, safe=""),
            token=token,
            params={"sendUpdates": "none"},
        )


class MemoryGoogle:
    """Deterministic fake for explicit local mode and mocked external tests."""

    def __init__(self):
        self.calendars = {}
        self.events = {}
        self.calls = []
        self.refresh_error = None

    def exchange(self, code, credentials, redirect_uri):
        self.calls.append(("exchange", redirect_uri))
        return {"access_token": "mock-access", "refresh_token": "mock-refresh", "expires_in": 3600}

    def refresh(self, refresh_token, credentials):
        self.calls.append(("refresh",))
        if self.refresh_error:
            raise self.refresh_error
        return {"access_token": "mock-access", "expires_in": 3600}

    def revoke(self, token):
        self.calls.append(("revoke",))
        return {}

    def create_calendar(self, token):
        identifier = "mock-calendar-" + str(len(self.calendars) + 1)
        self.calendars[identifier] = {"id": identifier, "summary": "Popssibilities Catering"}
        self.calls.append(("create_calendar", identifier))
        return copy.deepcopy(self.calendars[identifier])

    def check_calendar(self, token, calendar_id):
        if calendar_id not in self.calendars:
            raise GoogleFailure(
                "missing",
                "The selected calendar no longer exists. Repair the Google connection.",
                status=404,
            )
        return {}

    def get_event(self, token, calendar_id, event_id):
        self.calls.append(("get", calendar_id, event_id))
        if (calendar_id, event_id) not in self.events:
            raise GoogleFailure(
                "missing", "The event no longer exists. Use the repair action.", status=404
            )
        return copy.deepcopy(self.events[calendar_id, event_id])

    def insert_event(self, token, calendar_id, event):
        key = calendar_id, event["id"]
        self.calls.append(("insert", *key))
        if key in self.events:
            raise GoogleFailure("conflict", "The event already exists.", status=409)
        self.events[key] = copy.deepcopy(event)
        return copy.deepcopy(event)

    def update_event(self, token, calendar_id, event_id, event):
        self.calls.append(("update", calendar_id, event_id))
        self.events[calendar_id, event_id] = copy.deepcopy(event)
        return copy.deepcopy(event)

    def delete_event(self, token, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id))
        if (calendar_id, event_id) in self.events:
            self.events[calendar_id, event_id]["status"] = "cancelled"
        return {}
