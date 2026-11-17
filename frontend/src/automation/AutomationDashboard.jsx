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
} from "../eventTime.js";
import { OrderDecisionControls } from "../admin/OrderDecisionControls.jsx";
import { EventEndSelect } from "../admin/EventEndSelect.jsx";
import { SquareCheckoutControls } from "../payments/SquareCheckoutControls.jsx";

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
      <p>All event times use Houston/Central time.</p>
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
              connectionLoading ||
              !connection?.status ||
              connection.status === "disconnected"
            }
            onClick={() => mutate("/google/disconnect")}
          >
            Disconnect Google Calendar
          </button>
          <button type="button" disabled={connectionLoading} onClick={refresh}>
            Refresh status
          </button>
        </div>
      </fieldset>
      <fieldset disabled={busy}>
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
          <p>No customer orders awaiting intake.</p>
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
      {detail && (
        <BookingDetail
          key={`${detail.booking.id}:${detail.booking.revision}`}
          detail={detail}
          busy={busy}
          mutate={mutate}
          refresh={refresh}
        />
      )}
      <div
        className="table-scroll"
        role="region"
        aria-label="Catering bookings"
        tabIndex={0}
      >
        <table>
          <caption>Catering bookings</caption>
          <thead>
            <tr>
              <th>Customer</th>
              <th>Reference</th>
              <th>Booking</th>
              <th>Payment</th>
              <th>Remaining</th>
              <th>Calendar</th>
            </tr>
          </thead>
          <tbody>
            {items.map((booking) => (
              <tr key={booking.id}>
                <td>
                  {booking.source_order?.customer.name ||
                    booking.customer_email}
                </td>
                <th>
                  <Link to={`/admin/bookings/${booking.id}`}>
                    {booking.reference}
                  </Link>
                </th>
                <td>{booking.status}</td>
                <td>{booking.payment_status.replaceAll("_", " ")}</td>
                <td>{money(booking.remaining_minor, booking.currency)}</td>
                <td>{booking.calendar_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loaded && !error && !items.length && <p>No bookings yet.</p>}
      </div>
      <details>
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

function BookingDetail({ detail, busy, mutate, refresh }) {
  const [formError, setFormError] = useState("");
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
    <article aria-label={`Booking ${booking.reference}`}>
      <h3>
        {booking.source_order?.customer.name || booking.customer_email} ·{" "}
        {booking.reference}
      </h3>
      {formError && <p role="alert">{formError}</p>}
      <dl>
        <dt>Booking / payment / calendar</dt>
        <dd>
          {booking.status} / {booking.payment_status.replaceAll("_", " ")} /{" "}
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
        {booking.overpaid_minor > 0 && (
          <>
            <dt>Overpayment to review</dt>
            <dd>{money(booking.overpaid_minor, booking.currency)}</dd>
          </>
        )}
        <dt>Capacity reservation expires</dt>
        <dd>{time(booking.reservation_expires_at)}</dd>
        <dt>Last successful calendar sync</dt>
        <dd>{time(booking.last_synced_at || booking.last_sync_at)}</dd>
        <dt>Calendar error</dt>
        <dd>{booking.calendar_error || "None"}</dd>
        <dt>Owner review</dt>
        <dd>{booking.owner_review_reason || "None"}</dd>
      </dl>
      {booking.source_order && <OrderSelections order={booking.source_order} />}
      <OrderDecisionControls booking={booking} onSaved={refresh} />
      <SquareCheckoutControls booking={booking} />
      <fieldset disabled={busy}>
        <legend>Owner actions</legend>
        <div className="actions">
          <button type="button" onClick={() => mutate(`${path}/retry`)}>
            Retry calendar sync
          </button>
          <button type="button" onClick={() => mutate(`${path}/repair`)}>
            Repair missing event or calendar mapping
          </button>
        </div>
        {booking.status !== "cancelled" && (
          <form
            onSubmit={submit("final-count", (form) => ({
              quantity: Number(form.get("quantity")),
            }))}
          >
            <Input
              name="quantity"
              label="Final popsicle quantity"
              type="number"
              min="50"
              step="1"
              defaultValue={booking.quantity}
            />
            <button>Set final popsicle count</button>
          </form>
        )}
        <form
          onSubmit={submit("payments", (form) => ({
            reference: form.get("reference"),
            amount_minor: Number(form.get("amount_minor")),
            currency: booking.currency,
            provider: form.get("provider"),
            verification_details: form.get("verification_details"),
          }))}
        >
          <h4>Verify an external payment</h4>
          <p>
            Check the provider's actual transaction record. Screenshots and
            payment redirects do not verify payment. Verification is audited.
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
        </form>
        <details>
          <summary>Reschedule event</summary>
          <form onSubmit={submit("reschedule", eventPayload)}>
            <EventFields booking={booking} />
            <button>Reserve new time and reschedule</button>
          </form>
        </details>
        {booking.status !== "cancelled" ? (
          <details>
            <summary>Cancel booking</summary>
            <p>
              Payment history is retained. Handle any refund separately with the
              payment provider.
            </p>
            <button
              type="button"
              onClick={() => mutate(`${path}/cancel`, revision)}
            >
              Cancel this booking
            </button>
          </details>
        ) : (
          <form
            onSubmit={submit("reopen", (form) => {
              if (booking.end_unspecified && !form.get("end"))
                throw new Error("Choose the event end time before reopening.");
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
            <Input name="reason" label="Reason for reopening" minLength={10} />
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
            <button>Reopen and check capacity</button>
          </form>
        )}
      </fieldset>
      <BookingInventory booking={booking} refresh={refresh} />
      <h4>Verified payment history</h4>
      <ul>
        {detail.payments.map((payment) => (
          <li key={payment.reference}>
            {payment.provider}
            {payment.square_environment === "sandbox" ? " (test)" : ""}:{" "}
            {payment.reference} ·{" "}
            {money(payment.amount_minor, payment.currency)}
          </li>
        ))}
      </ul>
      <h4>Automation jobs</h4>
      <ul>
        {(detail.jobs || []).map((job) => (
          <li key={job.key}>
            {job.kind}: {job.delivery?.status || job.status}
            {(job.delivery?.error || job.delivery?.last_error) && (
              <> · {job.delivery.error || job.delivery.last_error}</>
            )}
            {["failed", "dead_letter"].includes(job.delivery?.status) && (
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
    </article>
  );
}

function OrderSelections({ order }) {
  return (
    <dl>
      <dt>Customer order</dt>
      <dd>{order.id}</dd>
      <dt>Customer</dt>
      <dd>
        {order.customer.name} · {order.customer.email} · {order.customer.phone}
      </dd>
      <dt>Event type and notes</dt>
      <dd>
        {order.event.type} · {order.event.notes || "None"}
      </dd>
      <dt>Selections</dt>
      <dd>
        {order.catering_request.quantity}{" "}
        {order.catering_request.popsicle_shape} popsicles ·{" "}
        {order.catering_request.service_type}
      </dd>
      <dt>Flavors and add-ons</dt>
      <dd>
        {formatFlavorRequests(order.catering_request) || "None"} ·{" "}
        {order.catering_request.add_ons.join(", ") || "None"}
      </dd>
      <dt>Dry ice blocks</dt>
      <dd>{order.catering_request.dry_ice_blocks ?? "Automatic"}</dd>
      <dt>Quoted total / deposit</dt>
      <dd>
        {money(order.pricing.total_cents, order.pricing.currency)} /{" "}
        {money(order.pricing.deposit_due_cents, order.pricing.currency)}
      </dd>
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
    <details>
      <summary>
        {order.customer.name} · {order.id}
      </summary>
      <OrderSelections order={order} />
      {error && <p role="alert">{error}</p>}
      <p>
        Event starts: {time(order.event.starts_at)} · {order.event.timezone}
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
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
          <button>Create booking from order</button>
        </fieldset>
      </form>
    </details>
  );
}
