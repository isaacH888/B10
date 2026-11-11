"""Persist one send attempt before contacting SES; an ambiguous send is never retried."""

from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

import pymysql

from .. import database


class MailStoreUnavailable(RuntimeError):
    """No mail may be sent without durable duplicate protection."""


class MailRateLimited(RuntimeError):
    """A shared sending budget is exhausted."""


class MailConflict(RuntimeError):
    """An idempotency key cannot be reused for a different identity or mailbox."""


def _hash(value):
    return sha256(value.encode()).hexdigest()


class MailStore:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def _transaction(self):
        connection = None
        try:
            connection = database.connect(self.settings)
            yield connection
            connection.commit()
        except (pymysql.MySQLError, OSError):
            if connection is not None:
                try:
                    connection.rollback()
                except (pymysql.MySQLError, OSError):
                    pass
            raise MailStoreUnavailable("Test email storage is unavailable") from None
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def reserve(self, identity_id, request_hash, recipient_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            # A single short SQL lock serializes the shared budgets across web
            # workers. Release it before any provider call, including credentials.
            gate = _hash("email:dispatch")
            cursor.execute(
                """INSERT INTO email_test_budgets
                (bucket_hash,window_start,attempts,expires_at) VALUES (%s,0,0,0)
                ON DUPLICATE KEY UPDATE attempts=attempts""",
                (gate,),
            )
            cursor.execute(
                "SELECT bucket_hash FROM email_test_budgets WHERE bucket_hash=%s FOR UPDATE",
                (gate,),
            )
            cursor.fetchone()
            cursor.execute(
                "SELECT * FROM email_test_messages WHERE request_hash=%s FOR UPDATE",
                (request_hash,),
            )
            existing = cursor.fetchone()
            if existing:
                if (
                    existing["identity_id"] != identity_id
                    or existing["recipient_hash"] != recipient_hash
                ):
                    raise MailConflict("The email request has changed")
                if existing["status"] == "sending" and now >= existing["created_at"] + 30:
                    cursor.execute(
                        """UPDATE email_test_messages SET status='uncertain',
                        error_code='email_delivery_uncertain',updated_at=%s WHERE request_hash=%s""",
                        (now, request_hash),
                    )
                    existing.update(
                        status="uncertain", error_code="email_delivery_uncertain", updated_at=now
                    )
                return existing, False

            budgets = (
                ("global:second", 1, 1),
                ("global:day", 60, 86400),
                ("identity:" + identity_id, 3, 3600),
                ("recipient:" + recipient_hash, 3, 3600),
            )
            for key, limit, seconds in budgets:
                bucket = _hash("email:" + key)
                start = now // seconds * seconds
                cursor.execute(
                    """INSERT IGNORE INTO email_test_budgets
                    (bucket_hash,window_start,attempts,expires_at) VALUES (%s,%s,0,%s)""",
                    (bucket, start, start + seconds),
                )
                cursor.execute(
                    "SELECT window_start,attempts FROM email_test_budgets WHERE bucket_hash=%s FOR UPDATE",
                    (bucket,),
                )
                row = cursor.fetchone()
                count = int(row["attempts"]) if row["window_start"] == start else 0
                if count >= limit:
                    raise MailRateLimited("Too many test emails")
                cursor.execute(
                    """UPDATE email_test_budgets SET window_start=%s,attempts=%s,expires_at=%s
                    WHERE bucket_hash=%s""",
                    (start, count + 1, start + seconds, bucket),
                )
            reference = "TEST-" + uuid4().hex[:20].upper()
            cursor.execute(
                """INSERT INTO email_test_messages
                (request_hash,identity_id,recipient_hash,reference,status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,'sending',%s,%s)""",
                (request_hash, identity_id, recipient_hash, reference, now, now),
            )
            return {
                "request_hash": request_hash,
                "identity_id": identity_id,
                "recipient_hash": recipient_hash,
                "reference": reference,
                "status": "sending",
                "created_at": now,
                "updated_at": now,
                "provider_message_id": None,
                "error_code": None,
            }, True

    def finish(self, request_hash, status, now, *, message_id=None, error_code=None):
        if status not in {"accepted", "failed", "uncertain"}:
            raise ValueError("Invalid email outcome")
        with self._transaction() as connection, connection.cursor() as cursor:
            # A delayed SES success is positive evidence even if a concurrent
            # retry already classified the abandoned reservation as uncertain.
            states = "('sending','uncertain')" if status == "accepted" else "('sending')"
            cursor.execute(
                """UPDATE email_test_messages SET status=%s,provider_message_id=%s,
                error_code=%s,updated_at=%s WHERE request_hash=%s AND status IN """
                + states,
                (status, message_id, error_code, now, request_hash),
            )
