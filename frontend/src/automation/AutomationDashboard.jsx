import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest, errorMessage, navigateToProvider } from "../auth/api.js";
import { formatFlavorRequests } from "../flavors.js";
import {
  fetchInventory,
  fetchBookingAllocations,
  saveBookingAllocations,
} from "../admin/adminApi.js";

import {
  centralTimeToIso,
  centralInputValue,
  EVENT_TIME_ZONE,
  formatEventTime,
} from "../eventTime.js";
import { OrderDecisionControls } from "../admin/OrderDecisionControls.jsx";
import { EventEndSelect } from "../admin/EventEndSelect.jsx";
import { SquareCheckoutControls } from "../payments/SquareCheckoutControls.jsx";
import "../admin/order-detail.css";

const base = "/admin/automation";
const money = (value, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    value / 100,
  );
const time = (value) =>
  value
    ? formatEventTime(typeof value === "number" ? value * 1000 : value)
    : "Never";

function Input({ name, label, type = "text", ...props }) {
  return (
    <label>
      {label}
      <input name={name} type={type} required {...props} />
    </label>
  );
}

function eventPayload(form) {
  return {
    start: centralTimeToIso(form.get("start")),
    end: centralTimeToIso(form.get("end")),
    timezone: EVENT_TIME_ZONE,
    venue: form.get("venue"),
  };
}

function EventFields({ booking = {} }) {
  return (
    <>
      <div className="adm-inline-fields">
        <Input
          name="start"
          label="Event start (Houston/Central time)"
          type="datetime-local"
          defaultValue={centralInputValue(booking.start)}
        />
        <Input
          name="end"
          label="Event end (Houston/Central time)"
          type="datetime-local"
          defaultValue={centralInputValue(booking.end)}
        />
      </div>
      <p className="adm-field-hint">
        All event times use Houston/Central time.
      </p>
      <Input
        name="venue"
        label="Venue"
        maxLength={500}
        defaultValue={booking.venue}
      />
    </>
  );
}

export function AutomationDashboard({ identity, csrfToken }) {
  const { bookingId } = useParams();
  const [items, setItems] = useState([]);
  const [orders, setOrders] = useState([]);
  const [ordersError, setOrdersError] = useState("");
  const [notifications, setNotifications] = useState(null);
  const [notificationsError, setNotificationsError] = useState("");
  const [connection, setConnection] = useState(null);
  const [connectionLoading, setConnectionLoading] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
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
    const [bookings, google, selected, intake, requests] =
      await Promise.allSettled([
        apiRequest(`${base}/bookings`),
        apiRequest(`${base}/google`),
        bookingId
          ? apiRequest(`${base}/bookings/${encodeURIComponent(bookingId)}`)
          : Promise.resolve(null),
        apiRequest(`${base}/orders`),
        apiRequest(`${base}/requests`),
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
    setNotifications(requests.status === "fulfilled" ? requests.value : null);
    setNotificationsError(
      requests.status === "rejected" ? explain(requests.reason) : "",
    );
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
    let schedule;
    try {
      schedule = eventPayload(form);
    } catch (failure) {
      setError(failure.message);
      return;
    }
    const ok = await mutate("/bookings", {
      ...schedule,
      quantity: Number(form.get("quantity")),
      total_minor: Number(form.get("total_minor")),
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

  if (bookingId) {
    return (
      <section className="automation-dashboard automation-dashboard--detail">
        <div className="adm-booking-detail-view-header">
          <h2>Catering automation</h2>
        </div>

        {error && <p role="alert">{error}</p>}
        {!loaded && <p role="status">Loading booking details…</p>}

        {detail ? (
          <BookingDetail
            key={`${detail.booking.id}:${detail.booking.revision}`}
            detail={detail}
            busy={busy}
            mutate={mutate}
            refresh={refresh}
            connection={connection}
            connectionLoading={connectionLoading}
            connectionError={connectionError}
          />
        ) : loaded && !error ? (
          <div className="adm-empty-state">
            <p className="adm-empty-state__title">Booking not found.</p>
            <p className="adm-empty-state__sub">
              This booking may have been removed or the ID is invalid.
            </p>
            <Link to="/admin/automation" className="adm-btn adm-btn--outline">
              ← Back to all bookings
            </Link>
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section className="automation-dashboard">
      <h2>Catering automation</h2>
      <p>
        <Link to="/admin/automation">All bookings</Link> ·{" "}
        <Link to="/admin/login?reauth=1">Verify owner access again</Link>
      </p>
      <p>
        Approve availability and reserve capacity before requesting a deposit. A
        verified 50% deposit confirms the booking.
      </p>
      {error && <p role="alert">{error}</p>}
      {!loaded && <p role="status">Loading bookings…</p>}

      <section aria-labelledby="customer-intake-heading">
        <h3 id="customer-intake-heading">Customer order intake</h3>
        <p>
          Review submitted orders and confirm the event end time. You can
          include a contract link if available. Creating a booking keeps the
          customer's saved selections and price. Approve availability
          separately.
        </p>
        {ordersError && (
          <p role="alert">Could not load customer orders. {ordersError}</p>
        )}
        {loaded && !ordersError && !orders.length && (
          <div className="adm-empty-state">
            <p className="adm-empty-state__title">
              No customer orders awaiting intake.
            </p>
            <p className="adm-empty-state__sub">
              Submitted customer orders ready for date confirmation will appear
              here.
            </p>
          </div>
        )}
        {orders.map((order) => (
          <CustomerOrder
            key={order.id}
            order={order}
            busy={busy}
            mutate={mutate}
          />
        ))}
      </section>

      <fieldset disabled={busy} className="adm-notifications-fieldset">
        <legend>Incoming request notifications</legend>
        <p>
          Email each new submitted request to your business inbox and add a
          non-blocking Pending entry to the connected calendar. Quote previews
          are excluded. Approval and a verified deposit confirm the booking.
          Enabling starts with future submissions.
        </p>
        {notificationsError && (
          <p>Could not load request notifications. {notificationsError}</p>
        )}
        {notifications && (
          <>
            {notifications.email_mode === "simulated" && (
              <p>Email delivery is simulated in this local preview.</p>
            )}
            <p role="status">
              {notifications.enabled
                ? `Enabled for ${notifications.recipient}`
                : "Request notifications are not enabled."}
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const form = new FormData(event.currentTarget);
                mutate("/requests", {
                  recipient: form.get("recipient"),
                  enabled: true,
                });
              }}
            >
              <label htmlFor="request-notification-email">
                Notification email
              </label>
              <input
                id="request-notification-email"
                name="recipient"
                type="email"
                required
                maxLength={254}
                defaultValue={notifications.recipient || ""}
              />
              <button
                type="submit"
                disabled={
                  connectionLoading || connection?.status !== "connected"
                }
              >
                Use this calendar for incoming requests
              </button>
            </form>
            {notifications.enabled && (
              <button
                type="button"
                onClick={() => mutate("/requests", { enabled: false })}
              >
                Stop new request notifications
              </button>
            )}
            {notifications.calendar_id && (
              <p>Request calendar: {notifications.calendar_id}</p>
            )}
            <ul aria-label="Recent request notifications">
              {(notifications.requests || []).map((item) => (
                <li key={item.order_id}>
                  <Link
                    to={`/admin/orders/${encodeURIComponent(item.order_id)}`}
                  >
                    {item.order_id}
                  </Link>
                  {` · Email: ${item.email_status} · Calendar: ${item.calendar_status}`}
                  {item.email_error && <p>{item.email_error}</p>}
                  {item.calendar_error && <p>{item.calendar_error}</p>}
                  {["failed", "dead_letter"].includes(item.email_status) && (
                    <button
                      type="button"
                      onClick={() =>
                        mutate(
                          `/jobs/${encodeURIComponent(item.email_job)}/retry`,
                        )
                      }
                    >
                      Retry request email
                    </button>
                  )}
                  {!["synced", "booking"].includes(item.calendar_status) && (
                    <button
                      type="button"
                      onClick={() =>
                        mutate(
                          `/requests/${encodeURIComponent(item.order_id)}/retry`,
                        )
                      }
                    >
                      Retry request calendar
                    </button>
                  )}
                  {item.calendar_status === "repair_required" && (
                    <button
                      type="button"
                      onClick={() =>
                        mutate(
                          `/requests/${encodeURIComponent(item.order_id)}/retry`,
                          { repair: true },
                        )
                      }
                    >
                      Repair request calendar event
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </fieldset>

      <div
        className="table-scroll adm-table-wrap"
        role="region"
        aria-label="Catering bookings"
        tabIndex={0}
      >
        <table className="adm-orders-table">
          <caption>Catering bookings</caption>
          <thead>
            <tr>
              <th scope="col">Customer</th>
              <th scope="col">Reference</th>
              <th scope="col">Booking</th>
              <th scope="col">Payment</th>
              <th scope="col" className="adm-orders-table__col-qty">
                Remaining
              </th>
              <th scope="col">Calendar</th>
            </tr>
          </thead>
          <tbody>
            {items.map((booking) => (
              <tr key={booking.id}>
                <td className="adm-orders-table__customer">
                  {booking.source_order?.customer?.name ||
                    booking.customer_email ||
                    "Customer"}
                </td>
                <th scope="row">
                  <Link
                    to={`/admin/bookings/${booking.id}`}
                    className="adm-card__link"
                  >
                    {booking.reference}
                  </Link>
                </th>
                <td>
                  <span className={`adm-status adm-status--${booking.status}`}>
                    {booking.status}
                  </span>
                </td>
                <td>
                  <span
                    className={`adm-status adm-status--payment-${booking.payment_status}`}
                  >
                    {booking.payment_status.replaceAll("_", " ")}
                  </span>
                </td>
                <td className="adm-orders-table__col-qty">
                  {money(booking.remaining_minor, booking.currency)}
                </td>
                <td>
                  <span
                    className={`adm-status adm-status--calendar-${booking.calendar_status}`}
                  >
                    {booking.calendar_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loaded && !error && !items.length && (
          <div className="adm-empty-state">
            <p className="adm-empty-state__title">No bookings yet.</p>
            <p className="adm-empty-state__sub">
              New customer bookings and approved catering requests will appear
              here.
            </p>
          </div>
        )}
      </div>

      <details className="adm-add-booking-details">
        <summary>Add a catering booking</summary>
        <form onSubmit={create}>
          <fieldset disabled={busy}>
            <legend>Agreed order</legend>
            <EventFields />
            <Input
              name="quantity"
              label="Popsicle quantity"
              type="number"
              min="50"
              step="1"
            />
            <label>
              Service type
              <select name="service_type">
                <option value="delivery">Delivery</option>
                <option value="full_service">Full service</option>
              </select>
            </label>
            <Input name="customer_email" label="Customer email" type="email" />
            <Input
              name="total_minor"
              label="Agreed total in minor units (USD cents)"
              type="number"
              min="1"
              step="1"
            />
            <Input
              name="currency"
              label="Currency (ISO code)"
              defaultValue="USD"
              pattern="[A-Z]{3}"
            />
            <Input
              name="contract_url"
              label="Customer contract link (optional, HTTPS)"
              type="url"
              required={false}
              pattern="https://.*"
              placeholder="https://example.com/contract"
            />
            <button>Create booking request</button>
          </fieldset>
        </form>
      </details>

      <fieldset disabled={busy}>
        <legend>Google Calendar connection</legend>
        <p role={connectionLoading ? "status" : undefined}>
          Connection:{" "}
          {connectionLoading ? "Loading…" : connection?.status || "Unavailable"}
        </p>
        {connectionError && <p role="alert">{connectionError}</p>}
        {connection?.setup_message && <p>{connection.setup_message}</p>}
        {connection?.calendar_id && <p>Calendar: {connection.calendar_id}</p>}
        {connection?.last_error && <p>{connection.last_error}</p>}
        <div className="actions">
          <button
            type="button"
            disabled={
              busy ||
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
            disabled={
              busy ||
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
            disabled={busy || connectionLoading}
            onClick={refresh}
          >
            Refresh status
          </button>
        </div>
      </fieldset>
    </section>
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
      <section>
        <h4>Flavor stock allocations</h4>
        <p>
          Confirm the booking before assigning flavor stock. Cancellation
          releases its allocations.
        </p>
      </section>
    );
  return (
    <section aria-label="Flavor stock allocations">
      <h4>Flavor stock allocations</h4>
      <p>
        Assign specific flavors to this confirmed booking. Free-text flavor
        requests do not reserve inventory.
      </p>
      {error && (
        <p role="alert">
          {error}{" "}
          <button type="button" onClick={refresh}>
            Refresh booking
          </button>
        </p>
      )}
      {catalog === null && !error && (
        <p role="status">Loading stock allocations…</p>
      )}
      {catalog && (
        <form onSubmit={save}>
          <fieldset disabled={saving}>
            <legend>Reserved flavors for {booking.quantity} paletas</legend>
            {catalog.length === 0 && (
              <p>
                No inventory items yet.{" "}
                <Link to="/admin/inventory">Add inventory</Link>.
              </p>
            )}
            {catalog.map((item) => (
              <label key={item.id}>
                {item.name} · {item.available} available
                <input
                  type="number"
                  min="0"
                  step="1"
                  max={booking.quantity}
                  value={quantities[item.id] || ""}
                  onChange={(event) =>
                    setQuantities((current) => ({
                      ...current,
                      [item.id]: event.target.value,
                    }))
                  }
                  aria-label={`Reserve ${item.name}`}
                />
              </label>
            ))}
            <button type="submit">
              {saving ? "Saving allocations…" : "Save flavor allocations"}
            </button>
          </fieldset>
        </form>
      )}
    </section>
  );
}

const BOOKING_ACTION_TABS = [
  { id: "all", label: "All" },
  { id: "decision", label: "Review Request" },
  { id: "payments", label: "Payments & Square" },
  { id: "flavors", label: "Flavor Stock" },
  { id: "calendar", label: "Google Calendar" },
  { id: "manage", label: "Manage Booking" },
  { id: "jobs", label: "Automation Jobs" },
];

function BookingDetail({
  detail,
  busy,
  mutate,
  refresh,
  connection,
  connectionLoading,
  connectionError,
}) {
  const [formError, setFormError] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [rescheduleOpen, setRescheduleOpen] = useState(false);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const booking = detail.booking;
  const path = `/bookings/${booking.id}`;
  const revision = { expected_revision: booking.revision };
  function submit(action, build) {
    return (event) => {
      event.preventDefault();
      setFormError("");
      try {
        mutate(`${path}/${action}`, {
          ...revision,
          ...build(new FormData(event.currentTarget)),
        });
      } catch (failure) {
        setFormError(failure.message);
      }
    };
  }
  return (
    <article
      aria-label={`Booking ${booking.reference}`}
      className="adm-booking-detail-card"
    >
      {/* Heading & customer info row */}
      <div className="od-heading-row" style={{ marginBottom: "16px" }}>
        <div>
          <h3
            className="od-heading"
            style={{ fontSize: "28px", lineHeight: "1.2" }}
          >
            {(
              booking.source_order?.customer?.name ||
              booking.customer_email ||
              booking.reference ||
              "Booking"
            ).toUpperCase()}{" "}
            ·{" "}
            <span style={{ color: "var(--adm-purple)" }}>
              {booking.reference}
            </span>
          </h3>
          {booking.source_order?.customer?.email && (
            <p className="od-created">
              {booking.source_order.customer.email} ·{" "}
              {booking.source_order.customer.phone}
            </p>
          )}
        </div>
      </div>

      {/* 3 Status Cards row matching Order Details */}
      <div
        className="od-status-row"
        aria-label="Booking status overview"
        style={{ marginBottom: "20px" }}
      >
        <div className="od-status-card od-status-card--pink">
          <p className="od-status-card__label">BOOKING STATUS</p>
          <p className="od-status-card__value">
            {booking.status === "awaiting_deposit"
              ? "AWAITING DEPOSIT"
              : booking.status?.replace("_", " ")?.toUpperCase()}
          </p>
          <p className="od-status-card__sub">
            {booking.quantity} paletas · {booking.service_type}
          </p>
        </div>
        <div className="od-status-card od-status-card--softpink">
          <p className="od-status-card__label">PAYMENT STATUS</p>
          <p className="od-status-card__value">
            {booking.payment_status?.replace("_", " ")?.toUpperCase()}
          </p>
          <p className="od-status-card__sub">
            {money(booking.paid_minor, booking.currency)} paid /{" "}
            {money(booking.remaining_minor, booking.currency)} remaining
          </p>
        </div>
        <div
          className={`od-status-card od-status-card--${
            booking.calendar_status === "synced" ? "pink" : "yellow"
          }`}
        >
          <p className="od-status-card__label">CALENDAR SYNC STATUS</p>
          <p className="od-status-card__value">
            {booking.calendar_status?.replace("_", " ")?.toUpperCase()}
          </p>
          <p className="od-status-card__sub">
            {booking.last_synced_at || booking.last_sync_at
              ? `Synced ${time(booking.last_synced_at || booking.last_sync_at)}`
              : "Pending initial sync"}
          </p>
        </div>
      </div>

      {/* Two-column layout matching Order Details */}
      <div className="od-columns">
        {/* Left column */}
        <div className="od-col-left">
          {/* Customer & Event */}
          <section
            className="adm-card adm-card--outlined od-section"
            aria-labelledby="bk-customer-heading"
          >
            <h2 className="od-section__title" id="bk-customer-heading">
              CUSTOMER &amp; EVENT
            </h2>
            <div className="od-section__two-col">
              <div>
                <p className="od-field-value od-field-value--bold">
                  {booking.source_order?.customer?.name ||
                    booking.customer_email ||
                    "Customer"}
                </p>
                {booking.source_order?.customer?.email && (
                  <>
                    <p className="od-field-value">
                      {booking.source_order.customer.email}
                    </p>
                    <p className="od-field-value">
                      {booking.source_order.customer.phone}
                    </p>
                  </>
                )}
                <div style={{ marginTop: "14px" }}>
                  <p className="od-field-label">EVENT LOCATION</p>
                  <p className="od-field-value">
                    {booking.venue || "Venue not specified"}
                  </p>
                </div>
              </div>
              <div>
                <p className="od-field-label">
                  {(booking.service_type || "Catering").toUpperCase()}
                </p>
                <p className="od-field-value">
                  {time(booking.start)} to {time(booking.end)}
                </p>
                <p className="od-field-value">Time zone: {booking.timezone}</p>
                {booking.source_order?.event && (
                  <div style={{ marginTop: "14px" }}>
                    <p className="od-field-label">EVENT TYPE &amp; NOTES</p>
                    <p className="od-field-value">
                      {booking.source_order.event.type} ·{" "}
                      {booking.source_order.event.notes || "None"}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* The Paleta Plan */}
          <section
            className="od-section od-section--softpink"
            aria-labelledby="bk-paleta-heading"
          >
            <h2 className="od-section__title" id="bk-paleta-heading">
              THE PALETA PLAN
            </h2>
            <div className="od-section__two-col">
              <div>
                <p className="od-field-value od-field-value--large">
                  {booking.quantity} PALETAS
                </p>
                <p className="od-field-value">
                  {formatFlavorRequests(
                    booking.source_order?.catering_request,
                  ) || "Standard flavor selection"}
                </p>
              </div>
              <div>
                <p className="od-field-label">SHAPE &amp; PREPARATION</p>
                <p className="od-field-value">
                  {booking.source_order?.catering_request?.popsicle_shape ||
                    "standard"}{" "}
                  popsicles · {booking.service_type}
                </p>
                <p className="od-field-value">
                  Count{" "}
                  {booking.count_finalized ? "finalized" : "not finalized"}
                </p>
              </div>
            </div>
            <div className="od-section__two-col" style={{ marginTop: "12px" }}>
              <div>
                <p className="od-field-label">ADD-ONS</p>
                <p className="od-field-value">
                  {booking.source_order?.catering_request?.add_ons?.join(
                    ", ",
                  ) || "None"}
                </p>
              </div>
              <div>
                <p className="od-field-label">DRY ICE BLOCKS</p>
                <p className="od-field-value">
                  {booking.source_order?.catering_request?.dry_ice_blocks ??
                    "Automatic"}
                </p>
              </div>
            </div>
          </section>

          {/* Special alerts / instructions if any */}
          {(booking.calendar_error || booking.owner_review_reason) && (
            <section
              className="adm-card adm-card--outlined od-section"
              aria-labelledby="bk-alerts-heading"
              style={{ borderColor: "#f8b4b4", background: "#fdf2f2" }}
            >
              <h2
                className="od-section__title"
                id="bk-alerts-heading"
                style={{ color: "#9b1c1c", fontSize: "16px" }}
              >
                ATTENTION REQUIRED
              </h2>
              {booking.calendar_error && (
                <div style={{ marginTop: "8px" }}>
                  <p className="od-field-label" style={{ color: "#9b1c1c" }}>
                    CALENDAR ERROR
                  </p>
                  <p className="od-field-value" style={{ color: "#771d1d" }}>
                    {booking.calendar_error}
                  </p>
                </div>
              )}
              {booking.owner_review_reason && (
                <div style={{ marginTop: "8px" }}>
                  <p className="od-field-label" style={{ color: "#9b1c1c" }}>
                    OWNER REVIEW REASON
                  </p>
                  <p className="od-field-value" style={{ color: "#771d1d" }}>
                    {booking.owner_review_reason}
                  </p>
                </div>
              )}
            </section>
          )}
        </div>

        {/* Right column */}
        <div className="od-col-right">
          {/* Pricing */}
          <section
            className="od-section od-section--pink"
            aria-labelledby="bk-pricing-heading"
          >
            <h2 className="od-section__title" id="bk-pricing-heading">
              PRICING &amp; BALANCE
            </h2>
            {booking.source_order?.pricing && (
              <div className="od-pricing-row od-pricing-row--total">
                <span>Quoted total</span>
                <span>
                  {money(
                    booking.source_order.pricing.total_cents,
                    booking.source_order.pricing.currency,
                  )}
                </span>
              </div>
            )}
            <div className="od-pricing-row">
              <span className="od-field-label-sm">Required deposit</span>
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
            {booking.overpaid_minor > 0 && (
              <div
                className="od-pricing-row"
                style={{ color: "#9b1c1c", fontWeight: 700 }}
              >
                <span>Overpayment to review</span>
                <span>{money(booking.overpaid_minor, booking.currency)}</span>
              </div>
            )}
            {booking.reservation_expires_at && (
              <div
                className="od-pricing-row"
                style={{ fontSize: "12px", opacity: 0.85 }}
              >
                <span>Reservation expires</span>
                <span>{time(booking.reservation_expires_at)}</span>
              </div>
            )}
            <div
              className="od-pricing-row"
              style={{ fontSize: "12px", opacity: 0.85 }}
            >
              <span>Calendar sync</span>
              <span>
                {booking.last_synced_at || booking.last_sync_at
                  ? time(booking.last_synced_at || booking.last_sync_at)
                  : "Pending initial sync"}
              </span>
            </div>
          </section>

          {/* Payment & Status Overview */}
          <section
            className="adm-card adm-card--outlined od-section"
            aria-labelledby="bk-payments-summary-heading"
          >
            <h2 className="od-section__title" id="bk-payments-summary-heading">
              PAYMENTS OVERVIEW
            </h2>
            <p className="od-field-value od-field-value--bold">
              {`${money(booking.paid_minor, booking.currency)} / ${money(booking.remaining_minor, booking.currency)}`}
            </p>
            <p className="od-field-value">
              {`${booking.status} / ${booking.payment_status.replaceAll("_", " ")} / ${booking.calendar_status}`}
            </p>
            {detail.payments.length > 0 ? (
              <p className="od-field-value" style={{ marginTop: "10px" }}>
                {detail.payments.length} verified payment record(s). Check
                Payments &amp; Square below to record or manage payments.
              </p>
            ) : (
              <p className="od-field-value" style={{ marginTop: "10px" }}>
                No verified payments recorded yet. Required deposit:{" "}
                {money(booking.deposit_minor, booking.currency)}.
              </p>
            )}
          </section>
        </div>
      </div>

      {/* Actions Section with Segmented Action Pills */}
      <div className="adm-actions-section">
        <div className="adm-actions-nav-bar">
          <h4 className="adm-actions-heading">Booking Actions</h4>
          <nav
            className="adm-subsection-nav"
            aria-label="Booking action sections"
          >
            {BOOKING_ACTION_TABS.map((sub) => (
              <button
                key={sub.id}
                type="button"
                className={`adm-subsection-btn ${
                  activeTab === sub.id ? "adm-subsection-btn--active" : ""
                }`}
                aria-pressed={activeTab === sub.id}
                onClick={() => setActiveTab(sub.id)}
              >
                {sub.label}
              </button>
            ))}
          </nav>
        </div>

        {formError && <p role="alert">{formError}</p>}

        {/* Action 1: Review Request */}
        {(activeTab === "all" || activeTab === "decision") && (
          <section
            id="sec-decision"
            className="adm-subsection"
            aria-label="Review and decision"
          >
            <OrderDecisionControls booking={booking} onSaved={refresh} />
          </section>
        )}

        {/* Action 2: Payments & Square */}
        {(activeTab === "all" || activeTab === "payments") && (
          <section
            id="sec-payments"
            className="adm-subsection"
            aria-label="Payments management"
          >
            <SquareCheckoutControls booking={booking} />

            <form
              className="adm-card adm-form-card"
              onSubmit={submit("payments", (form) => ({
                reference: form.get("reference"),
                amount_minor: Number(form.get("amount_minor")),
                currency: booking.currency,
                provider: form.get("provider"),
                verification_details: form.get("verification_details"),
              }))}
            >
              <fieldset disabled={busy}>
                <h4>Verify an external payment</h4>
                <p>
                  Check the provider's actual transaction record. Screenshots
                  and payment redirects do not verify payment. Verification is
                  audited.
                </p>
                <Input
                  name="reference"
                  label="Unique provider transaction reference"
                  maxLength={160}
                />
                <Input
                  name="provider"
                  label="Provider"
                  placeholder="Square, PayPal, or Venmo"
                />
                <Input
                  name="amount_minor"
                  label={`Verified amount (${booking.currency} minor units)`}
                  type="number"
                  min="1"
                  step="1"
                />
                <Input
                  name="verification_details"
                  label="Verification details from provider records"
                  minLength={10}
                  maxLength={2000}
                />
                <button>Record verified payment</button>
              </fieldset>
            </form>

            <div className="adm-card adm-history-card">
              <h4>Verified payment history</h4>
              {detail.payments.length === 0 ? (
                <p className="adm-empty-note">
                  No verified payments recorded yet.
                </p>
              ) : (
                <ul className="adm-payment-history-list">
                  {detail.payments.map((payment) => (
                    <li key={payment.reference}>
                      <strong>{payment.provider}</strong>
                      {payment.square_environment === "sandbox"
                        ? " (test)"
                        : ""}
                      : <code>{payment.reference}</code> ·{" "}
                      <span className="adm-paid-amount">
                        {money(payment.amount_minor, payment.currency)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        )}

        {/* Action 3: Flavor Stock */}
        {(activeTab === "all" || activeTab === "flavors") && (
          <section
            id="sec-flavors"
            className="adm-subsection"
            aria-label="Flavor allocations"
          >
            <BookingInventory booking={booking} refresh={refresh} />
          </section>
        )}

        {/* Action 4: Google Calendar */}
        {(activeTab === "all" || activeTab === "calendar") && (
          <section
            id="sec-calendar"
            className="adm-subsection adm-calendar-panel"
            aria-label="Google Calendar connection"
          >
            {/* Card 1: Google Account Connection */}
            <div className="adm-card adm-action-card">
              <h4>Google Calendar connection</h4>
              <p className="adm-card__desc">
                Connect your business Google account to authorize calendar
                access and manage your primary booking calendar.
              </p>

              <div className="adm-calendar-status-box">
                <div className="adm-calendar-status-row">
                  <span className="adm-calendar-status-label">
                    Account Status:
                  </span>
                  <span
                    role={connectionLoading ? "status" : undefined}
                    className={`adm-status ${
                      connection?.status === "connected"
                        ? "adm-status--confirmed"
                        : "adm-status--pending"
                    }`}
                  >
                    Connection:{" "}
                    {connectionLoading
                      ? "Loading…"
                      : connection?.status || "Unavailable"}
                  </span>
                </div>
                {connection?.calendar_id && (
                  <div className="adm-calendar-status-row">
                    <span className="adm-calendar-status-label">Calendar:</span>
                    <span className="adm-calendar-status-value">
                      {connection.calendar_id}
                    </span>
                  </div>
                )}
                {connection?.setup_message && (
                  <p className="adm-calendar-note">
                    {connection.setup_message}
                  </p>
                )}
                {connectionError && (
                  <p role="alert" className="adm-calendar-error">
                    {connectionError}
                  </p>
                )}
                {connection?.last_error && (
                  <p role="alert" className="adm-calendar-error">
                    {connection.last_error}
                  </p>
                )}
              </div>

              <div className="adm-action-btn-row">
                <button
                  type="button"
                  className="adm-btn adm-btn--primary"
                  disabled={
                    busy ||
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
                    busy ||
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
                  disabled={busy || connectionLoading}
                  onClick={refresh}
                >
                  Refresh status
                </button>
              </div>
            </div>

            {/* Card 2: Event Calendar Synchronization */}
            <div className="adm-card adm-action-card">
              <h4>Calendar and synchronization</h4>
              <p className="adm-card__desc">
                Synchronize the booking with Google Calendar or repair missing
                event mappings.
              </p>

              <div className="adm-calendar-status-box">
                <div className="adm-calendar-status-row">
                  <span className="adm-calendar-status-label">Event Sync:</span>
                  <span className="adm-calendar-status-value">
                    Status: {booking.calendar_status}
                    {booking.last_synced_at || booking.last_sync_at
                      ? ` · Synced ${time(
                          booking.last_synced_at || booking.last_sync_at,
                        )}`
                      : " · Pending initial sync"}
                  </span>
                </div>
                {booking.calendar_error && (
                  <p role="alert" className="adm-calendar-error">
                    {booking.calendar_error}
                  </p>
                )}
              </div>

              <div className="adm-action-btn-row">
                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  disabled={busy}
                  onClick={() => mutate(`${path}/retry`)}
                >
                  Retry calendar sync
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  disabled={busy}
                  onClick={() => mutate(`${path}/repair`)}
                >
                  Repair missing event or calendar mapping
                </button>
              </div>
            </div>
          </section>
        )}

        {/* Action 5: Manage Booking */}
        {(activeTab === "all" || activeTab === "manage") && (
          <section
            id="sec-manage"
            className="adm-subsection"
            aria-label="Manage booking"
          >
            {/* Card 1: Update Popsicle Count */}
            {booking.status !== "cancelled" &&
              booking.status !== "fulfilled" && (
                <form
                  className="adm-card adm-action-card"
                  onSubmit={submit("final-count", (form) => ({
                    quantity: Number(form.get("quantity")),
                  }))}
                >
                  <h4>Popsicle count</h4>
                  <p className="adm-card__desc">
                    Update or finalize the headcount for catering preparation.
                  </p>
                  <div className="adm-popsicle-count-fields">
                    <Input
                      name="quantity"
                      label="Final popsicle quantity"
                      type="number"
                      min="50"
                      step="1"
                      defaultValue={booking.quantity}
                      disabled={busy}
                    />
                    <button
                      type="submit"
                      className="adm-btn adm-btn--primary"
                      disabled={busy}
                    >
                      Set final popsicle count
                    </button>
                  </div>
                </form>
              )}

            {/* Card 3: Reschedule Event */}
            {booking.status !== "fulfilled" && (
              <div className="adm-card adm-action-card">
                <div className="adm-action-header-row">
                  <div>
                    <h4>Reschedule event</h4>
                    <p className="adm-card__desc">
                      Update the event date, start/end time, or venue address.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="adm-btn adm-btn--outline"
                    onClick={() => setRescheduleOpen((prev) => !prev)}
                  >
                    {rescheduleOpen
                      ? "Cancel rescheduling"
                      : "Reschedule event"}
                  </button>
                </div>
                {rescheduleOpen && (
                  <form
                    onSubmit={submit("reschedule", eventPayload)}
                    className="adm-reschedule-form"
                  >
                    <fieldset disabled={busy}>
                      <EventFields booking={booking} />
                      <div className="adm-form-actions">
                        <button
                          type="submit"
                          className="adm-btn adm-btn--primary"
                        >
                          Reserve new time and reschedule
                        </button>
                      </div>
                    </fieldset>
                  </form>
                )}
              </div>
            )}

            {/* Card 4: Cancel or Reopen or Completed */}
            {booking.status === "fulfilled" ? (
              <div className="adm-card adm-action-card adm-action-card--fulfilled">
                <h4>Event completed and fulfilled</h4>
                <p className="adm-card__desc">
                  All catering deliverables for this booking have been
                  fulfilled. Rescheduling and cancellation are closed for
                  completed orders.
                </p>
              </div>
            ) : booking.status !== "cancelled" ? (
              <div className="adm-card adm-action-card adm-action-card--danger">
                <div className="adm-action-header-row">
                  <div>
                    <h4 className="adm-danger-text">Cancel booking</h4>
                    <p className="adm-card__desc">
                      Release the reserved catering date and inventory. Recorded
                      payment history remains in the log.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="adm-btn adm-btn--danger-outline"
                    onClick={() => setCancelConfirm((prev) => !prev)}
                  >
                    {cancelConfirm ? "Keep booking" : "Cancel booking"}
                  </button>
                </div>
                {cancelConfirm && (
                  <div className="adm-danger-confirm-box">
                    <p>
                      Are you sure you want to cancel this booking? This action
                      will mark the booking as cancelled and release calendar
                      capacity.
                    </p>
                    <div className="adm-danger-actions">
                      <button
                        type="button"
                        className="adm-btn adm-btn--danger"
                        disabled={busy}
                        onClick={() => mutate(`${path}/cancel`, revision)}
                      >
                        Confirm cancellation
                      </button>
                      <button
                        type="button"
                        className="adm-btn adm-btn--outline"
                        onClick={() => setCancelConfirm(false)}
                      >
                        Nevermind, keep booking
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <form
                className="adm-card adm-action-card"
                onSubmit={submit("reopen", (form) => {
                  if (booking.end_unspecified && !form.get("end"))
                    throw new Error(
                      "Choose the event end time before reopening.",
                    );
                  return {
                    reason: form.get("reason"),
                    ...(form.get("contract_url")
                      ? { contract_url: form.get("contract_url") }
                      : {}),
                    ...(form.get("end")
                      ? { end: new Date(form.get("end")).toISOString() }
                      : {}),
                  };
                })}
              >
                <h4>Reopen cancelled booking</h4>
                <p className="adm-card__desc">
                  Recheck capacity and reactivate the customer's catering
                  request.
                </p>
                <fieldset disabled={busy}>
                  <Input
                    name="reason"
                    label="Reason for reopening"
                    minLength={10}
                  />
                  {!booking.contract_url && (
                    <Input
                      name="contract_url"
                      label="Customer contract link before reopening (optional, HTTPS)"
                      type="url"
                      required={false}
                      pattern="https://.*"
                    />
                  )}
                  {booking.end_unspecified && (
                    <EventEndSelect
                      name="end"
                      label="Event end before reopening (Houston/Central time)"
                      start={booking.start}
                      required
                    />
                  )}
                  <button type="submit" className="adm-btn adm-btn--primary">
                    Reopen and check capacity
                  </button>
                </fieldset>
              </form>
            )}
          </section>
        )}

        {/* Action 6: Automation Jobs */}
        {(activeTab === "all" || activeTab === "jobs") && (
          <section
            id="sec-jobs"
            className="adm-subsection"
            aria-label="Automation jobs"
          >
            <div className="adm-card adm-jobs-card">
              <h4>Automation jobs</h4>
              {(detail.jobs || []).length === 0 ? (
                <p className="adm-empty-note">
                  No automation jobs logged for this booking.
                </p>
              ) : (
                <ul className="adm-jobs-list">
                  {(detail.jobs || []).map((job) => (
                    <li key={job.key}>
                      <strong>{job.kind}</strong>:{" "}
                      {job.delivery?.status || job.status}
                      {(job.delivery?.error || job.delivery?.last_error) && (
                        <> · {job.delivery.error || job.delivery.last_error}</>
                      )}
                      {["failed", "dead_letter"].includes(
                        job.delivery?.status,
                      ) && (
                        <button
                          disabled={busy}
                          type="button"
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
            </div>
          </section>
        )}
      </div>
    </article>
  );
}

function OrderSelections({ order }) {
  return (
    <dl className="adm-detail-grid">
      <div className="adm-detail-item">
        <dt>Customer order</dt>
        <dd>{order.id}</dd>
      </div>
      <div className="adm-detail-item">
        <dt>Customer</dt>
        <dd>
          {order.customer.name} · {order.customer.email} ·{" "}
          {order.customer.phone}
        </dd>
      </div>
      <div className="adm-detail-item">
        <dt>Event type and notes</dt>
        <dd>
          {order.event.type} · {order.event.notes || "None"}
        </dd>
      </div>
      <div className="adm-detail-item">
        <dt>Selections</dt>
        <dd>
          {order.catering_request.quantity}{" "}
          {order.catering_request.popsicle_shape} popsicles ·{" "}
          {order.catering_request.service_type}
        </dd>
      </div>
      <div className="adm-detail-item">
        <dt>Flavors and add-ons</dt>
        <dd>
          {formatFlavorRequests(order.catering_request) || "None"} ·{" "}
          {order.catering_request.add_ons.join(", ") || "None"}
        </dd>
      </div>
      <div className="adm-detail-item">
        <dt>Dry ice blocks</dt>
        <dd>{order.catering_request.dry_ice_blocks ?? "Automatic"}</dd>
      </div>
      <div className="adm-detail-item">
        <dt>Quoted total / deposit</dt>
        <dd>
          {money(order.pricing.total_cents, order.pricing.currency)} /{" "}
          {money(order.pricing.deposit_due_cents, order.pricing.currency)}
        </dd>
      </div>
    </dl>
  );
}

function CustomerOrder({ order, busy, mutate }) {
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      if (!form.get("end"))
        throw new Error("Choose the event end time before creating a booking.");
      await mutate(`/orders/${encodeURIComponent(order.id)}/booking`, {
        end: form.get("end"),
        contract_url: form.get("contract_url"),
      });
    } catch (failure) {
      setError(failure.message);
    }
  }
  return (
    <details className="adm-order-intake-card">
      <summary className="adm-order-intake-summary">
        <div className="adm-order-intake-summary__main">
          <span className="adm-order-intake-title">
            {order.customer.name} · {order.id}
          </span>
          <span className="adm-order-intake-meta">
            {order.event?.type || "Catering event"} · Starts{" "}
            {time(order.event.starts_at)}
          </span>
        </div>
        <div className="adm-order-intake-summary__aside">
          <span className="adm-order-intake-pill">
            {order.catering_request.quantity} paletas ·{" "}
            {order.catering_request.service_type}
          </span>
          <span className="adm-order-intake-price">
            {money(order.pricing.total_cents, order.pricing.currency)}
          </span>
          <span className="adm-order-intake-chevron" aria-hidden="true">
            ▾
          </span>
        </div>
      </summary>
      <div className="adm-order-intake-content">
        <OrderSelections order={order} />
        {error && <p role="alert">{error}</p>}
        <form onSubmit={submit}>
          <fieldset disabled={busy} className="adm-order-intake-fieldset">
            <legend>Prepare customer order for booking</legend>
            <EventEndSelect
              name="end"
              label="Confirmed event end (Houston/Central time)"
              start={order.event.starts_at}
              defaultValue={order.event.ends_at || ""}
              required
            />
            <Input
              name="contract_url"
              label="Order contract link (optional, HTTPS)"
              type="url"
              required={false}
              pattern="https://.*"
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
