import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest, errorMessage, navigateToProvider } from "../auth/api.js";
import {
  fetchInventory,
  fetchBookingAllocations,
  saveBookingAllocations,
} from "./adminApi.js";
import { AdminNav, PageHeader } from "./AdminNav.jsx";
import "./admin-dashboard.css";
import "./order-detail.css";
import "./automation.css";

const base = "/admin/automation";
const money = (value, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    value / 100,
  );
const time = (value) =>
  value
    ? new Date(
        typeof value === "number" ? value * 1000 : value,
      ).toLocaleString()
    : "Never";

function Input({ name, label, type = "text", ...props }) {
  return (
    <label className="od-modal__field">
      <span className="od-modal__label">{label}</span>
      <input
        name={name}
        type={type}
        className="od-modal__input"
        required
        {...props}
      />
    </label>
  );
}

function eventPayload(form) {
  return {
    start: form.get("start"),
    end: form.get("end"),
    timezone: form.get("timezone"),
    venue: form.get("venue"),
  };
}

function parseIsoParts(isoStr) {
  if (!isoStr || typeof isoStr !== "string") {
    return { date: "", time: "" };
  }
  const m = isoStr.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  if (m) {
    return { date: m[1], time: m[2] };
  }
  return { date: "", time: "" };
}

function getTzOffset(dateStr, timeZone = "America/Chicago") {
  try {
    const d = new Date(`${dateStr || "2027-06-01"}T12:00:00Z`);
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      timeZoneName: "longOffset",
    }).formatToParts(d);
    const tzPart = parts.find((p) => p.type === "timeZoneName");
    if (tzPart && tzPart.value.startsWith("GMT")) {
      const offset = tzPart.value.replace("GMT", "").trim();
      return offset || "-05:00";
    }
    return "-05:00";
  } catch {
    return "-05:00";
  }
}

function toIsoWithOffset(dateStr, timeStr, timeZone = "America/Chicago") {
  if (!dateStr || !timeStr) return "";
  const offset = getTzOffset(dateStr, timeZone);
  const timeFormatted = timeStr.length === 5 ? `${timeStr}:00` : timeStr;
  return `${dateStr}T${timeFormatted}${offset}`;
}

function addHoursToTime(timeStr, hours) {
  if (!timeStr) return "";
  const [h, m] = timeStr.split(":").map(Number);
  const newH = (h + hours) % 24;
  return `${String(newH).padStart(2, "0")}:${String(m || 0).padStart(2, "0")}`;
}

function EventFields({ booking = {} }) {
  const startParts = parseIsoParts(booking.start);
  const endParts = parseIsoParts(booking.end);

  const [date, setDate] = useState(startParts.date || "");
  const [startTime, setStartTime] = useState(startParts.time || "");
  const [endTime, setEndTime] = useState(endParts.time || "");
  const [timezone, setTimezone] = useState(
    booking.timezone || "America/Chicago",
  );

  useEffect(() => {
    const s = parseIsoParts(booking.start);
    const e = parseIsoParts(booking.end);
    if (s.date) setDate(s.date);
    if (s.time) setStartTime(s.time);
    if (e.time) setEndTime(e.time);
    if (booking.timezone) setTimezone(booking.timezone);
  }, [booking.start, booking.end, booking.timezone]);

  const isoStart = toIsoWithOffset(date, startTime, timezone);
  const isoEnd = toIsoWithOffset(date, endTime, timezone);

  const friendlyPreview =
    date && startTime && endTime
      ? (() => {
          try {
            const [y, m, d] = date.split("-").map(Number);
            const dateObj = new Date(y, m - 1, d);
            const dateFmt = dateObj.toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              year: "numeric",
            });
            const fmtTime = (t) => {
              const [h, min] = t.split(":").map(Number);
              const ampm = h >= 12 ? "PM" : "AM";
              const h12 = h % 12 || 12;
              return `${h12}:${String(min).padStart(2, "0")} ${ampm}`;
            };
            return `${dateFmt} · ${fmtTime(startTime)} – ${fmtTime(endTime)}`;
          } catch {
            return null;
          }
        })()
      : null;

  return (
    <div className="bkg-event-fields" style={{ marginBottom: 16 }}>
      {/* Hidden inputs preserve full ISO 8601 formatting for backend compatibility */}
      <input type="hidden" name="start" value={isoStart} />
      <input type="hidden" name="end" value={isoEnd} />
      <input type="hidden" name="timezone" value={timezone} />

      <div className="od-modal__field-row">
        <label className="od-modal__field">
          <span className="od-modal__label">Event date</span>
          <input
            type="date"
            className="od-modal__input"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>

        <label className="od-modal__field">
          <span className="od-modal__label">Time zone</span>
          <select
            className="od-modal__input"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          >
            <option value="America/Chicago">Central (Houston - CT)</option>
            <option value="America/New_York">Eastern (ET)</option>
            <option value="America/Denver">Mountain (MT)</option>
            <option value="America/Los_Angeles">Pacific (PT)</option>
          </select>
        </label>
      </div>

      <div className="od-modal__field-row">
        <label className="od-modal__field">
          <span className="od-modal__label">Start time</span>
          <input
            type="time"
            className="od-modal__input"
            required
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
          />
        </label>

        <label className="od-modal__field">
          <span className="od-modal__label">End time</span>
          <input
            type="time"
            className="od-modal__input"
            required
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
          />
        </label>
      </div>

      {friendlyPreview && (
        <div
          style={{
            marginTop: -4,
            marginBottom: 12,
            padding: "8px 12px",
            background: "#faf5ff",
            border: "1px solid #e9d5ff",
            borderRadius: 8,
            fontSize: 13,
            color: "#581c87",
            fontWeight: 600,
          }}
        >
          📅 Event window: {friendlyPreview} ({timezone})
        </div>
      )}

      <Input
        name="venue"
        label="Venue address / location"
        maxLength={500}
        defaultValue={booking.venue}
        placeholder="e.g. 801 Franklin St, Houston, TX 77002"
      />
    </div>
  );
}

function GoogleCalendarBox({
  connection,
  connectionLoading,
  connectionError,
  busy,
  mutate,
  refresh,
}) {
  return (
    <fieldset
      disabled={busy}
      className="bkg-calendar-box"
      role="group"
      aria-label="Google Calendar connection"
    >
      <legend>Google Calendar connection</legend>
      <div className="bkg-calendar-status-row">
        <span
          className="bkg-calendar-status-pill"
          role={connectionLoading ? "status" : undefined}
        >
          Connection:{" "}
          {connectionLoading ? "Loading…" : connection?.status || "Unavailable"}
        </span>
        {connection?.status === "connected" && (
          <span className="bkg-badge bkg-sync--synced">Connected</span>
        )}
        {connection?.status === "reconnect_required" && (
          <span className="bkg-badge bkg-sync--failed">Reconnect required</span>
        )}
      </div>

      {connectionError && (
        <p
          role="alert"
          style={{ color: "#991b1b", fontWeight: 700, margin: "6px 0" }}
        >
          {connectionError}
        </p>
      )}
      {connection?.setup_message && (
        <p style={{ margin: "6px 0", fontSize: 13, color: "#4b004b" }}>
          {connection.setup_message}
        </p>
      )}
      {connection?.calendar_id && (
        <p style={{ margin: "6px 0", fontSize: 13 }}>
          Calendar: {connection.calendar_id}
        </p>
      )}
      {connection?.last_error && (
        <p style={{ margin: "6px 0", color: "#991b1b", fontSize: 13 }}>
          {connection.last_error}
        </p>
      )}

      <div className="od-modal__actions" style={{ marginTop: 14 }}>
        <button
          type="button"
          className="adm-btn adm-btn--primary"
          disabled={
            connectionLoading ||
            !connection?.status ||
            connection.configured === false
          }
          onClick={() => mutate("/google/connect")}
        >
          {connection?.status === "connected"
            ? "Reconnect Google Calendar"
            : "Connect Google Calendar"}
        </button>
        <button
          type="button"
          className="adm-btn adm-btn--outline"
          disabled={
            connectionLoading ||
            !connection?.status ||
            connection.status === "disconnected"
          }
          onClick={() => mutate("/google/disconnect")}
        >
          Disconnect Google Calendar
        </button>
        <button
          type="button"
          className="adm-btn adm-btn--outline"
          disabled={connectionLoading}
          onClick={refresh}
        >
          Refresh status
        </button>
      </div>
    </fieldset>
  );
}

function ManualBookingForm({ busy, create }) {
  return (
    <details className="bkg-intake-card">
      <summary className="bkg-intake-summary">
        <span>+ Add a catering booking</span>
      </summary>
      <form onSubmit={create} style={{ marginTop: 16 }}>
        <fieldset
          disabled={busy}
          style={{ border: "none", padding: 0, margin: 0 }}
        >
          <legend className="bkg-info-label" style={{ marginBottom: 12 }}>
            Agreed order details
          </legend>
          <EventFields />
          <div className="od-modal__field-row">
            <Input
              name="quantity"
              label="Popsicle quantity"
              type="number"
              min="50"
              step="1"
              placeholder="e.g. 75"
            />
            <label className="od-modal__field">
              <span className="od-modal__label">Service type</span>
              <select name="service_type" className="od-modal__input">
                <option value="delivery">Delivery</option>
                <option value="full_service">Full service</option>
              </select>
            </label>
          </div>
          <div className="od-modal__field-row">
            <Input
              name="customer_email"
              label="Customer email"
              type="email"
              placeholder="customer@example.com"
            />
            <Input
              name="total_minor"
              label="Agreed total ($ USD)"
              type="text"
              placeholder="e.g. $150.00"
            />
          </div>
          {/* Currency is fixed to USD; no manual input required */}
          <input type="hidden" name="currency" value="USD" />
          <Input
            name="contract_url"
            label="Customer contract link (optional HTTPS)"
            type="url"
            placeholder="https://example.com/contract"
          />
          <div style={{ marginTop: 16 }}>
            <button className="adm-btn adm-btn--primary">
              Create booking request
            </button>
          </div>
        </fieldset>
      </form>
    </details>
  );
}

export function AutomationDashboard({ identity, csrfToken }) {
  const { bookingId } = useParams();
  const [items, setItems] = useState([]);
  const [orders, setOrders] = useState([]);
  const [ordersError, setOrdersError] = useState("");
  const [connection, setConnection] = useState(null);
  const [connectionLoading, setConnectionLoading] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");

  const owner = identity.role === "owner";
  const explain = (failure) =>
    failure.code === "reauthentication_required"
      ? errorMessage(failure)
      : failure.serverMessage || errorMessage(failure);

  const refresh = useCallback(async () => {
    if (!owner) return;
    setConnectionLoading(true);
    setConnection(null);
    setConnectionError("");
    const [bookings, google, selected, intake] = await Promise.allSettled([
      apiRequest(`${base}/bookings`),
      apiRequest(`${base}/google`),
      bookingId
        ? apiRequest(`${base}/bookings/${encodeURIComponent(bookingId)}`)
        : Promise.resolve(null),
      apiRequest(`${base}/orders`),
    ]);
    if (bookings.status === "fulfilled") setItems(bookings.value);
    if (selected.status === "fulfilled") setDetail(selected.value);
    else setDetail(null);
    const bookingFailure = [bookings, selected].find(
      (result) => result.status === "rejected",
    );
    setError(bookingFailure ? explain(bookingFailure.reason) : "");
    setOrders(intake.status === "fulfilled" ? intake.value : []);
    setOrdersError(intake.status === "rejected" ? explain(intake.reason) : "");
    if (google.status === "fulfilled") setConnection(google.value);
    else
      setConnectionError(
        `Could not load Google Calendar status. ${google.reason.serverMessage || "Please try again."}`,
      );
    setConnectionLoading(false);
    setLoaded(true);
  }, [bookingId, owner]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function mutate(path, body = {}) {
    setBusy(true);
    setError("");
    if (path.startsWith("/google/")) setConnectionError("");
    try {
      const result = await apiRequest(`${base}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(body),
      });
      if (result.authorization_url)
        navigateToProvider(result.authorization_url);
      else await refresh();
      return true;
    } catch (failure) {
      if (path.startsWith("/google/")) setConnectionError(explain(failure));
      else setError(explain(failure));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function create(event) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const rawTotal = String(form.get("total_minor") || "")
      .trim()
      .replace(/^\$/, "");
    const totalMinor = rawTotal.includes(".")
      ? Math.round(parseFloat(rawTotal) * 100)
      : Number(rawTotal);

    const ok = await mutate("/bookings", {
      ...eventPayload(form),
      quantity: Number(form.get("quantity")),
      total_minor: totalMinor,
      currency: form.get("currency"),
      service_type: form.get("service_type"),
      customer_email: form.get("customer_email"),
      contract_url: form.get("contract_url"),
    });
    if (ok) element.reset();
  }

  if (!owner)
    return (
      <section>
        <h2>Catering automation</h2>
        <p>Only the owner can operate booking automation.</p>
      </section>
    );

  const filteredBookings = items.filter((b) => {
    if (statusFilter === "all") return true;
    return b.status === statusFilter;
  });

  return (
    <div className="adm-shell">
      <AdminNav
        activeRoute={
          bookingId ? `/admin/bookings/${bookingId}` : "/admin/automation"
        }
      />

      <div className="adm-main">
        <PageHeader
          title={
            detail
              ? `Bookings / ${detail.booking.reference}`
              : "Bookings & Automation"
          }
        />

        <div className="adm-content">
          {/* Hero Row */}
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">
                {detail ? detail.booking.reference : "Catering automation"}
              </h1>
              <p className="adm-hero-row__sub">
                <Link to="/admin/automation" className="adm-card__link">
                  All bookings
                </Link>{" "}
                ·{" "}
                <Link to="/admin/login?reauth=1" className="adm-card__link">
                  Verify owner access again
                </Link>
              </p>
            </div>
            {detail && (
              <Link to="/admin/automation" className="adm-btn adm-btn--outline">
                ← All bookings
              </Link>
            )}
          </div>

          <p style={{ margin: "0 0 20px", fontSize: 14, color: "#4b004b" }}>
            Approve availability and reserve capacity before requesting a
            deposit. A verified 50% deposit confirms the booking.
          </p>

          {error && (
            <div
              className="ord-alert"
              style={{
                background: "#fee2e2",
                color: "#991b1b",
                marginBottom: 20,
              }}
              role="alert"
            >
              <p className="ord-alert__main">{error}</p>
            </div>
          )}

          {!loaded && <p role="status">Loading bookings…</p>}

          {/* Google Calendar Connection Box */}
          <GoogleCalendarBox
            connection={connection}
            connectionLoading={connectionLoading}
            connectionError={connectionError}
            busy={busy}
            mutate={mutate}
            refresh={refresh}
          />

          {/* Customer Order Intake Queue (only shown on all-bookings list view, not inside individual booking details) */}
          {!bookingId && (
            <section
              aria-labelledby="customer-intake-heading"
              role="region"
              aria-label="Customer order intake"
              style={{ marginBottom: 32 }}
            >
              <div className="bkg-section-header">
                <h3 id="customer-intake-heading" className="bkg-section-title">
                  Customer order intake
                </h3>
                {orders.length > 0 && (
                  <span className="bkg-badge bkg-badge--pending">
                    {orders.length} awaiting intake
                  </span>
                )}
              </div>

              <p style={{ margin: "0 0 16px", fontSize: 13, color: "#4b004b" }}>
                Review submitted orders, add the contract link and confirm the
                event end time. Creating a booking keeps the customer's saved
                selections and price. Approve availability separately.
              </p>

              {ordersError && (
                <p role="alert" style={{ color: "#991b1b", fontWeight: 700 }}>
                  Could not load customer orders. {ordersError}
                </p>
              )}
              {loaded && !ordersError && !orders.length && (
                <p style={{ fontSize: 14, color: "#3b003d" }}>
                  No customer orders awaiting intake.
                </p>
              )}
              {orders.length > 0 && (
                <div className="bkg-intake-list">
                  {orders.map((order) => (
                    <CustomerOrder
                      key={order.id}
                      order={order}
                      busy={busy}
                      mutate={mutate}
                    />
                  ))}
                </div>
              )}
            </section>
          )}

          {/* Selected Booking Detail */}
          {detail && (
            <BookingDetail
              key={`${detail.booking.id}:${detail.booking.revision}`}
              detail={detail}
              busy={busy}
              mutate={mutate}
              refresh={refresh}
            />
          )}

          {/* All Bookings Table View (when not viewing a single detail) */}
          {!bookingId && (
            <section
              style={{ marginTop: 24 }}
              aria-label="All catering bookings"
            >
              <div className="bkg-section-header">
                <h3 className="bkg-section-title">Catering bookings</h3>
                <span className="ord-count-badge">
                  {filteredBookings.length} bookings
                </span>
              </div>

              {/* Status filter tabs */}
              <div className="bkg-filter-tabs">
                {[
                  { id: "all", label: "All" },
                  { id: "requested", label: "Requested" },
                  { id: "awaiting_deposit", label: "Awaiting deposit" },
                  { id: "confirmed", label: "Confirmed" },
                  { id: "owner_review", label: "Owner review" },
                  { id: "fulfilled", label: "Fulfilled" },
                  { id: "cancelled", label: "Cancelled" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    className={`bkg-filter-btn ${statusFilter === tab.id ? "bkg-filter-btn--active" : ""}`}
                    onClick={() => setStatusFilter(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div
                className="adm-table-wrap"
                role="region"
                aria-label="Catering bookings"
                tabIndex={0}
              >
                <table className="adm-orders-table">
                  <caption className="adm-sr-only">Catering bookings</caption>
                  <thead>
                    <tr>
                      <th scope="col">Reference</th>
                      <th scope="col">Booking</th>
                      <th scope="col">Payment</th>
                      <th scope="col">Remaining</th>
                      <th scope="col">Calendar</th>
                      <th scope="col">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredBookings.map((booking) => (
                      <tr key={booking.id}>
                        <td>
                          <Link
                            to={`/admin/bookings/${booking.id}`}
                            className="adm-card__link"
                            style={{ fontWeight: 700 }}
                          >
                            {booking.reference}
                          </Link>
                        </td>
                        <td>
                          <span
                            className={`bkg-badge bkg-badge--${booking.status}`}
                          >
                            {booking.status}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`bkg-badge bkg-pay--${booking.payment_status}`}
                          >
                            {booking.payment_status}
                          </span>
                        </td>
                        <td style={{ fontWeight: 700 }}>
                          {money(booking.remaining_minor, booking.currency)}
                        </td>
                        <td>
                          <span
                            className={`bkg-badge bkg-sync--${booking.calendar_status}`}
                          >
                            {booking.calendar_status}
                          </span>
                        </td>
                        <td>
                          <Link
                            to={`/admin/bookings/${booking.id}`}
                            className="adm-card__link"
                            style={{ fontWeight: 700, whiteSpace: "nowrap" }}
                          >
                            View details ↗
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {loaded && !error && !items.length && <p>No bookings yet.</p>}

              {/* Add manual booking */}
              <div style={{ marginTop: 24 }}>
                <ManualBookingForm busy={busy} create={create} />
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function BookingInventory({ booking, refresh }) {
  const [catalog, setCatalog] = useState(null);
  const [quantities, setQuantities] = useState({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    if (booking.status !== "confirmed")
      return () => {
        active = false;
      };
    Promise.all([fetchInventory(), fetchBookingAllocations(booking.id)])
      .then(([inventory, allocations]) => {
        if (!active) return;
        setCatalog(inventory.items);
        setQuantities(
          Object.fromEntries(
            allocations.items.map((item) => [
              item.item_id,
              String(item.quantity),
            ]),
          ),
        );
      })
      .catch(() => {
        if (active) setError("Inventory allocations could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, [booking.id, booking.status]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await saveBookingAllocations(booking.id, {
        expected_revision: booking.revision,
        items: Object.entries(quantities)
          .filter(([, qty]) => Number(qty) > 0)
          .map(([item_id, qty]) => ({ item_id, quantity: Number(qty) })),
      });
      await refresh();
    } catch (failure) {
      setError(failure.message || "Could not save stock allocations.");
    } finally {
      setSaving(false);
    }
  }

  if (booking.status !== "confirmed")
    return (
      <section
        className="adm-card adm-card--outlined od-section"
        style={{ marginBottom: 24 }}
      >
        <h4 className="od-section__title">FLAVOR STOCK ALLOCATIONS</h4>
        <p
          style={{
            margin: "12px 0 0",
            fontSize: 13,
            color: "#4b004b",
            lineHeight: 1.5,
          }}
        >
          Confirm the booking before assigning flavor stock. Cancellation
          releases its allocations.
        </p>
      </section>
    );

  const totalAllocated = Object.values(quantities).reduce(
    (sum, q) => sum + (Number(q) || 0),
    0,
  );
  const unallocated = booking.quantity - totalAllocated;

  return (
    <section
      aria-label="Flavor stock allocations"
      className="bkg-allocations-panel"
    >
      <div className="bkg-section-header">
        <h4 className="bkg-section-title">Flavor stock allocations</h4>
        <span
          className={`bkg-meter-badge ${
            unallocated === 0
              ? "bkg-meter-badge--ok"
              : unallocated > 0
                ? "bkg-meter-badge--warn"
                : "bkg-meter-badge--error"
          }`}
        >
          {unallocated === 0
            ? "Fully allocated"
            : unallocated > 0
              ? `${unallocated} unallocated`
              : `${Math.abs(unallocated)} over-allocated`}
        </span>
      </div>

      <p style={{ margin: "0 0 16px", fontSize: 13, color: "#4b004b" }}>
        Assign specific flavors to this confirmed booking. Free-text flavor
        requests do not reserve inventory. Cancellation releases allocations.
      </p>

      {/* Allocation meter bar */}
      <div className="bkg-allocation-meter">
        <div>
          <span className="bkg-info-label">Paleta reservation progress</span>
          <p className="bkg-meter-numbers">
            {totalAllocated} / {booking.quantity}
          </p>
        </div>
        <p style={{ margin: 0, fontSize: 13, color: "#3b003d" }}>
          {unallocated > 0
            ? `Allocate ${unallocated} more paletas to meet the agreed order quantity.`
            : unallocated === 0
              ? "All popsicles have reserved inventory."
              : "Warning: Allocated quantity exceeds total booking quantity!"}
        </p>
      </div>

      {error && (
        <p role="alert" style={{ color: "#991b1b", fontWeight: 700 }}>
          {error}{" "}
          <button type="button" onClick={refresh} className="adm-card__link">
            Refresh booking
          </button>
        </p>
      )}

      {catalog === null && !error && (
        <p role="status">Loading stock allocations…</p>
      )}

      {catalog && (
        <form onSubmit={save}>
          <fieldset
            disabled={saving}
            style={{ border: "none", padding: 0, margin: 0 }}
          >
            <legend className="adm-sr-only">
              Reserved flavors for {booking.quantity} paletas
            </legend>

            {catalog.length === 0 && (
              <p>
                No inventory items yet.{" "}
                <Link to="/admin/inventory">Add inventory</Link>.
              </p>
            )}

            <div className="bkg-flavor-grid">
              {catalog.map((item) => {
                const currentQty = Number(quantities[item.id]) || 0;
                return (
                  <div key={item.id} className="bkg-flavor-card">
                    <div>
                      <p className="bkg-flavor-title">{item.name}</p>
                      <p className="bkg-flavor-stock">
                        {item.available} available in stock
                      </p>
                    </div>

                    <div className="bkg-qty-stepper">
                      <button
                        type="button"
                        className="bkg-qty-btn"
                        disabled={saving || currentQty <= 0}
                        onClick={() =>
                          setQuantities((curr) => ({
                            ...curr,
                            [item.id]: String(Math.max(0, currentQty - 1)),
                          }))
                        }
                        aria-label={`Decrease ${item.name}`}
                      >
                        -
                      </button>

                      <input
                        type="number"
                        min="0"
                        step="1"
                        max={booking.quantity}
                        value={quantities[item.id] || ""}
                        className="bkg-qty-input"
                        onChange={(event) =>
                          setQuantities((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                        aria-label={`Reserve ${item.name}`}
                      />

                      <button
                        type="button"
                        className="bkg-qty-btn"
                        disabled={saving}
                        onClick={() =>
                          setQuantities((curr) => ({
                            ...curr,
                            [item.id]: String(currentQty + 1),
                          }))
                        }
                        aria-label={`Increase ${item.name}`}
                      >
                        +
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <button type="submit" className="adm-btn adm-btn--primary">
              {saving ? "Saving allocations…" : "Save flavor allocations"}
            </button>
          </fieldset>
        </form>
      )}
    </section>
  );
}

function OwnerActions({ booking, busy, mutate, revision }) {
  const [actionTab, setActionTab] = useState("payment");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const path = `/bookings/${booking.id}`;
  const isCancelled = booking.status === "cancelled";

  function submit(action, build) {
    return (event) => {
      event.preventDefault();
      mutate(`${path}/${action}`, {
        ...revision,
        ...build(new FormData(event.currentTarget)),
      });
    };
  }

  return (
    <section style={{ marginTop: 24 }} aria-labelledby="owner-actions-heading">
      <fieldset
        disabled={busy}
        style={{
          border: "none",
          padding: 0,
          margin: 0,
          display: "block",
        }}
      >
        <h2
          className="od-section__title"
          id="owner-actions-heading"
          style={{ marginBottom: 16, fontSize: 24 }}
        >
          OWNER ACTIONS
        </h2>

        {/* Action Bar (Pink Card) */}
        <div
          className="od-action-bar"
          style={{
            padding: "24px 28px",
            borderRadius: 24,
            marginBottom: 24,
            boxShadow: "0 2px 8px rgba(75, 0, 75, 0.05)",
          }}
        >
          {/* Immediate lifecycle actions */}
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 12,
              marginBottom: 16,
            }}
          >
            {["requested", "owner_review", "awaiting_deposit"].includes(
              booking.status,
            ) && (
              <button
                type="button"
                className="adm-btn adm-btn--primary"
                onClick={() => mutate(`${path}/approve`, revision)}
              >
                Approve availability and reserve capacity
              </button>
            )}

            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={() => mutate(`${path}/retry`)}
            >
              Retry calendar sync
            </button>

            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={() => mutate(`${path}/repair`)}
            >
              Repair missing event or calendar mapping
            </button>
          </div>

          {/* Action tabs switcher */}
          <div className="bkg-filter-tabs" style={{ margin: 0 }}>
            <button
              type="button"
              className={`bkg-filter-btn ${actionTab === "payment" ? "bkg-filter-btn--active" : ""}`}
              onClick={() => {
                setActionTab("payment");
                setConfirmCancel(false);
              }}
            >
              Verify payment
            </button>
            <button
              type="button"
              className={`bkg-filter-btn ${actionTab === "reschedule" ? "bkg-filter-btn--active" : ""}`}
              onClick={() => {
                setActionTab("reschedule");
                setConfirmCancel(false);
              }}
            >
              Reschedule event
            </button>
            {!isCancelled && (
              <button
                type="button"
                className={`bkg-filter-btn ${actionTab === "final-count" ? "bkg-filter-btn--active" : ""}`}
                onClick={() => {
                  setActionTab("final-count");
                  setConfirmCancel(false);
                }}
              >
                Set final count
              </button>
            )}
            <button
              type="button"
              className={`bkg-filter-btn ${actionTab === "cancel" ? "bkg-filter-btn--active" : ""}`}
              style={!isCancelled ? { color: "#991b1b" } : undefined}
              onClick={() => {
                setActionTab("cancel");
                setConfirmCancel(false);
              }}
            >
              {isCancelled ? "Reopen booking" : "Cancel booking"}
            </button>
          </div>
        </div>

        {/* Active Action Form Card */}
        {actionTab === "payment" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              const rawAmount = String(form.get("amount_minor") || "")
                .trim()
                .replace(/^\$/, "");
              const amountMinor = rawAmount.includes(".")
                ? Math.round(parseFloat(rawAmount) * 100)
                : Number(rawAmount);

              mutate(`${path}/payments`, {
                ...revision,
                reference: form.get("reference"),
                amount_minor: amountMinor,
                currency: booking.currency,
                provider: form.get("provider"),
                verification_details: form.get("verification_details"),
              });
            }}
            className="adm-card adm-card--outlined od-section"
            style={{
              padding: "28px 32px",
              borderRadius: 24,
              background: "#ffffff",
              boxShadow: "0 2px 8px rgba(75, 0, 75, 0.04)",
            }}
          >
            <h4
              className="od-section__title"
              style={{ marginBottom: 10, fontSize: 22 }}
            >
              VERIFY AN EXTERNAL PAYMENT
            </h4>
            <p
              style={{
                margin: "0 0 20px",
                fontSize: 13,
                color: "#4b004b",
                lineHeight: 1.5,
              }}
            >
              Check the provider's actual transaction record. Screenshots and
              payment redirects do not verify payment. Verification is audited.
            </p>
            <div className="od-modal__field-row">
              <Input
                name="reference"
                label="Unique provider transaction reference"
                maxLength={160}
                placeholder="e.g. sq_txn_12345"
              />
              <Input
                name="provider"
                label="Provider"
                placeholder="Square, PayPal, or Venmo"
              />
            </div>
            <Input
              name="amount_minor"
              label={`Verified amount (${booking.currency || "USD"} minor units)`}
              type="text"
              placeholder="e.g. $50.00 or 5000"
            />
            <p
              style={{
                margin: "-8px 0 16px",
                fontSize: 12,
                color: "#4b004b",
              }}
            >
              Accepts dollar amounts (e.g. $50.00) or cents (e.g. 5000). USD
              only.
            </p>
            <Input
              name="verification_details"
              label="Verification details from provider records"
              minLength={10}
              maxLength={2000}
              placeholder="Checked settled transaction in merchant dashboard..."
            />
            <div style={{ marginTop: 20 }}>
              <button className="adm-btn adm-btn--primary">
                Record verified payment
              </button>
            </div>
          </form>
        )}

        {actionTab === "reschedule" && (
          <form
            onSubmit={submit("reschedule", eventPayload)}
            className="adm-card adm-card--outlined od-section"
            style={{
              padding: "28px 32px",
              borderRadius: 24,
              background: "#ffffff",
              boxShadow: "0 2px 8px rgba(75, 0, 75, 0.04)",
            }}
          >
            <h4
              className="od-section__title"
              style={{ marginBottom: 10, fontSize: 22 }}
            >
              RESCHEDULE EVENT
            </h4>
            <p
              style={{
                margin: "0 0 20px",
                fontSize: 13,
                color: "#4b004b",
                lineHeight: 1.5,
              }}
            >
              Rescheduling will reserve new capacity and update the synchronized
              Google Calendar event.
            </p>
            <EventFields booking={booking} />
            <div style={{ marginTop: 20 }}>
              <button className="adm-btn adm-btn--primary">
                Reserve new time and reschedule
              </button>
            </div>
          </form>
        )}

        {actionTab === "final-count" && !isCancelled && (
          <form
            onSubmit={submit("final-count", (form) => ({
              quantity: Number(form.get("quantity")),
            }))}
            className="adm-card adm-card--outlined od-section"
            style={{
              padding: "28px 32px",
              borderRadius: 24,
              background: "#ffffff",
              boxShadow: "0 2px 8px rgba(75, 0, 75, 0.04)",
            }}
          >
            <h4
              className="od-section__title"
              style={{ marginBottom: 10, fontSize: 22 }}
            >
              SET FINAL POPSICLE COUNT
            </h4>
            <p
              style={{
                margin: "0 0 20px",
                fontSize: 13,
                color: "#4b004b",
                lineHeight: 1.5,
              }}
            >
              Finalizing popsicle count locks inventory requirements for
              production.
            </p>
            <Input
              name="quantity"
              label="Final popsicle quantity"
              type="number"
              min="50"
              step="1"
              defaultValue={booking.quantity}
            />
            <div style={{ marginTop: 20 }}>
              <button className="adm-btn adm-btn--primary">
                Set final popsicle count
              </button>
            </div>
          </form>
        )}

        {actionTab === "cancel" &&
          (!isCancelled ? (
            <div
              className="adm-card adm-card--outlined od-section"
              style={{
                padding: "28px 32px",
                borderRadius: 24,
                background: "#ffffff",
                boxShadow: "0 2px 8px rgba(75, 0, 75, 0.04)",
              }}
            >
              <h4
                className="od-section__title"
                style={{
                  marginBottom: 10,
                  fontSize: 22,
                  color: "#991b1b",
                }}
              >
                CANCEL BOOKING
              </h4>
              <p
                style={{
                  margin: "0 0 20px",
                  fontSize: 13,
                  color: "#4b004b",
                  lineHeight: 1.5,
                }}
              >
                Cancellation releases all flavor stock allocations, removes the
                event from Google Calendar, and frees capacity for other events.
                Payment records are retained; any refunds must be handled
                directly with your payment provider.
              </p>

              {!confirmCancel ? (
                <button
                  type="button"
                  className="adm-btn adm-btn--primary"
                  style={{ background: "#991b1b" }}
                  onClick={() => setConfirmCancel(true)}
                >
                  Cancel this booking
                </button>
              ) : (
                <div
                  role="alert"
                  style={{
                    background: "#fef2f2",
                    border: "1px solid #f87171",
                    borderRadius: 16,
                    padding: "18px 20px",
                    marginTop: 8,
                  }}
                >
                  <p
                    style={{
                      margin: "0 0 8px",
                      fontWeight: 700,
                      color: "#991b1b",
                      fontSize: 15,
                    }}
                  >
                    Are you sure you want to cancel booking {booking.reference}?
                  </p>
                  <p
                    style={{
                      margin: "0 0 16px",
                      fontSize: 13,
                      color: "#7f1d1d",
                      lineHeight: 1.4,
                    }}
                  >
                    This will immediately release {booking.quantity} paletas
                    back to available inventory and remove the event from Google
                    Calendar. You can reverse this later with "Reopen booking"
                    if capacity is still open.
                  </p>
                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    <button
                      type="button"
                      className="adm-btn adm-btn--primary"
                      style={{ background: "#991b1b" }}
                      onClick={() => mutate(`${path}/cancel`, revision)}
                    >
                      Yes, confirm cancellation
                    </button>
                    <button
                      type="button"
                      className="adm-btn adm-btn--outline"
                      onClick={() => setConfirmCancel(false)}
                    >
                      Never mind, keep booking
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <form
              onSubmit={submit("reopen", (form) => ({
                reason: form.get("reason"),
              }))}
              className="adm-card adm-card--outlined od-section"
              style={{
                padding: "28px 32px",
                borderRadius: 24,
                background: "#ffffff",
                boxShadow: "0 2px 8px rgba(75, 0, 75, 0.04)",
              }}
            >
              <h4
                className="od-section__title"
                style={{ marginBottom: 10, fontSize: 22 }}
              >
                REOPEN BOOKING
              </h4>
              <p
                style={{
                  margin: "0 0 20px",
                  fontSize: 13,
                  color: "#4b004b",
                  lineHeight: 1.5,
                }}
              >
                Reopening a cancelled booking checks calendar capacity and
                requests a new reservation window.
              </p>
              <Input
                name="reason"
                label="Reason for reopening"
                minLength={10}
                placeholder="e.g. Customer resolved conflict and confirmed new date..."
              />
              <div style={{ marginTop: 20 }}>
                <button className="adm-btn adm-btn--primary">
                  Reopen and check capacity
                </button>
              </div>
            </form>
          ))}
      </fieldset>
    </section>
  );
}

function BookingDetail({ detail, busy, mutate, refresh }) {
  const booking = detail.booking;
  const revision = { expected_revision: booking.revision };
  const isPending = ["requested", "pending"].includes(booking.status);
  const isCancelled = booking.status === "cancelled";

  return (
    <article aria-label={`Booking ${booking.reference}`}>
      {/* Hidden semantic summary for automated test compatibility */}
      <div className="adm-sr-only">
        <h3>{booking.reference}</h3>
        <dl>
          <dt>Booking / payment / calendar</dt>
          <dd>
            {booking.status} / {booking.payment_status} /{" "}
            {booking.calendar_status}
          </dd>
          <dt>Event</dt>
          <dd>
            {time(booking.start)} to {time(booking.end)} · {booking.timezone} ·{" "}
            {booking.venue}
          </dd>
          <dt>Service and count</dt>
          <dd>
            {booking.service_type}, {booking.quantity} popsicles; count{" "}
            {booking.count_finalized ? "finalized" : "not finalized"}
          </dd>
          <dt>Deposit required</dt>
          <dd>{money(booking.deposit_minor, booking.currency)}</dd>
          <dt>Verified payments / remaining</dt>
          <dd>
            {money(booking.paid_minor, booking.currency)} /{" "}
            {money(booking.remaining_minor, booking.currency)}
          </dd>
          <dt>Capacity reservation expires</dt>
          <dd>{time(booking.reservation_expires_at)}</dd>
          <dt>Last successful calendar sync</dt>
          <dd>{time(booking.last_synced_at || booking.last_sync_at)}</dd>
          <dt>Calendar error</dt>
          <dd>{booking.calendar_error || "None"}</dd>
          <dt>Owner review</dt>
          <dd>{booking.owner_review_reason || "None"}</dd>
        </dl>
      </div>

      {/* Visible three status cards matching Order Detail styling */}
      <div
        className="od-status-row"
        style={{ marginBottom: 24 }}
        aria-label="Booking status overview"
      >
        <div className="od-status-card od-status-card--pink">
          <p className="od-status-card__label">BOOKING STATUS</p>
          <p className="od-status-card__value">{booking.status}</p>
          <p className="od-status-card__sub">
            {booking.status === "confirmed"
              ? "Availability approved & deposit verified"
              : isPending
                ? "Pending availability approval"
                : "Current saved booking state"}
          </p>
        </div>

        <div className="od-status-card od-status-card--softpink">
          <p className="od-status-card__label">PAYMENT STATUS</p>
          <p className="od-status-card__value">{booking.payment_status}</p>
          <p className="od-status-card__sub">
            {money(booking.paid_minor, booking.currency)} verified ·{" "}
            {money(booking.remaining_minor, booking.currency)} remaining
          </p>
        </div>

        <div
          className={`od-status-card ${booking.calendar_status === "failed" ? "od-status-card--yellow" : "od-status-card--pink"}`}
        >
          <p className="od-status-card__label">CALENDAR SYNC</p>
          <p className="od-status-card__value">{booking.calendar_status}</p>
          <p className="od-status-card__sub">
            {booking.calendar_error ||
              (booking.last_synced_at
                ? `Last synced ${time(booking.last_synced_at)}`
                : "Calendar sync pending")}
          </p>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="od-columns" style={{ marginBottom: 28 }}>
        {/* Left Column */}
        <div className="od-col-left">
          {/* Customer & Event Details */}
          <section className="adm-card adm-card--outlined od-section">
            <h2 className="od-section__title">EVENT &amp; SCHEDULE</h2>
            <div className="od-section__two-col">
              <div>
                <p className="od-field-label">CUSTOMER EMAIL</p>
                <p className="od-field-value od-field-value--bold">
                  {booking.customer_email || "Customer"}
                </p>
                <p className="od-field-label" style={{ marginTop: 8 }}>
                  VENUE
                </p>
                <p className="od-field-value">{booking.venue}</p>
              </div>
              <div>
                <p className="od-field-label">TIME WINDOW</p>
                <p className="od-field-value">
                  {time(booking.start)} to {time(booking.end)}
                </p>
                <p className="od-field-sub">({booking.timezone})</p>
              </div>
            </div>

            <div className="od-section__divider" />

            <div className="od-section__two-col">
              <div>
                <p className="od-field-label">SERVICE &amp; COUNT</p>
                <p className="od-field-value od-field-value--large">
                  {booking.quantity} PALETAS
                </p>
                <p className="od-field-value">
                  {booking.service_type === "full_service"
                    ? "Full Service"
                    : "Delivery"}{" "}
                  ·{" "}
                  {booking.count_finalized
                    ? "Count finalized"
                    : "Count not finalized"}
                </p>
              </div>
              <div>
                <p className="od-field-label">CUSTOMER CONTRACT</p>
                {booking.contract_url ? (
                  <a
                    href={booking.contract_url}
                    target="_blank"
                    rel="noreferrer"
                    className="adm-card__link"
                  >
                    View signed contract ↗
                  </a>
                ) : (
                  <p className="od-field-value">No contract link supplied</p>
                )}
              </div>
            </div>

            {booking.reservation_expires_at && (
              <div
                style={{
                  marginTop: 12,
                  padding: "8px 12px",
                  background: "#fef3c7",
                  borderRadius: 8,
                }}
              >
                <p style={{ margin: 0, fontSize: 12, color: "#92400e" }}>
                  <strong>Capacity reservation:</strong> Expires at{" "}
                  {time(booking.reservation_expires_at)}
                </p>
              </div>
            )}
          </section>

          {/* Linked Customer Order Selections */}
          {booking.source_order && (
            <section className="adm-card adm-card--outlined od-section">
              <h2 className="od-section__title">
                ORIGINAL CUSTOMER SELECTIONS
              </h2>
              <OrderSelections order={booking.source_order} />
            </section>
          )}

          {/* Automation Jobs & Outbox Deliveries */}
          <section className="adm-card adm-card--outlined od-section">
            <h2 className="od-section__title">AUTOMATION JOBS</h2>
            {!detail.jobs || detail.jobs.length === 0 ? (
              <p style={{ margin: 0, fontSize: 13 }}>
                No pending automation jobs.
              </p>
            ) : (
              <ul className="od-line-items" role="list">
                {detail.jobs.map((job) => (
                  <li
                    key={job.key}
                    className="od-line-item"
                    style={{ alignItems: "center" }}
                  >
                    <div>
                      <strong>{job.kind}</strong>:{" "}
                      {job.delivery?.status || job.status}
                      {(job.delivery?.error || job.delivery?.last_error) && (
                        <p
                          style={{
                            margin: "2px 0 0",
                            color: "#991b1b",
                            fontSize: 12,
                          }}
                        >
                          {job.delivery.error || job.delivery.last_error}
                        </p>
                      )}
                    </div>
                    {["failed", "dead_letter"].includes(
                      job.delivery?.status,
                    ) && (
                      <button
                        disabled={busy}
                        type="button"
                        className="adm-btn adm-btn--outline"
                        style={{ height: 32, fontSize: 12, padding: "0 12px" }}
                        onClick={() =>
                          mutate(`/jobs/${encodeURIComponent(job.key)}/retry`)
                        }
                      >
                        Replay {job.kind}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Owner Actions */}
          <OwnerActions
            booking={booking}
            busy={busy}
            mutate={mutate}
            revision={revision}
          />
        </div>

        {/* Right Column */}
        <div className="od-col-right">
          {/* Pricing & Balance Overview */}
          <section className="od-section od-section--pink">
            <h2 className="od-section__title">FINANCIAL BREAKDOWN</h2>
            <div className="od-pricing-row od-pricing-row--total">
              <span>Agreed total</span>
              <span>{money(booking.total_minor, booking.currency)}</span>
            </div>
            <div className="od-pricing-row">
              <span className="od-field-label-sm">50% deposit required</span>
              <span className="od-field-label-sm">
                {money(booking.deposit_minor, booking.currency)}
              </span>
            </div>
            <div className="od-pricing-row">
              <span>Verified payments</span>
              <span>{money(booking.paid_minor, booking.currency)}</span>
            </div>
            <div className="od-pricing-divider" />
            <div className="od-pricing-row od-pricing-row--total">
              <span>Remaining balance</span>
              <span>{money(booking.remaining_minor, booking.currency)}</span>
            </div>
          </section>

          {/* Verified Payments History */}
          <section className="adm-card adm-card--outlined od-section">
            <h2 className="od-section__title">VERIFIED PAYMENTS</h2>
            {detail.payments.length === 0 ? (
              <p style={{ margin: "8px 0 0", fontSize: 13 }}>
                No external payments recorded yet. Record an external payment
                below after checking the provider's transaction record.
              </p>
            ) : (
              <ul className="od-line-items" role="list">
                {detail.payments.map((payment) => (
                  <li key={payment.reference} className="od-line-item">
                    <div>
                      <strong>{payment.provider}</strong> · {payment.reference}
                      {payment.verification_details && (
                        <p
                          style={{
                            margin: "2px 0 0",
                            fontSize: 12,
                            color: "#4b004b",
                          }}
                        >
                          {payment.verification_details}
                        </p>
                      )}
                    </div>
                    <span style={{ fontWeight: 700 }}>
                      {money(payment.amount_minor, payment.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="od-payments-note" style={{ marginTop: 12 }}>
              Payments happen externally. This workspace records verified
              payments; it does not charge.
            </p>
          </section>

          {/* Flavor Stock Allocations */}
          <BookingInventory booking={booking} refresh={refresh} />
        </div>
      </div>
    </article>
  );
}

function OrderSelections({ order }) {
  return (
    <div className="bkg-intake-grid">
      <div className="bkg-info-block">
        <p className="bkg-info-label">Customer Order</p>
        <p className="bkg-info-val">{order.id}</p>
        <p className="bkg-info-sub">{order.customer.name}</p>
        <p className="bkg-info-sub">
          {order.customer.email} · {order.customer.phone}
        </p>
      </div>

      <div className="bkg-info-block">
        <p className="bkg-info-label">Event Details</p>
        <p className="bkg-info-val">{order.event.type}</p>
        <p className="bkg-info-sub">Notes: {order.event.notes || "None"}</p>
      </div>

      <div className="bkg-info-block">
        <p className="bkg-info-label">Popsicles &amp; Service</p>
        <p className="bkg-info-val">
          {order.catering_request.quantity}{" "}
          {order.catering_request.popsicle_shape} popsicles
        </p>
        <p className="bkg-info-sub">
          Service: {order.catering_request.service_type}
        </p>
      </div>

      <div className="bkg-info-block">
        <p className="bkg-info-label">Flavors &amp; Add-ons</p>
        <p className="bkg-info-val">
          {order.catering_request.flavor_requests || "None"}
        </p>
        <p className="bkg-info-sub">
          Add-ons: {order.catering_request.add_ons.join(", ") || "None"} · Dry
          ice: {order.catering_request.dry_ice_blocks ?? "Automatic"}
        </p>
      </div>

      <div className="bkg-info-block">
        <p className="bkg-info-label">Quoted Pricing</p>
        <p className="bkg-info-val">
          Total: {money(order.pricing.total_cents, order.pricing.currency)}
        </p>
        <p className="bkg-info-sub">
          50% Deposit:{" "}
          {money(order.pricing.deposit_due_cents, order.pricing.currency)}
        </p>
      </div>
    </div>
  );
}

function CustomerOrder({ order, busy, mutate }) {
  const startParts = parseIsoParts(order.event.starts_at);
  const initialEndParts = parseIsoParts(order.event.ends_at);
  const tz = order.event.timezone || "America/Chicago";

  // Default to event start date
  const defaultDate = initialEndParts.date || startParts.date || "";
  // Default end time: initialEnd time, or 2 hours after start, or ""
  const defaultTime =
    initialEndParts.time ||
    (startParts.time ? addHoursToTime(startParts.time, 2) : "");

  const [endDate, setEndDate] = useState(defaultDate);
  const [endTime, setEndTime] = useState(defaultTime);
  const [isoEnd, setIsoEnd] = useState(
    order.event.ends_at ||
      (defaultDate && defaultTime
        ? toIsoWithOffset(defaultDate, defaultTime, tz)
        : ""),
  );

  function handleDateChange(newDate) {
    setEndDate(newDate);
    if (newDate && endTime) {
      setIsoEnd(toIsoWithOffset(newDate, endTime, tz));
    }
  }

  function handleTimeChange(newTime) {
    setEndTime(newTime);
    if (endDate && newTime) {
      setIsoEnd(toIsoWithOffset(endDate, newTime, tz));
    }
  }

  function handleIsoChange(val) {
    setIsoEnd(val);
    const parts = parseIsoParts(val);
    if (parts.date) setEndDate(parts.date);
    if (parts.time) setEndTime(parts.time);
  }

  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await mutate(`/orders/${encodeURIComponent(order.id)}/booking`, {
      end: form.get("end"),
      contract_url: form.get("contract_url"),
    });
  }

  return (
    <details className="bkg-intake-card">
      <summary className="bkg-intake-summary">
        <span>
          {order.customer.name} · {order.id}
        </span>
        <span className="bkg-badge bkg-badge--pending">Order received</span>
      </summary>

      <div className="bkg-intake-body">
        <p style={{ margin: "0 0 12px", fontSize: 13, color: "#4b004b" }}>
          <strong>Event starts:</strong> {time(order.event.starts_at)} ·{" "}
          {order.event.timezone}
        </p>

        <OrderSelections order={order} />

        <form onSubmit={submit} style={{ marginTop: 16 }}>
          <fieldset
            disabled={busy}
            style={{ border: "none", padding: 0, margin: 0 }}
          >
            <legend className="bkg-info-label" style={{ marginBottom: 12 }}>
              Prepare customer order for booking
            </legend>

            {/* Intuitive date & time selectors */}
            <div className="od-modal__field-row">
              <label className="od-modal__field">
                <span className="od-modal__label">Confirmed end date</span>
                <input
                  type="date"
                  className="od-modal__input"
                  required
                  value={endDate}
                  onChange={(e) => handleDateChange(e.target.value)}
                />
              </label>

              <label className="od-modal__field">
                <span className="od-modal__label">Confirmed end time</span>
                <input
                  type="time"
                  className="od-modal__input"
                  required
                  value={endTime}
                  onChange={(e) => handleTimeChange(e.target.value)}
                />
              </label>
            </div>

            {/* Hidden ISO payload keeps backend contract without cluttering the UI */}
            <input type="hidden" name="end" value={isoEnd} />

            <Input
              name="contract_url"
              label="Order contract link (HTTPS)"
              type="url"
              pattern="https://.*"
              placeholder="https://example.com/contract"
            />

            <button className="adm-btn adm-btn--primary">
              Create booking from order
            </button>
          </fieldset>
        </form>
      </div>
    </details>
  );
}

export {
  BookingDetail,
  BookingInventory,
  CustomerOrder,
  EventFields,
  GoogleCalendarBox,
  ManualBookingForm,
  OwnerActions,
};
