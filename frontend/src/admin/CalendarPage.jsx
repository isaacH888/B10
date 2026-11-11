import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import "./admin-dashboard.css";
import "./calendar.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";
import { fetchCalendar } from "./adminApi.js";

const NAV_ITEMS = [
  { label: "Dashboard", icon: iconDashboard, href: "/admin/dashboard" },
  { label: "Orders", icon: iconOrders, href: "/admin/orders" },
  { label: "Calendar", icon: iconCalendar, href: "/admin/calendar" },
  { label: "Inventory", icon: iconInventory, href: "/admin/inventory" },
];
const DOW_LABELS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function AdminNav() {
  return (
    <aside className="adm-nav" aria-label="Admin navigation">
      <div className="adm-nav__brand">
        <img
          src={logoSrc}
          alt="Popssibilities logo"
          className="adm-nav__logo"
          width={64}
          height={58}
        />
        <p className="adm-nav__site-name">POPSSIBILITIES</p>
        <p className="adm-nav__area">BUSINESS ADMIN</p>
      </div>
      <nav aria-label="Admin pages">
        <ul className="adm-nav__list" role="list">
          {NAV_ITEMS.map((item) => {
            const isActive = item.href === "/admin/calendar";
            return (
              <li key={item.label}>
                <Link
                  to={item.href}
                  className={
                    isActive
                      ? "adm-nav__link adm-nav__link--active"
                      : "adm-nav__link"
                  }
                  aria-current={isActive ? "page" : undefined}
                >
                  <img
                    src={item.icon}
                    alt=""
                    aria-hidden="true"
                    className="adm-nav__icon"
                    width={24}
                    height={24}
                  />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="adm-nav__note">
        <p className="adm-nav__note-heading">
          A LITTLE ORDER.
          <br />A LOT OF JOY.
        </p>
        <p className="adm-nav__note-sub">
          Houston, TX
          <br />
          Owner workspace
        </p>
      </div>
    </aside>
  );
}

// Build a calendar grid for a given year/month
function buildGrid(year, month) {
  const firstDow = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

// Event detail data for the drawer (matches what backend would return)
const EVENT_DETAILS = {
  "#1045": {
    orderId: "#1045",
    customer: "Elena Martinez",
    date: "Sat, Nov 7, 2026 · 2:00–4:00 PM",
    location: "Hermann Park · 1500 Hermann Dr, Houston TX 77004",
    service: "Full Service",
    qty: 150,
    bookingStatus: "Confirmed",
    bookingStatusSub: "Availability approved",
    paymentStatus: "Part paid · 50% verified",
    paymentStatusSub: "$650 remaining",
    syncType: "failed",
    syncError: {
      title: "GOOGLE CALENDAR · SYNC FAILED",
      body: "Google Calendar could not save this event because of a temporary service error. No external event was created.",
      account: "owner@popssibilities.com",
      calendar: "Catering",
      lastAttempt: "Nov 4, 2026 at 9:12 AM Central",
    },
    booking_ok_note: {
      heading: "YOUR BOOKING IS STILL CONFIRMED",
      body: "Availability approved + verified $650 deposit.\n150 paletas stay reserved. A calendar sync error does not cancel the booking or change payment status.",
    },
    contact: { email: "elena.martinez@example.com", phone: "(713) 555-0145" },
    orderSummary: "Total $1,300 · Verified $650 · Remaining $650",
  },
  "#1044": {
    orderId: "#1044",
    customer: "Bayou Creative",
    date: "Sun, Nov 8, 2026 · 11:00 AM",
    location: "Bayou Creative Studio · 2802 White Oak Dr, Houston TX 77007",
    service: "Delivery",
    qty: 120,
    bookingStatus: "Confirmed",
    bookingStatusSub: "Availability approved",
    paymentStatus: "Part paid · Review",
    paymentStatusSub: "$480 unverified",
    syncType: "synced",
    contact: { email: "events@bayoucreative.com", phone: "(713) 555-0144" },
    orderSummary: "Total $960 · Verified $480 · Remaining $480",
  },
};

// ---------------------------------------------------------------------------
// Event Detail Drawer
// ---------------------------------------------------------------------------
function EventDetailDrawer({ event, onClose }) {
  const navigate = useNavigate();
  const detail = EVENT_DETAILS[event.orderId];

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div
        className="cal-drawer-backdrop"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className="cal-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cal-drawer-title"
      >
        <div className="cal-drawer__header">
          <div>
            <p className="cal-drawer__eyebrow">
              ORDER {event.orderId} · {event.date}
            </p>
            <h2 className="cal-drawer__title" id="cal-drawer-title">
              {event.customer.toUpperCase()}
            </h2>
            <p className="cal-drawer__sub">
              {event.service} · {event.qty} paletas
            </p>
          </div>
          <button
            type="button"
            className="cal-drawer__close"
            onClick={onClose}
            aria-label="Close event details"
          >
            Close ×
          </button>
        </div>

        {detail ? (
          <>
            {/* Location */}
            <div className="cal-drawer__detail-row">
              <p className="cal-drawer__detail-label">DATE & TIME</p>
              <p className="cal-drawer__detail-val">{detail.date}</p>
            </div>
            {detail.location && (
              <div className="cal-drawer__detail-row">
                <p className="cal-drawer__detail-label">LOCATION</p>
                <p className="cal-drawer__detail-val">{detail.location}</p>
              </div>
            )}

            {/* Status cards */}
            <div className="cal-drawer__status-row">
              <div className="cal-drawer__status-card">
                <p className="cal-drawer__status-label">BOOKING</p>
                <p className="cal-drawer__status-val">{detail.bookingStatus}</p>
                <p className="cal-drawer__status-sub">
                  {detail.bookingStatusSub}
                </p>
              </div>
              <div className="cal-drawer__status-card">
                <p className="cal-drawer__status-label">PAYMENT</p>
                <p className="cal-drawer__status-val">{detail.paymentStatus}</p>
                <p className="cal-drawer__status-sub">
                  {detail.paymentStatusSub}
                </p>
              </div>
            </div>

            {/* Sync failure panel */}
            {detail.syncType === "failed" && detail.syncError && (
              <div className="cal-drawer__sync-failure">
                <p className="cal-drawer__sync-failure-title">
                  {detail.syncError.title}
                </p>
                <p className="cal-drawer__sync-failure-body">
                  {detail.syncError.body}
                </p>
                <p className="cal-drawer__sync-failure-meta">
                  Connected: {detail.syncError.account}
                  <br />
                  Calendar: {detail.syncError.calendar}
                  <br />
                  Last attempt: {detail.syncError.lastAttempt}
                </p>
                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  style={{ marginTop: "16px" }}
                  onClick={() =>
                    navigate(
                      `/admin/orders/${encodeURIComponent(event.orderId)}`,
                    )
                  }
                >
                  Review sync in order details
                </button>
              </div>
            )}

            {/* Booking not affected note */}
            {detail.syncType === "failed" && detail.booking_ok_note && (
              <div className="cal-drawer__booking-ok">
                <p className="cal-drawer__booking-ok-heading">
                  {detail.booking_ok_note.heading}
                </p>
                <p className="cal-drawer__booking-ok-body">
                  {detail.booking_ok_note.body}
                </p>
              </div>
            )}

            {/* Contact */}
            {detail.contact && (
              <div className="cal-drawer__detail-row">
                <p className="cal-drawer__detail-label">CUSTOMER CONTACT</p>
                <p className="cal-drawer__detail-val">
                  {detail.contact.email}
                  <br />
                  {detail.contact.phone}
                </p>
              </div>
            )}

            {/* Order summary */}
            {detail.orderSummary && (
              <div className="cal-drawer__detail-row">
                <p className="cal-drawer__detail-label">ORDER SUMMARY</p>
                <p className="cal-drawer__detail-val">{detail.orderSummary}</p>
                <p className="cal-drawer__detail-sub">
                  Review flavors, special instructions, and the payment history
                  in the full order details.
                </p>
              </div>
            )}
          </>
        ) : (
          <div className="cal-drawer__detail-row">
            <p className="cal-drawer__detail-val">
              Date: {event.date} · {event.time}
            </p>
            <p className="cal-drawer__detail-val">
              Service: {event.service} · {event.qty} paletas
            </p>
            <p className="cal-drawer__detail-val">Status: {event.booking}</p>
          </div>
        )}

        <div className="cal-drawer__actions">
          <button
            type="button"
            className="adm-btn adm-btn--primary"
            onClick={() => {
              onClose();
              navigate(`/admin/orders/${encodeURIComponent(event.orderId)}`);
            }}
          >
            Open order details ↗
          </button>
          <button
            type="button"
            className="adm-btn adm-btn--outline"
            onClick={onClose}
          >
            Back to calendar
          </button>
        </div>
        <p className="cal-drawer__footer-note">
          Selected event: {event.orderId}. Booking, payment, and sync are
          independent.
        </p>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Calendar Cell
// ---------------------------------------------------------------------------
function CalendarCell({ day, event, isToday, onSelect }) {
  if (!day)
    return <div className="cal-cell cal-cell--empty" aria-hidden="true" />;

  return (
    <div
      className={`cal-cell${event ? " cal-cell--has-event" : ""}`}
      role="gridcell"
    >
      <div
        className={`cal-cell__date${isToday ? " cal-cell__date--today" : ""}`}
        aria-label={`${day}${isToday ? ", today" : ""}`}
      >
        {day}
      </div>
      {event && (
        <button
          type="button"
          className={`cal-event cal-event--${event.color}`}
          onClick={() => onSelect(event)}
          aria-label={`${event.customer}, ${event.service}, ${event.qty} paletas, ${event.bookingStatus}`}
        >
          <p className="cal-event__name">{event.customer}</p>
          <p className="cal-event__time">
            {/* time shown in upcoming list */}
            {event.service}
          </p>
          <p
            className={`cal-event__status cal-event__status--${event.bookingStatus === "pending" ? "pending" : event.syncStatus === "failed" ? "confirmed-warn" : "confirmed"}`}
          >
            {event.bookingStatus === "pending"
              ? "Pending →"
              : event.syncStatus === "failed"
                ? "Confirmed · Sync failed"
                : "Confirmed →"}
          </p>
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export function CalendarPage() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1); // 1-indexed
  const [view, setView] = useState("month"); // "month" | "upcoming"
  const [events, setEvents] = useState({});
  const [stats, setStats] = useState({ confirmed: 0, pending: 0, reserved: 0 });
  const [loading, setLoading] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchCalendar(year, month);
      setEvents(data.events);
      setStats(data.stats);
    } catch {
      // fail silently for calendar — show empty grid
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    load();
  }, [load]);

  function prevMonth() {
    if (month === 1) {
      setYear((y) => y - 1);
      setMonth(12);
    } else setMonth((m) => m - 1);
  }
  function nextMonth() {
    if (month === 12) {
      setYear((y) => y + 1);
      setMonth(1);
    } else setMonth((m) => m + 1);
  }

  const upcomingEvents = Object.entries(events).map(([day, event]) => ({
    ...event,
    date: new Date(year, month - 1, Number(day)).toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    }),
    booking:
      event.bookingStatus === "pending" ? "Pending request" : "Confirmed",
    sync:
      event.syncStatus === "synced"
        ? "Synced"
        : event.syncStatus === "failed"
          ? "Sync failed"
          : "Not eligible yet",
    syncType: event.syncStatus,
  }));
  const weeks = buildGrid(year, month);
  const todayDay =
    today.getFullYear() === year && today.getMonth() + 1 === month
      ? today.getDate()
      : null;

  return (
    <div className="adm-shell">
      <AdminNav />

      <div className="adm-main">
        <header className="adm-page-header">
          <p className="adm-page-header__title">Calendar</p>
          <div className="adm-page-header__actions">
            <a href="/" className="adm-page-header__view-site">
              View website ↗
            </a>
            <Link to="/admin" className="adm-btn adm-btn--outline">
              Owner account
            </Link>
          </div>
        </header>

        <div className="adm-content">
          {/* Hero */}
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">
                {view === "upcoming" ? "UPCOMING EVENTS" : "MAKE ROOM FOR JOY."}
              </h1>
              <p className="adm-hero-row__sub">
                {`${MONTH_NAMES[month - 1]} ${year} · ${stats.confirmed} confirmed bookings · ${stats.pending} pending requests · ${stats.reserved} paletas reserved · All times Central`}
              </p>
            </div>
          </div>

          {/* Google Calendar banner */}
          <div className="cal-gcal-banner">
            <div className="cal-gcal-banner__info">
              <p className="cal-gcal-banner__title">
                GOOGLE CALENDAR · CONNECTED
              </p>
              <p className="cal-gcal-banner__account">
                owner@popssibilities.com · Catering calendar
              </p>
              <p className="cal-gcal-banner__sync">
                Last sync Nov 4, 9:12 AM · 5 synced · 1 failed. Pending requests
                stay internal.
              </p>
            </div>
            <Link to="/admin/automation" className="adm-btn adm-btn--outline">
              Manage connection
            </Link>
          </div>

          {/* Nav row */}
          <div className="cal-nav-row">
            <h2 className="cal-month-heading">
              {MONTH_NAMES[month - 1].toUpperCase()} {year}
            </h2>
            <div className="cal-nav-controls">
              <button
                type="button"
                className="adm-btn adm-btn--outline"
                onClick={prevMonth}
                aria-label="Previous month"
              >
                ‹ Previous
              </button>
              <button
                type="button"
                className="adm-btn adm-btn--outline"
                onClick={nextMonth}
                aria-label="Next month"
              >
                Next ›
              </button>
            </div>
            <div
              className="cal-view-toggle"
              role="group"
              aria-label="Calendar view"
            >
              <button
                type="button"
                className={`adm-btn ${view === "month" ? "adm-btn--primary" : "adm-btn--outline"}`}
                onClick={() => setView("month")}
                aria-pressed={view === "month"}
              >
                Month
              </button>
              <button
                type="button"
                className={`adm-btn ${view === "upcoming" ? "adm-btn--primary" : "adm-btn--outline"}`}
                onClick={() => setView("upcoming")}
                aria-pressed={view === "upcoming"}
              >
                Upcoming
              </button>
            </div>
          </div>

          {/* Loading */}
          {loading && (
            <p
              role="status"
              style={{ fontFamily: "'DM Sans', sans-serif", fontSize: "15px" }}
            >
              Loading calendar…
            </p>
          )}

          {/* Month view */}
          {!loading && view === "month" && (
            <section
              className="adm-card adm-card--outlined cal-grid-card"
              aria-label={`${MONTH_NAMES[month - 1]} ${year} calendar`}
            >
              <div className="cal-dow-row" role="row">
                {DOW_LABELS.map((d) => (
                  <div key={d} className="cal-dow-label" role="columnheader">
                    {d}
                  </div>
                ))}
              </div>
              <div className="cal-grid" role="grid" aria-label="Calendar days">
                {weeks.map((week, wi) => (
                  <div key={wi} className="cal-week" role="row">
                    {week.map((day, di) => (
                      <CalendarCell
                        key={`${wi}-${di}`}
                        day={day}
                        event={day ? events[day] : null}
                        isToday={day === todayDay}
                        onSelect={(ev) =>
                          setSelectedEvent({
                            ...ev,
                            day,
                            orderId: ev.orderId,
                            date: `${MONTH_NAMES[month - 1]} ${day}`,
                            time: "",
                          })
                        }
                      />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Upcoming view */}
          {!loading && view === "upcoming" && (
            <section
              className="adm-card adm-card--outlined cal-upcoming-card"
              aria-labelledby="cal-upcoming-heading"
            >
              <h2 className="visually-hidden" id="cal-upcoming-heading">
                Upcoming events for {MONTH_NAMES[month - 1]} {year}
              </h2>

              {/* Summary banner */}
              <div className="cal-upcoming-banner" role="status">
                <p className="cal-upcoming-banner__text">
                  ONLY CONFIRMED BOOKINGS RESERVE STOCK &amp; SYNC &nbsp;·&nbsp;{" "}
                  {stats.reserved} paletas reserved across {stats.confirmed}{" "}
                  bookings. The {stats.pending} pending requests are visible for
                  planning only.
                </p>
              </div>

              <div
                className="adm-table-wrap"
                role="region"
                aria-label="Upcoming events table"
                tabIndex={0}
              >
                <table className="adm-orders-table cal-upcoming-table">
                  <thead>
                    <tr>
                      <th scope="col">EVENT / TIME</th>
                      <th scope="col">CUSTOMER</th>
                      <th scope="col">QTY</th>
                      <th scope="col">SERVICE</th>
                      <th scope="col">BOOKING</th>
                      <th scope="col">GOOGLE SYNC</th>
                      <th scope="col">ORDER</th>
                    </tr>
                  </thead>
                  <tbody>
                    {upcomingEvents.map((ev) => (
                      <tr
                        key={ev.orderId}
                        className={`cal-upcoming-row cal-upcoming-row--${ev.booking === "Pending request" ? "pending" : "confirmed"}`}
                      >
                        <td>
                          <p style={{ margin: 0, fontWeight: 400 }}>
                            {ev.date}
                          </p>
                          <p style={{ margin: 0, fontWeight: 400 }}>
                            {ev.time}
                          </p>
                        </td>
                        <td style={{ fontWeight: 700 }}>{ev.customer}</td>
                        <td>{ev.qty}</td>
                        <td>{ev.service}</td>
                        <td style={{ fontWeight: 700 }}>{ev.booking}</td>
                        <td
                          className={
                            ev.syncType === "failed"
                              ? "cal-upcoming__sync--failed"
                              : ""
                          }
                        >
                          {ev.sync}
                        </td>
                        <td>
                          <Link
                            to={`/admin/orders/${encodeURIComponent(ev.orderId)}`}
                            className="adm-card__link"
                          >
                            {ev.orderId} ↗
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* Legend */}
          <div className="cal-legend" aria-label="Calendar legend">
            <span className="cal-legend__item">
              <span
                className="cal-legend__dot cal-legend__dot--yellow"
                aria-hidden="true"
              />
              Confirmed (Sync active)
            </span>
            <span className="cal-legend__item">
              <span
                className="cal-legend__dot cal-legend__dot--pink"
                aria-hidden="true"
              />
              Confirmed
            </span>
            <span className="cal-legend__item">
              <span
                className="cal-legend__dot cal-legend__dot--cream"
                aria-hidden="true"
              />
              Pending request
            </span>
          </div>
        </div>
      </div>

      {/* Event detail drawer */}
      {selectedEvent && (
        <EventDetailDrawer
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}
