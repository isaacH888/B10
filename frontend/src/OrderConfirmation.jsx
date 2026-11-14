import { Link, Navigate, useLocation } from "react-router-dom";
import { EVENT_TIME_ZONE, formatEventTime } from "./eventTime.js";
import { FlavorMixSummary } from "./FlavorPicker.jsx";
import "./order-confirmation.css";

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
  const catering = order.catering_request || {};

  return (
    <section
      className="order-confirmation"
      aria-labelledby="confirmation-heading"
    >
      <header className="confirmation-intro">
        <div className="confirmation-eyebrow">
          <span className="confirmation-received-icon" aria-hidden="true">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              focusable="false"
            >
              <path d="m5 12 4 4L19 6" />
            </svg>
          </span>
          <span>Request submitted</span>
        </div>
        <h1 id="confirmation-heading">Catering Request Received</h1>
        <p>
          Thank you, {order.customer?.name}. Your catering request has been
          submitted and is under review. We will be in touch at{" "}
          <span>{order.customer?.email}</span>.
        </p>
      </header>

      <div className="confirmation-layout">
        <section
          className="confirmation-card confirmation-details"
          aria-labelledby="order-details-heading"
        >
          <div className="confirmation-card-heading">
            <h2 id="order-details-heading">Request Details</h2>
            <span
              className="confirmation-status"
              aria-label={`Request status: ${friendlyStatus(order.status)}`}
            >
              {friendlyStatus(order.status)}
            </span>
          </div>
          <dl className="confirmation-facts">
            <div className="confirmation-facts__wide">
              <dt>Request ID</dt>
              <dd className="confirmation-reference">{order.id}</dd>
            </div>
            <div>
              <dt>Event</dt>
              <dd>{event.type || "Not provided"}</dd>
            </div>
            <div>
              <dt>Service type</dt>
              <dd>
                {catering.service_type === "full_service"
                  ? "Full service"
                  : "Delivery"}
              </dd>
            </div>
            <div>
              <dt>Starts</dt>
              <dd>{formatEventTime(event.starts_at, timeZone)}</dd>
            </div>
            <div>
              <dt>Ends</dt>
              <dd>{formatEventTime(event.ends_at, timeZone)}</dd>
            </div>
            <div className="confirmation-facts__wide">
              <dt>Time zone</dt>
              <dd>
                {timeZone === EVENT_TIME_ZONE
                  ? "Houston / Central time"
                  : timeZone}
              </dd>
            </div>
            <div className="confirmation-facts__wide">
              <dt>Event address</dt>
              <dd>{address || "Not provided"}</dd>
            </div>
          </dl>
        </section>

        <aside
          className="confirmation-card confirmation-quote"
          aria-labelledby="confirmation-quote-heading"
        >
          <h2 id="confirmation-quote-heading">Quote Summary</h2>
          <dl>
            {total != null && (
              <div className="confirmation-total">
                <dt>Estimated total</dt>
                <dd>{formatCents(total)}</dd>
              </div>
            )}
            {depositDue != null && (
              <div className="confirmation-deposit">
                <dt>Deposit due to confirm</dt>
                <dd>{formatCents(depositDue)}</dd>
              </div>
            )}
          </dl>
          <p className="confirmation-payment-note">
            Our team will confirm availability and send deposit instructions.
            Your booking is secured after the required deposit is verified.
          </p>
          <div className="confirmation-help">
            <h3>Have a Question?</h3>
            <a href="mailto:info@popssibilities.com">Email our team</a>
            <a href="tel:+12812487514">Call 281-248-7514</a>
          </div>
        </aside>

        <section
          className="confirmation-card confirmation-paletas"
          aria-labelledby="confirmation-paletas-heading"
        >
          <h2 id="confirmation-paletas-heading">Paletas &amp; Extras</h2>
          <dl className="confirmation-facts">
            <div>
              <dt>Quantity</dt>
              <dd>{catering.quantity} paletas</dd>
            </div>
            <div>
              <dt>Shape</dt>
              <dd>
                {catering.popsicle_shape === "heart"
                  ? "Heart-shaped"
                  : "Regular"}
              </dd>
            </div>
            {catering.flavor_allocations?.length > 0 && (
              <div className="confirmation-facts__wide">
                <dt>Requested flavor mix</dt>
                <dd>
                  <FlavorMixSummary allocations={catering.flavor_allocations} />
                </dd>
              </div>
            )}
            {catering.flavor_requests && (
              <div className="confirmation-facts__wide">
                <dt>Flavor and allergy requests</dt>
                <dd>{catering.flavor_requests}</dd>
              </div>
            )}
            {catering.dry_ice_blocks > 0 && (
              <div>
                <dt>Dry ice</dt>
                <dd>{catering.dry_ice_blocks} blocks</dd>
              </div>
            )}
          </dl>
        </section>

        <section
          className="confirmation-card confirmation-next"
          aria-labelledby="next-steps-heading"
        >
          <h2 id="next-steps-heading">What Happens Next</h2>
          <ol>
            <li>
              <h3>Availability Review</h3>
              <p>
                Our team will review your request and confirm availability for
                your event date.
              </p>
            </li>
            <li>
              <h3>Deposit Instructions</h3>
              <p>
                After availability is approved, our team will provide
                instructions for the deposit (
                {depositDue != null
                  ? formatCents(depositDue)
                  : "50% of your total"}
                ).
              </p>
            </li>
            <li>
              <h3>Payment Verification</h3>
              <p>
                Use the payment method agreed with our team. The owner will
                verify the transaction with the payment provider.
              </p>
            </li>
            <li>
              <h3>Booking Confirmation</h3>
              <p>
                Your booking is secured after the owner verifies the required
                deposit. Our team will coordinate the remaining balance and
                event details with you.
              </p>
            </li>
          </ol>
        </section>
      </div>

      <div className="confirmation-actions">
        <Link
          className="confirmation-button confirmation-button--primary"
          to="/order"
        >
          Start another catering request
        </Link>
        <Link className="confirmation-button" to="/">
          Back to home
        </Link>
      </div>
    </section>
  );
}
