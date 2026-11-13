import { Link, Navigate, useLocation } from "react-router-dom";
import { EVENT_TIME_ZONE, formatEventTime } from "./eventTime.js";
import { FlavorMixSummary } from "./FlavorPicker.jsx";

// Formats a cents integer as a USD dollar string, e.g. 10000 -> "$100.00"
function formatCents(cents) {
  return "$" + (cents / 100).toFixed(2);
}

// Maps the raw API status enum to a customer-friendly label.
function friendlyStatus(status) {
  const labels = {
    pending_review: "Under review",
    confirmed: "Confirmed",
    fulfilled: "Fulfilled",
    cancelled: "Cancelled",
  };
  return labels[status] ?? status;
}

export function OrderConfirmation() {
  const { state } = useLocation();
  const order = state?.order;

  // If the user navigated directly to this page without order data, send them
  // back to the catering form rather than showing a broken page.
  if (!order) {
    return <Navigate to="/order" replace />;
  }

  const depositDue =
    order.deposit?.amount_due_cents ?? order.pricing?.deposit_due_cents;
  const total = order.pricing?.total_cents;
  const event = order.event || {};
  const location = event.location || {};
  const address = [
    location.line1,
    location.city,
    location.region,
    location.postal_code,
  ]
    .filter(Boolean)
    .join(", ");
  const timeZone = event.timezone || EVENT_TIME_ZONE;

  return (
    <section aria-labelledby="confirmation-heading">
      <h1 id="confirmation-heading">Catering Request Received</h1>
      <p>
        Thank you, {order.customer?.name}. Your catering request has been
        submitted and is under review. We will be in touch at{" "}
        {order.customer?.email}.
      </p>

      {/* Order summary */}
      <section aria-labelledby="order-details-heading">
        <h2 id="order-details-heading">Request Details</h2>
        <dl>
          <dt>Request ID</dt>
          <dd>{order.id}</dd>
          <dt>Status</dt>
          <dd>{friendlyStatus(order.status)}</dd>
          {total != null && (
            <>
              <dt>Estimated total</dt>
              <dd>{formatCents(total)}</dd>
            </>
          )}
          {depositDue != null && (
            <>
              <dt>Deposit due to confirm</dt>
              <dd>{formatCents(depositDue)}</dd>
            </>
          )}
          <dt>Event</dt>
          <dd>{event.type || "Not provided"}</dd>
          <dt>Starts</dt>
          <dd>{formatEventTime(event.starts_at, timeZone)}</dd>
          <dt>Ends</dt>
          <dd>{formatEventTime(event.ends_at, timeZone)}</dd>
          <dt>Time zone</dt>
          <dd>
            {timeZone === EVENT_TIME_ZONE ? "Houston / Central time" : timeZone}
          </dd>
          <dt>Event address</dt>
          <dd>{address || "Not provided"}</dd>
          <dt>Quantity</dt>
          <dd>{order.catering_request?.quantity} paletas</dd>
          {order.catering_request?.flavor_allocations?.length > 0 && (
            <>
              <dt>Requested flavor mix</dt>
              <dd>
                <FlavorMixSummary
                  allocations={order.catering_request.flavor_allocations}
                />
              </dd>
            </>
          )}
          <dt>Service type</dt>
          <dd>
            {order.catering_request?.service_type === "full_service"
              ? "Full service"
              : "Delivery"}
          </dd>
        </dl>
      </section>

      {/* Next steps */}
      <section aria-labelledby="next-steps-heading">
        <h2 id="next-steps-heading">What Happens Next</h2>
        <ol>
          <li>
            Our team will review your request and confirm availability for your
            event date.
          </li>
          <li>
            After availability is approved, our team will provide instructions
            for the deposit (
            {depositDue != null ? formatCents(depositDue) : "50% of your total"}
            ).
          </li>
          <li>
            Use the payment method agreed with our team. The owner will verify
            the transaction with the payment provider.
          </li>
          <li>
            Your booking is secured after the owner verifies the required
            deposit. Our team will coordinate the remaining balance and event
            details with you.
          </li>
        </ol>
      </section>

      <div className="actions">
        <Link to="/order">Start another catering request</Link>
        <Link to="/">Back to home</Link>
      </div>
    </section>
  );
}
