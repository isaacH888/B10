import { Link, Navigate, useLocation } from "react-router-dom";

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

  return (
    <section aria-labelledby="confirmation-heading">
      <h1 id="confirmation-heading">Order received</h1>
      <p>
        Thank you, {order.customer?.name}. Your catering request has been
        submitted and is under review. We will be in touch at{" "}
        {order.customer?.email}.
      </p>

      {/* Order summary */}
      <section aria-labelledby="order-details-heading">
        <h2 id="order-details-heading">Order details</h2>
        <dl>
          <dt>Order ID</dt>
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
          <dd>
            {order.event?.type} -{" "}
            {order.event?.starts_at
              ? new Date(order.event.starts_at).toLocaleDateString()
              : "-"}
          </dd>
          <dt>Quantity</dt>
          <dd>{order.catering_request?.quantity} popsicles</dd>
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
        <h2 id="next-steps-heading">What happens next</h2>
        <ol>
          <li>
            Our team will review your request and confirm availability for your
            event date.
          </li>
          <li>
            Once confirmed, you will receive an email with a link to pay the 50%
            deposit (
            {depositDue != null ? formatCents(depositDue) : "50% of your total"}
            ).
          </li>
          <li>
            Payment can be made via Square, PayPal, or Venmo using the link
            provided.
          </li>
          <li>
            Your booking is secured after the deposit is received. A final
            payment reminder will be sent 7 days before your event.
          </li>
        </ol>
      </section>

      <div className="actions">
        <Link to="/order">Place another order</Link>
        <Link to="/">Back to home</Link>
      </div>
    </section>
  );
}
