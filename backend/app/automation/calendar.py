"""Authoritative one-way Calendar projection, serialized across Google calls."""

import hashlib
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .google import GoogleFailure
from .oauth import stamp


def event_id(booking):
    # A SHA-256 hex string is a subset of Google's base32hex alphabet (0-9,a-v).
    value = "popssibilities:" + str(booking["owner_id"]) + ":" + booking["id"] + ":" + str(booking.get("event_generation", 0))
    return hashlib.sha256(value.encode()).hexdigest()


def ownership(booking):
    return {"application": "popssibilities", "booking_id": booking["id"], "owner_id": str(booking["owner_id"])}


def owns(event, booking):
    props = event.get("extendedProperties", {}).get("private", {})
    return all(props.get(key) == value for key, value in ownership(booking).items())


class CalendarWorker:
    def __init__(self, settings, store, oauth, google=None, clock=None):
        self.settings, self.store, self.oauth = settings, store, oauth
        self.google = google or oauth.google
        self.clock = clock or time.time

    def _body(self, booking):
        try:
            zone = ZoneInfo(booking["timezone"])
            start = datetime.fromisoformat(booking["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(booking["end"].replace("Z", "+00:00"))
            if start.tzinfo is None or end.tzinfo is None or end <= start:
                raise ValueError()
            if not booking["venue"] or not booking["service_type"]:
                raise ValueError()
        except (ValueError, KeyError, ZoneInfoNotFoundError):
            raise GoogleFailure("invalid", "Correct the booking start, end, venue, service type, and IANA time zone, then retry.") from None
        link = self.settings.get("AUTOMATION_DASHBOARD_URL", "http://localhost:5173/admin/automation").rstrip("/") + "/" + quote(booking["id"], safe="")
        return {"id": event_id(booking), "status": "confirmed",
                "summary": f"{booking['reference']} · {booking['service_type']}",
                "location": booking["venue"],
                "description": f"Booking: {booking['reference']}\nService: {booking['service_type']}\nPrivate owner dashboard: {link}",
                "start": {"dateTime": start.astimezone(zone).isoformat(), "timeZone": booking["timezone"]},
                "end": {"dateTime": end.astimezone(zone).isoformat(), "timeZone": booking["timezone"]},
                "extendedProperties": {"private": ownership(booking)},
                "visibility": "private", "transparency": "opaque",
                "guestsCanInviteOthers": False, "reminders": {"useDefault": False}}

    def _get(self, token, calendar_id, identifier):
        try:
            return self.google.get_event(token, calendar_id, identifier)
        except GoogleFailure as error:
            if error.category == "missing":
                return None
            raise

    def _delete(self, token, calendar_id, identifier, booking):
        event = self._get(token, calendar_id, identifier)
        if not event or event.get("status") == "cancelled":
            return
        if not owns(event, booking):
            raise GoogleFailure("repair_required", "The event ownership metadata does not match this booking. Investigate before repair.")
        try:
            self.google.delete_event(token, calendar_id, identifier)
        except GoogleFailure as error:
            if error.category != "missing":
                raise

    def _project(self, booking, connection, token, repair):
        calendar_id = connection.get("calendar_id")
        if not calendar_id:
            raise GoogleFailure("repair_required", "The calendar is not configured. Reconnect Google Calendar.")
        mapped_calendar = booking.get("google_calendar_id")
        identifier = event_id(booking) if booking.get("calendar_repair_pending") else booking.get("google_event_id") or event_id(booking)
        if booking["status"] != "confirmed":
            # Use the historical calendar even if the configured target changed.
            self._delete(token, mapped_calendar or calendar_id, identifier, booking)
            return mapped_calendar or calendar_id, identifier
        self.google.check_calendar(token, calendar_id)
        if mapped_calendar and mapped_calendar != calendar_id:
            if not repair:
                raise GoogleFailure("repair_required", "The selected calendar changed. Use repair to remove the old event and recreate it on the selected calendar.")
            self._delete(token, mapped_calendar, identifier, booking)
            identifier = event_id(booking)
        event = self._get(token, calendar_id, identifier)
        if event:
            if owns(event, booking):
                if (event.get("status") == "cancelled" and booking.get("calendar_synced_status") != "cancelled"
                        and not repair and not booking.get("calendar_create_pending")):
                    raise GoogleFailure("repair_required", "The mapped event was deleted in Google Calendar. Use the owner repair action to restore it.")
                body = self._body(booking)
                body["id"] = identifier
                # Also restores an owned event after cancellation/reopening.
                self.google.update_event(token, calendar_id, identifier, body)
                return calendar_id, identifier
            if event.get("status") != "cancelled" or not booking.get("google_event_id"):
                raise GoogleFailure("repair_required", "The event identifier belongs to another event. Investigate its ownership before retrying.")
        missing_mapping = booking.get("google_event_id") and mapped_calendar == calendar_id
        if (event or missing_mapping) and not booking.get("calendar_repair_pending") and not booking.get("calendar_create_pending"):
            if not repair:
                raise GoogleFailure("repair_required", "The mapped event was deleted in Google Calendar. Use the owner repair action to recreate it.")
            # Deleted event IDs may be tombstoned. Persist a new deterministic
            # generation before inserting, so a crash still retries the same ID.
            booking["event_generation"] = int(booking.get("event_generation", 0)) + 1
            booking["calendar_repair_pending"] = True
            identifier = event_id(booking)
            with self.store.transaction() as tx:
                current = tx.get_booking(booking["id"])
                if current and current["revision"] == booking["revision"]:
                    current["event_generation"] = booking["event_generation"]
                    current["calendar_repair_pending"] = True
                    tx.save_booking(current)
                else:
                    raise GoogleFailure("transient", "The booking changed during repair. Retry synchronization.")
        elif booking.get("calendar_repair_pending"):
            identifier = event_id(booking)
        body = self._body(booking)
        body["id"] = identifier
        # Record the intended target before insertion. Cancellation or a
        # connection change during Google's response must still know where a
        # successfully inserted event needs to be removed.
        with self.store.transaction() as tx:
            current = tx.get_booking(booking["id"])
            if not current or current["revision"] != booking["revision"]:
                raise GoogleFailure("transient", "The booking changed before event creation. Retry synchronization.")
            current.update(google_calendar_id=calendar_id, google_event_id=identifier,
                           calendar_create_pending=True)
            tx.save_booking(current)
        try:
            self.google.insert_event(token, calendar_id, body)
        except GoogleFailure as error:
            if error.category != "conflict":
                raise
            # Covers duplicate delivery and a crash after Google succeeded but
            # before the mapping transaction committed.
            existing = self.google.get_event(token, calendar_id, identifier)
            if not owns(existing, booking):
                raise GoogleFailure("repair_required", "The event identifier already exists with different ownership. Investigate before retrying.") from None
            self.google.update_event(token, calendar_id, identifier, body)
        return calendar_id, identifier

    def _record_error(self, booking, error, snapshot):
        category = error.category
        status = {"transient": "pending", "reconnect_required": "reconnect_required", "missing": "repair_required",
                  "repair_required": "repair_required"}.get(category, "failed")
        with self.store.transaction() as tx:
            connection = tx.get_connection(booking["owner_id"]) or {}
            if connection.get("connection_revision", 0) != (snapshot or {}).get("connection_revision", 0):
                # An old grant's response cannot change a newly reconnected or
                # explicitly disconnected integration, even on the same calendar.
                return False
            current = tx.get_booking(booking["id"])
            if current and current["revision"] == booking["revision"]:
                current.update(calendar_status=status, calendar_error=error.message)
                tx.save_booking(current)
            if category == "reconnect_required":
                if connection and connection.get("status") != "disconnected":
                    connection.update(status="reconnect_required", last_error=error.message,
                                      updated_at=stamp(self.clock()))
                    tx.save_connection(connection)
        return True

    def run(self, booking_id, revision=None, repair=False):
        # The job's revision is deliberately not authoritative. This lock is
        # held across network calls; dashboard transitions use the same named
        # lock and may briefly wait while this projection is being applied.
        with self.store.booking_lock(booking_id):
            for _ in range(8):
                with self.store.transaction() as tx:
                    booking = tx.get_booking(booking_id)
                    connection = tx.get_connection(booking["owner_id"]) if booking else None
                if not booking or (booking["status"] not in {"confirmed", "cancelled"} and not booking.get("google_event_id")):
                    return {"status": "obsolete"}
                repair = repair or bool(booking.get("calendar_repair_requested"))
                try:
                    token = self.oauth.access_token(booking["owner_id"])
                    if not connection or connection.get("status") != "connected":
                        raise GoogleFailure("reconnect_required", "Connect Google Calendar before synchronizing bookings.")
                    calendar_id, identifier = self._project(booking, connection, token, repair)
                except GoogleFailure as error:
                    if not self._record_error(booking, error, connection):
                        continue
                    raise
                with self.store.transaction() as tx:
                    current = tx.get_booking(booking_id)
                    active_connection = tx.get_connection(booking["owner_id"]) or {}
                    same_connection = (active_connection.get("status") == "connected"
                                       and active_connection.get("calendar_id") == connection.get("calendar_id")
                                       and active_connection.get("connection_revision", 0) == connection.get("connection_revision", 0))
                    if current and current["revision"] == booking["revision"] and same_connection:
                        current.update(google_event_id=identifier, google_calendar_id=calendar_id,
                                       synced_revision=booking["revision"], calendar_status="synced",
                                       calendar_synced_status=booking["status"],
                                       last_synced_at=stamp(self.clock()), calendar_error=None,
                                       calendar_repair_pending=False, calendar_create_pending=False,
                                       calendar_repair_requested=False)
                        tx.save_booking(current)
                        return {"status": "synced", "revision": booking["revision"]}
                    if not same_connection:
                        continue
            raise GoogleFailure("transient", "The booking keeps changing. Retry synchronization after the owner finishes editing.")
