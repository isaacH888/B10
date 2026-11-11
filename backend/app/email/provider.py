"""Small SES adapter with bounded requests and no implicit retry of a send."""

import os
import threading

import boto3
from botocore.config import Config
from botocore.configprovider import ConstantProvider
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
)
from botocore.session import Session

from .settings import valid_address, validate_settings
from .templates import render_confirmation


class MailFailure(Exception):
    """Only safe classifications cross the provider boundary; SES errors can contain PII."""

    def __init__(self, kind, safe_code):
        self.kind = kind
        self.safe_code = safe_code
        super().__init__(
            {
                "rejected": "The email provider could not accept this test email.",
                "unavailable": "Test email is temporarily unavailable.",
                "uncertain": "The email delivery result is uncertain. Avoid sending again immediately.",
            }[kind]
        )


def _session(settings):
    # Do not inherit the developer's private operator profile or generic AWS access keys.
    core = Session()
    core.get_component("config_store").set_config_provider("profile", ConstantProvider(None))
    core.set_config_variable("config_file", os.devnull)
    core.set_config_variable("credentials_file", os.devnull)
    resolver = core.get_component("credential_provider")
    allowed = {"container-role", "iam-role", "assume-role-with-web-identity"}
    resolver.providers = [provider for provider in resolver.providers if provider.METHOD in allowed]
    credentials = {}
    if settings.get("EMAIL_AWS_ACCESS_KEY_ID"):
        credentials = {
            "aws_access_key_id": settings["EMAIL_AWS_ACCESS_KEY_ID"],
            "aws_secret_access_key": settings["EMAIL_AWS_SECRET_ACCESS_KEY"],
            "aws_session_token": settings.get("EMAIL_AWS_SESSION_TOKEN") or None,
        }
    return boto3.Session(
        botocore_session=core, region_name=settings["EMAIL_AWS_REGION"], **credentials
    )


class SESMailer:
    def __init__(self, settings, *, client=None):
        self.settings = settings
        self._client = client
        self._client_lock = threading.Lock()

    def _ses(self):
        with self._client_lock:
            if self._client is None:
                self._client = _session(self.settings).client(
                    "sesv2",
                    config=Config(
                        connect_timeout=3,
                        read_timeout=5,
                        ignore_configured_endpoint_urls=True,
                        retries={"mode": "standard", "total_max_attempts": 1},
                    ),
                )
            return self._client

    def send(self, recipient, name, reference):
        if not self.settings.get("EMAIL_ENABLED", False):
            raise MailFailure("unavailable", "email_disabled")
        try:
            validate_settings(self.settings)
        except ValueError:
            raise MailFailure("unavailable", "email_misconfigured") from None
        if not valid_address(recipient):
            raise MailFailure("rejected", "invalid_recipient")
        message = render_confirmation(name, reference)
        request = {
            "FromEmailAddress": self.settings["EMAIL_FROM_ADDRESS"],
            "Destination": {"ToAddresses": [recipient]},
            "ReplyToAddresses": [self.settings["EMAIL_REPLY_TO_ADDRESS"]],
            "Content": {
                "Simple": {
                    "Subject": {"Charset": "UTF-8", "Data": message["subject"]},
                    "Body": {
                        "Text": {"Charset": "UTF-8", "Data": message["text"]},
                        "Html": {"Charset": "UTF-8", "Data": message["html"]},
                    },
                }
            },
            "EmailTags": [{"Name": "kind", "Value": "customer-test-confirmation"}],
        }
        if self.settings.get("EMAIL_SES_CONFIGURATION_SET"):
            request["ConfigurationSetName"] = self.settings["EMAIL_SES_CONFIGURATION_SET"]
        try:
            client = self._ses()
        except Exception:
            raise MailFailure("unavailable", "ses_credentials_unavailable") from None
        try:
            response = client.send_email(**request)
        except (NoCredentialsError, PartialCredentialsError):
            raise MailFailure("unavailable", "ses_credentials_unavailable") from None
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            code = error.response.get("Error", {}).get("Code", "")
            if code in {
                "TooManyRequestsException",
                "Throttling",
                "ThrottlingException",
                "LimitExceededException",
            }:
                raise MailFailure("unavailable", "ses_throttled") from None
            if 400 <= status < 500:
                raise MailFailure("rejected", "ses_rejected") from None
            raise MailFailure("uncertain", "ses_delivery_uncertain") from None
        except BotoCoreError:
            # A network failure may happen after SES accepted the request. Do not retry silently.
            raise MailFailure("uncertain", "ses_delivery_uncertain") from None
        except Exception:
            raise MailFailure("uncertain", "ses_delivery_uncertain") from None
        message_id = response.get("MessageId") if isinstance(response, dict) else None
        if not isinstance(message_id, str) or not message_id or len(message_id) > 256:
            raise MailFailure("uncertain", "ses_response_invalid")
        return message_id
