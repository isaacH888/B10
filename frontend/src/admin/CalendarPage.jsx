import { useCallback, useEffect, useRef, useState } from "react";
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
function EventDetailDrawer({ event, onClose }) {
  const navigate = useNavigate();
  const detail = event.detail;

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

                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  style={{ marginTop: "16px" }}
                  onClick={() => navigate(event.href)}
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
              navigate(event.href);
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
function CalendarCell({ day, events, isToday, onSelect }) {
  if (!day)
    return <div className="cal-cell cal-cell--empty" aria-hidden="true" />;

  return (
    <div
      className={`cal-cell${events.length ? " cal-cell--has-event" : ""}`}
      role="gridcell"
    >
      <div
        className={`cal-cell__date${isToday ? " cal-cell__date--today" : ""}`}
        aria-label={`${day}${isToday ? ", today" : ""}`}
      >
        {day}
      </div>
      {events.map((event) => (
        <button
          key={event.id}
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
            {event.booking}{" "}
            {event.syncStatus === "failed" ? "· Sync failed" : "→"}
          </p>
        </button>
      ))}
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
  const [stats, setStats] = useState({
    confirmed: 0,
    pending: 0,
    confirmed_quantity: 0,
  });
  const [loading, setLoading] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [connection, setConnection] = useState({ status: "loading" });
  const [error, setError] = useState(false);
  const latestRequest = useRef(0);

  const load = useCallback(async () => {
    const version = ++latestRequest.current;
    setLoading(true);
    setError(false);
    setSelectedEvent(null);
    try {
      const data = await fetchCalendar(year, month);
      if (version !== latestRequest.current) return;
      setEvents(data.events);
      setStats(data.stats);
      setConnection(data.connection);
    } catch {
      if (version !== latestRequest.current) return;
      setError(true);
      setEvents({});
      setConnection({ status: "unavailable" });
    } finally {
      if (version === latestRequest.current) setLoading(false);
    }
  }, [year, month]);

  useEffect(() => {
    load();
    return () => {
      latestRequest.current += 1;
    };
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

  const upcomingEvents = Object.values(events).flat();
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
                {`${MONTH_NAMES[month - 1]} ${year} · ${stats.confirmed} confirmed bookings · ${stats.pending} pending requests · ${stats.confirmed_quantity} paletas in confirmed bookings · All times Central`}
              </p>
            </div>
          </div>

          {/* Google Calendar banner */}
          <div className="cal-gcal-banner">
            <div className="cal-gcal-banner__info">
              <p className="cal-gcal-banner__title">
                GOOGLE CALENDAR · {connection.status.toUpperCase()}
              </p>
              <p className="cal-gcal-banner__account">
                {connection.calendar_id ||
                  connection.setup_message ||
                  "Manage the current owner connection in the booking workspace."}
              </p>
              <p className="cal-gcal-banner__sync">
                Event and booking data remain available when Google is
                disconnected.
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

          {error && (
            <p role="alert">
              Could not load calendar events.{" "}
              <button onClick={load}>Try again</button>
            </p>
          )}
          {/* Month view */}
          {!loading && !error && view === "month" && (
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
                        events={day ? events[day] || [] : []}
                        isToday={day === todayDay}
                        onSelect={setSelectedEvent}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Upcoming view */}
          {!loading && !error && view === "upcoming" && (
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
                  CONFIRMED BOOKINGS ARE ELIGIBLE FOR CALENDAR SYNC
                  &nbsp;·&nbsp; {stats.confirmed_quantity} paletas in confirmed
                  bookings across {stats.confirmed} bookings. The{" "}
                  {stats.pending} pending requests are visible for planning
                  only.
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
                    {upcomingEvents.length === 0 && (
                      <tr>
                        <td colSpan={7}>No events in this month.</td>
                      </tr>
                    )}
                    {upcomingEvents.map((ev) => (
                      <tr
                        key={ev.id}
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
                          <Link to={ev.href} className="adm-card__link">
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
