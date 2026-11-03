import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiRequest, errorMessage, navigateToProvider } from "../auth/api.js";

const base = "/admin/automation";
const money = (value, currency) => `${value} ${currency} minor units`;
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
    start: form.get("start"),
    end: form.get("end"),
    timezone: form.get("timezone"),
    venue: form.get("venue"),
  };
}

function EventFields({ booking = {} }) {
  return (
    <>
      <Input
        name="start"
        label="Event start (ISO date, time and UTC offset)"
        placeholder="2027-06-12T14:00:00-05:00"
        defaultValue={booking.start}
      />
      <Input
        name="end"
        label="Event end (ISO date, time and UTC offset)"
        placeholder="2027-06-12T16:00:00-05:00"
        defaultValue={booking.end}
      />
      <Input
        name="timezone"
        label="IANA time zone"
        defaultValue={booking.timezone || "America/Chicago"}
      />
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
    const ok = await mutate("/bookings", {
      ...eventPayload(form),
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
      <section aria-labelledby="customer-intake-heading">
        <h3 id="customer-intake-heading">Customer order intake</h3>
        <p>
          Review submitted orders, add the contract link and confirm the event
          end time. Creating a booking keeps the customer's saved selections and
          price. Approve availability separately.
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
                <th>
                  <Link to={`/admin/bookings/${booking.id}`}>
                    {booking.reference}
                  </Link>
                </th>
                <td>{booking.status}</td>
                <td>{booking.payment_status}</td>
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
              label="Customer contract link (HTTPS)"
              type="url"
              placeholder="https://example.com/contract"
            />
            <button>Create booking request</button>
          </fieldset>
        </form>
      </details>
    </section>
  );
}

function BookingDetail({ detail, busy, mutate }) {
  const booking = detail.booking;
  const path = `/bookings/${booking.id}`;
  const revision = { expected_revision: booking.revision };
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
    <article aria-label={`Booking ${booking.reference}`}>
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
      {booking.source_order && <OrderSelections order={booking.source_order} />}
      <fieldset disabled={busy}>
        <legend>Owner actions</legend>
        <div className="actions">
          {["requested", "owner_review", "awaiting_deposit"].includes(
            booking.status,
          ) && (
            <button
              type="button"
              onClick={() => mutate(`${path}/approve`, revision)}
            >
              Approve availability and reserve capacity
            </button>
          )}
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
            onSubmit={submit("reopen", (form) => ({
              reason: form.get("reason"),
            }))}
          >
            <Input name="reason" label="Reason for reopening" minLength={10} />
            <button>Reopen and check capacity</button>
          </form>
        )}
      </fieldset>
      <h4>Verified payment history</h4>
      <ul>
        {detail.payments.map((payment) => (
          <li key={payment.reference}>
            {payment.provider}: {payment.reference} ·{" "}
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
        {order.catering_request.flavor_requests || "None"} ·{" "}
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
  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await mutate(`/orders/${encodeURIComponent(order.id)}/booking`, {
      end: form.get("end"),
      contract_url: form.get("contract_url"),
    });
  }
  return (
    <details>
      <summary>
        {order.customer.name} · {order.id}
      </summary>
      <OrderSelections order={order} />
      <p>
        Event starts: {time(order.event.starts_at)} · {order.event.timezone}
      </p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <legend>Prepare customer order for booking</legend>
          <Input
            name="end"
            label="Confirmed event end (ISO date, time and UTC offset)"
            defaultValue={order.event.ends_at || ""}
            placeholder="2027-06-12T16:00:00-05:00"
          />
          <Input
            name="contract_url"
            label="Order contract link (HTTPS)"
            type="url"
            pattern="https://.*"
          />
          <button>Create booking from order</button>
        </fieldset>
      </form>
    </details>
  );
}
