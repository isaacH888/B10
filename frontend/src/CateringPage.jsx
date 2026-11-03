import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./catering.css";
import heroImage from "./assets/Hero.webp";
import venueImage from "./assets/Venue.webp";
import {
  mockGetQuote,
  mockGetQuoteOutsideRadius,
  mockGetQuoteRequiresReview,
  mockSubmitOrder,
} from "./mockApi.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Formats a cents integer as a USD dollar string, e.g. 20000 -> "$200.00"
function formatCents(cents) {
  return "$" + (cents / 100).toFixed(2);
}

// Converts a datetime-local input value ("2026-11-07T15:00") to an ISO 8601
// string with the browser's current UTC offset, e.g. "2026-11-07T15:00:00-06:00"
function toIsoWithOffset(datetimeLocalValue) {
  if (!datetimeLocalValue) return "";
  const date = new Date(datetimeLocalValue);
  const offsetMinutes = date.getTimezoneOffset();
  const sign = offsetMinutes <= 0 ? "+" : "-";
  const absMinutes = Math.abs(offsetMinutes);
  const hh = String(Math.floor(absMinutes / 60)).padStart(2, "0");
  const mm = String(absMinutes % 60).padStart(2, "0");
  const local =
    datetimeLocalValue.length === 16
      ? datetimeLocalValue + ":00"
      : datetimeLocalValue;
  return `${local}${sign}${hh}:${mm}`;
}

// Returns the IANA timezone name for the browser, falling back to UTC.
function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

// ---------------------------------------------------------------------------
// Initial form state
// ---------------------------------------------------------------------------

const initialForm = {
  // Step 1 - contact
  name: "",
  email: "",
  phone: "",
  // Step 2 - service type and event address
  service_type: "delivery",
  location_line1: "",
  location_city: "",
  location_region: "",
  location_postal_code: "",
  // Step 3 - event details
  event_type: "",
  event_starts_at: "",
  event_ends_at: "",
  event_notes: "",
  // Step 4 - order details
  quantity: 50,
  popsicle_shape: "standard",
  flavor_requests: "",
  dry_ice_blocks: "",
};

const TOTAL_STEPS = 5;

const stepTitles = [
  "Your Contact",
  "Your Event",
  "Event Details",
  "Additional Details",
  "Summary",
];

// Subtitle shown below the step title inside the modal form area.
const stepSubtitles = [
  "Tell us about yourself.",
  "How should we serve you?",
  "Let us know more about your event.",
  "Tell us about the popsicles.",
  "Review and get your quote.",
];

// ---------------------------------------------------------------------------
// Step components
// ---------------------------------------------------------------------------

function StepContact({ form, onChange, errors }) {
  return (
    <fieldset>
      <legend>{stepTitles[0]}</legend>

      <div className="form-field">
        <label htmlFor="cf-name">
          Full name{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-name"
          type="text"
          value={form.name}
          onChange={(e) => onChange("name", e.target.value)}
          autoComplete="name"
          placeholder="Jane Doe"
          required
        />
        {errors.name && (
          <p className="field-error" role="alert">
            {errors.name}
          </p>
        )}
      </div>

      <div className="form-field">
        <label htmlFor="cf-email">
          Email address{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-email"
          type="email"
          value={form.email}
          onChange={(e) => onChange("email", e.target.value)}
          autoComplete="email"
          placeholder="jane@example.com"
          required
        />
        {errors.email && (
          <p className="field-error" role="alert">
            {errors.email}
          </p>
        )}
      </div>

      <div className="form-field">
        <label htmlFor="cf-phone">
          Phone number{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-phone"
          type="tel"
          value={form.phone}
          onChange={(e) => onChange("phone", e.target.value)}
          autoComplete="tel"
          placeholder="(555) 123-4567"
          required
        />
        {errors.phone && (
          <p className="field-error" role="alert">
            {errors.phone}
          </p>
        )}
      </div>
    </fieldset>
  );
}

function StepEvent({ form, onChange, errors }) {
  return (
    <fieldset>
      <legend>{stepTitles[1]}</legend>

      {/* Service type as styled radio cards matching Figma */}
      <div
        className="form-field"
        role="group"
        aria-labelledby="service-type-label"
      >
        <span id="service-type-label" className="field-group-label">
          Event style{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </span>
        <div className="service-options">
          <label className="service-option">
            <input
              type="radio"
              name="service_type"
              value="delivery"
              checked={form.service_type === "delivery"}
              onChange={() => onChange("service_type", "delivery")}
            />
            <span className="service-option-text">
              <strong>Delivery</strong>
              <span>We drop off and you serve.</span>
            </span>
          </label>
          <label className="service-option">
            <input
              type="radio"
              name="service_type"
              value="full_service"
              checked={form.service_type === "full_service"}
              onChange={() => onChange("service_type", "full_service")}
            />
            <span className="service-option-text">
              <strong>Full Service</strong>
              <span>Our team serves at your event.</span>
            </span>
          </label>
        </div>
      </div>

      <div className="form-field">
        <label htmlFor="cf-line1">
          Event address{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-line1"
          type="text"
          value={form.location_line1}
          onChange={(e) => onChange("location_line1", e.target.value)}
          autoComplete="street-address"
          placeholder="123 Pop Street, City, State"
          required
        />
        {errors.location_line1 && (
          <p className="field-error" role="alert">
            {errors.location_line1}
          </p>
        )}
      </div>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="cf-city">
            City{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-city"
            type="text"
            value={form.location_city}
            onChange={(e) => onChange("location_city", e.target.value)}
            autoComplete="address-level2"
            required
          />
          {errors.location_city && (
            <p className="field-error" role="alert">
              {errors.location_city}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-region">
            State{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-region"
            type="text"
            value={form.location_region}
            onChange={(e) => onChange("location_region", e.target.value)}
            autoComplete="address-level1"
            maxLength={2}
            placeholder="TX"
            required
          />
          {errors.location_region && (
            <p className="field-error" role="alert">
              {errors.location_region}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-postal">
            Postal code{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-postal"
            type="text"
            value={form.location_postal_code}
            onChange={(e) => onChange("location_postal_code", e.target.value)}
            autoComplete="postal-code"
            required
          />
          {errors.location_postal_code && (
            <p className="field-error" role="alert">
              {errors.location_postal_code}
            </p>
          )}
        </div>
      </div>
    </fieldset>
  );
}

function StepEventDetails({ form, onChange, errors }) {
  return (
    <fieldset>
      <legend>{stepTitles[2]}</legend>

      <div className="form-field">
        <label htmlFor="cf-event-type">
          Event type{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-event-type"
          type="text"
          value={form.event_type}
          onChange={(e) => onChange("event_type", e.target.value)}
          placeholder="Baby shower party"
          required
        />
        {errors.event_type && (
          <p className="field-error" role="alert">
            {errors.event_type}
          </p>
        )}
      </div>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="cf-starts-at">
            Event date{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-starts-at"
            type="datetime-local"
            value={form.event_starts_at}
            onChange={(e) => onChange("event_starts_at", e.target.value)}
            required
          />
          {errors.event_starts_at && (
            <p className="field-error" role="alert">
              {errors.event_starts_at}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-ends-at">Event time (optional)</label>
          <input
            id="cf-ends-at"
            type="datetime-local"
            value={form.event_ends_at}
            onChange={(e) => onChange("event_ends_at", e.target.value)}
          />
          {errors.event_ends_at && (
            <p className="field-error" role="alert">
              {errors.event_ends_at}
            </p>
          )}
        </div>
      </div>

      <div className="form-field">
        <label htmlFor="cf-event-notes">Additional notes (optional)</label>
        <textarea
          id="cf-event-notes"
          value={form.event_notes}
          onChange={(e) => onChange("event_notes", e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Any details that will help us plan for your event"
        />
      </div>
    </fieldset>
  );
}

function StepOrderDetails({ form, onChange, errors }) {
  return (
    <fieldset>
      <legend>{stepTitles[3]}</legend>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="cf-quantity">
            Number of popsicles{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-quantity"
            type="number"
            value={form.quantity}
            onChange={(e) => onChange("quantity", e.target.value)}
            min={50}
            max={100000}
            required
          />
          <p className="field-hint">Minimum 50.</p>
          {errors.quantity && (
            <p className="field-error" role="alert">
              {errors.quantity}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-shape">Popsicle shape</label>
          <select
            id="cf-shape"
            value={form.popsicle_shape}
            onChange={(e) => onChange("popsicle_shape", e.target.value)}
          >
            <option value="standard">Standard</option>
            <option value="heart">Heart-shaped</option>
          </select>
          <p className="field-hint">Heart-shaped may affect pricing.</p>
        </div>
      </div>

      <div className="form-field">
        <label htmlFor="cf-flavors">
          Flavor and add-on requests (optional)
        </label>
        <textarea
          id="cf-flavors"
          value={form.flavor_requests}
          onChange={(e) => onChange("flavor_requests", e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="e.g. Strawberry, mango, no nuts, dietary needs"
        />
      </div>

      <div className="form-field">
        <label htmlFor="cf-dry-ice">Dry ice blocks (optional)</label>
        <input
          id="cf-dry-ice"
          type="number"
          value={form.dry_ice_blocks}
          onChange={(e) => onChange("dry_ice_blocks", e.target.value)}
          min={0}
          max={1000}
          placeholder="0"
        />
        <p className="field-hint">$15 per block.</p>
        {errors.dry_ice_blocks && (
          <p className="field-error" role="alert">
            {errors.dry_ice_blocks}
          </p>
        )}
      </div>
    </fieldset>
  );
}

function StepSummary({
  form,
  quoteStatus,
  quote,
  onGetQuote,
  onSubmitOrder,
  submitError,
}) {
  const isLoading = quoteStatus === "loading";
  const isSubmitting = quoteStatus === "submitting";
  const busy = isLoading || isSubmitting;

  return (
    <fieldset>
      <legend>{stepTitles[4]}</legend>

      <section aria-label="Order summary">
        <dl>
          <dt>Name</dt>
          <dd>{form.name}</dd>
          <dt>Email</dt>
          <dd>{form.email}</dd>
          <dt>Phone</dt>
          <dd>{form.phone}</dd>
          <dt>Service</dt>
          <dd>
            {form.service_type === "full_service" ? "Full service" : "Delivery"}
          </dd>
          <dt>Address</dt>
          <dd>
            {form.location_line1}, {form.location_city}, {form.location_region}{" "}
            {form.location_postal_code}
          </dd>
          <dt>Event</dt>
          <dd>{form.event_type}</dd>
          <dt>Date</dt>
          <dd>
            {form.event_starts_at
              ? new Date(form.event_starts_at).toLocaleString()
              : "-"}
          </dd>
          <dt>Quantity</dt>
          <dd>{form.quantity} popsicles</dd>
          <dt>Shape</dt>
          <dd>
            {form.popsicle_shape === "heart" ? "Heart-shaped" : "Standard"}
          </dd>
          {form.flavor_requests && (
            <>
              <dt>Requests</dt>
              <dd>{form.flavor_requests}</dd>
            </>
          )}
          {form.dry_ice_blocks && (
            <>
              <dt>Dry ice</dt>
              <dd>{form.dry_ice_blocks} blocks</dd>
            </>
          )}
        </dl>
      </section>

      {quoteStatus === "idle" && (
        <button
          type="button"
          className="btn-next"
          onClick={onGetQuote}
          disabled={busy}
          style={{ width: "100%", marginTop: "0.75rem" }}
        >
          Get quote
        </button>
      )}

      {isLoading && (
        <p role="status" style={{ marginTop: "0.75rem" }}>
          Getting your quote...
        </p>
      )}

      {quoteStatus === "priced" && quote && (
        <div className="quote-result">
          <h3>Your quote</h3>
          {quote.pricing.line_items.map((item) => (
            <p
              key={item.code}
              style={{ margin: "0.2rem 0", fontSize: "0.88rem" }}
            >
              {item.description}: {formatCents(item.amount_cents)}
            </p>
          ))}
          <p className="quote-total">
            Total: {formatCents(quote.pricing.total_cents)}
          </p>
          <p className="quote-deposit">
            Deposit to confirm: {formatCents(quote.pricing.deposit_due_cents)}
          </p>
          <p className="field-hint">Quote expires in 15 minutes.</p>
          {submitError && (
            <div className="catering-notice" role="alert">
              <p>{submitError}</p>
              <p>Retrying will not create a duplicate order.</p>
            </div>
          )}
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
            <button
              type="button"
              className="btn-back"
              onClick={onGetQuote}
              disabled={busy}
              style={{ flex: 1 }}
            >
              Recalculate
            </button>
            <button
              type="button"
              className="btn-next"
              onClick={onSubmitOrder}
              disabled={busy}
              style={{ flex: 1 }}
            >
              {isSubmitting ? "Placing order..." : "Place order"}
            </button>
          </div>
        </div>
      )}

      {quoteStatus === "requires_review" && (
        <div className="catering-notice" role="status">
          <p>
            Your request needs a manual pricing review. A member of our team
            will follow up with a custom quote.
          </p>
          <p>No payment is due at this time.</p>
          <button
            type="button"
            className="btn-back"
            onClick={onGetQuote}
            disabled={busy}
            style={{ marginTop: "0.5rem" }}
          >
            Recalculate
          </button>
        </div>
      )}

      {quoteStatus === "inquiry" && quote?.next_action && (
        <div className="catering-notice" role="alert">
          <p>{quote.next_action.message}</p>
          <a
            href={quote.next_action.inquiry_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Submit a custom event inquiry
          </a>
        </div>
      )}

      {quoteStatus === "error" && (
        <div className="catering-notice" role="alert">
          <p>We could not retrieve a quote. Please try again.</p>
          <button
            type="button"
            className="btn-back"
            onClick={onGetQuote}
            style={{ marginTop: "0.5rem" }}
          >
            Try again
          </button>
        </div>
      )}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function validateStep(step, form) {
  const errors = {};
  if (step === 1) {
    if (!form.name.trim()) errors.name = "Full name is required.";
    if (!form.email.trim()) errors.email = "Email address is required.";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      errors.email = "Enter a valid email address.";
    if (!form.phone.trim()) errors.phone = "Phone number is required.";
  }
  if (step === 2) {
    if (!form.location_line1.trim())
      errors.location_line1 = "Street address is required.";
    if (!form.location_city.trim()) errors.location_city = "City is required.";
    if (!form.location_region.trim())
      errors.location_region = "State is required.";
    if (!form.location_postal_code.trim())
      errors.location_postal_code = "Postal code is required.";
  }
  if (step === 3) {
    if (!form.event_type.trim()) errors.event_type = "Event type is required.";
    if (!form.event_starts_at)
      errors.event_starts_at = "Event start date and time is required.";
    else if (new Date(form.event_starts_at) <= new Date())
      errors.event_starts_at = "Event start must be in the future.";
    if (
      form.event_ends_at &&
      new Date(form.event_ends_at) <= new Date(form.event_starts_at)
    )
      errors.event_ends_at = "Event end must be after the start time.";
  }
  if (step === 4) {
    const qty = Number(form.quantity);
    if (!form.quantity || isNaN(qty) || qty < 50)
      errors.quantity = "Minimum order is 50 popsicles.";
    else if (qty > 100000)
      errors.quantity = "Maximum order is 100,000 popsicles.";
    const dryIce = form.dry_ice_blocks;
    if (dryIce !== "" && (isNaN(Number(dryIce)) || Number(dryIce) < 0))
      errors.dry_ice_blocks = "Enter a valid number of dry ice blocks.";
  }
  return errors;
}

// Builds the request body the API expects from the flat form state.
function buildRequestBody(form, quoteId) {
  const body = {
    catering_request: {
      quantity: Number(form.quantity),
      popsicle_shape: form.popsicle_shape,
      flavor_requests: form.flavor_requests.trim(),
      add_ons: [],
      service_type: form.service_type,
      dry_ice_blocks:
        form.dry_ice_blocks !== "" ? Number(form.dry_ice_blocks) : null,
    },
    event: {
      type: form.event_type.trim(),
      location: {
        line1: form.location_line1.trim(),
        city: form.location_city.trim(),
        region: form.location_region.trim().toUpperCase(),
        postal_code: form.location_postal_code.trim(),
        country_code: "US",
      },
      starts_at: toIsoWithOffset(form.event_starts_at),
      ends_at: form.event_ends_at ? toIsoWithOffset(form.event_ends_at) : null,
      timezone: browserTimezone(),
      notes: form.event_notes.trim(),
    },
  };
  if (quoteId) {
    return {
      customer: {
        name: form.name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
      },
      ...body,
      quote_id: quoteId,
    };
  }
  return body;
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

function CateringModal({ onClose }) {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(1);
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  // quoteStatus: "idle" | "loading" | "priced" | "requires_review" | "inquiry" | "error" | "submitting"
  const [quoteStatus, setQuoteStatus] = useState("idle");
  const [quote, setQuote] = useState(null);
  const [submitError, setSubmitError] = useState("");
  // Generated once per submission attempt; reused on retry to prevent duplicates.
  const idempotencyKey = useRef(null);

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
    // Any field change on the summary step invalidates the current quote.
    if (currentStep === 5 && quoteStatus !== "idle") {
      setQuoteStatus("idle");
      setQuote(null);
      idempotencyKey.current = null;
    }
  }

  function handleNext() {
    const stepErrors = validateStep(currentStep, form);
    if (Object.keys(stepErrors).length > 0) {
      setErrors(stepErrors);
      return;
    }
    setErrors({});
    setCurrentStep((prev) => prev + 1);
  }

  function handleBack() {
    setErrors({});
    setCurrentStep((prev) => prev - 1);
  }

  async function handleGetQuote() {
    setQuoteStatus("loading");
    setQuote(null);
    setSubmitError("");
    try {
      const requestBody = buildRequestBody(form, null);
      // TODO: replace with apiRequest("/quotes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestBody) })
      const data = await mockGetQuote(requestBody);
      setQuote(data);
      if (data.status === "priced") {
        setQuoteStatus("priced");
      } else if (data.next_action?.type === "contact_inquiry") {
        setQuoteStatus("inquiry");
      } else {
        setQuoteStatus("requires_review");
      }
    } catch {
      setQuoteStatus("error");
    }
  }

  async function handleSubmitOrder() {
    if (!quote || quoteStatus !== "priced") return;
    idempotencyKey.current ||= crypto.randomUUID();
    setQuoteStatus("submitting");
    setSubmitError("");
    try {
      const requestBody = buildRequestBody(form, quote.id);
      // TODO: replace with apiRequest("/orders", {
      //   method: "POST",
      //   headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey.current },
      //   body: JSON.stringify(requestBody),
      // })
      const order = await mockSubmitOrder(requestBody);
      navigate("/order/confirm", { state: { order } });
    } catch (error) {
      // Keep the same idempotency key on retry to prevent duplicate orders.
      setQuoteStatus("priced");
      setSubmitError(
        error?.code === "quote_expired"
          ? "Your quote expired. Please recalculate to get a fresh quote."
          : error?.code === "idempotency_conflict"
            ? "A conflicting order was detected. Please contact us if this continues."
            : "Your order could not be placed. You can retry safely.",
      );
    }
  }

  function handleModalKeyDown(e) {
    if (e.key === "Escape") onClose();
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-step-title"
        onKeyDown={handleModalKeyDown}
      >
        {/* Left image panel - full height, 50% width */}
        <div className="modal-image-panel">
          <img src={venueImage} alt="" />
        </div>

        {/* Right form panel - title, scrollable fields, footer */}
        <div className="modal-form-panel">
          <div className="modal-form-area">
            <div className="modal-form-header">
              <span className="step-indicator-overlay">
                Step {currentStep} of {TOTAL_STEPS}
              </span>
              <button
                type="button"
                className="modal-close"
                onClick={onClose}
                aria-label="Close catering form"
              >
                &times;
              </button>
            </div>
            <h2 id="modal-step-title" className="modal-step-title">
              {stepTitles[currentStep - 1]}
            </h2>
            <p className="modal-step-subtitle">
              {stepSubtitles[currentStep - 1]}
            </p>
            <div className="modal-body">
              {currentStep === 1 && (
                <StepContact
                  form={form}
                  onChange={handleChange}
                  errors={errors}
                />
              )}
              {currentStep === 2 && (
                <StepEvent
                  form={form}
                  onChange={handleChange}
                  errors={errors}
                />
              )}
              {currentStep === 3 && (
                <StepEventDetails
                  form={form}
                  onChange={handleChange}
                  errors={errors}
                />
              )}
              {currentStep === 4 && (
                <StepOrderDetails
                  form={form}
                  onChange={handleChange}
                  errors={errors}
                />
              )}
              {currentStep === 5 && (
                <StepSummary
                  form={form}
                  quoteStatus={quoteStatus}
                  quote={quote}
                  onGetQuote={handleGetQuote}
                  onSubmitOrder={handleSubmitOrder}
                  submitError={submitError}
                />
              )}
            </div>
          </div>

          {/* Back/Next navigation sits at the bottom of the right form panel */}
          <div className="modal-footer">
            {currentStep > 1 && (
              <button
                type="button"
                className="btn-back"
                onClick={handleBack}
                disabled={
                  quoteStatus === "loading" || quoteStatus === "submitting"
                }
              >
                Back
              </button>
            )}
            {currentStep < TOTAL_STEPS && (
              <button type="button" className="btn-next" onClick={handleNext}>
                Next
              </button>
            )}
          </div>
        </div>
        {/* end modal-form-panel */}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Landing page
// ---------------------------------------------------------------------------

export function CateringPage() {
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <section aria-labelledby="catering-heading">
      {/* Hero - full bleed image with title and CTA overlaid */}
      <div className="catering-hero">
        <img src={heroImage} alt="" className="catering-hero-image" />
        <div className="catering-hero-content">
          <h1 id="catering-heading">Bring the Chill to Your Event</h1>
          <p>
            From weddings to corporate events, our popsicles make every moment
            sweeter.
          </p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => setModalOpen(true)}
          >
            Request a quote
          </button>
        </div>
      </div>

      {/* How it works */}
      <section className="catering-info" aria-labelledby="how-it-works-heading">
        <h2 id="how-it-works-heading">How it works</h2>
        <ol>
          <li>Fill out the short catering form with your event details.</li>
          <li>Get an instant quote based on your order.</li>
          <li>Place your order and pay the 50% deposit to confirm.</li>
          <li>We handle the rest - delivery or full-service staff included.</li>
        </ol>
        <ul>
          <li>Minimum order: 50 popsicles</li>
          <li>Delivery within 30 miles: $25 - $75</li>
          <li>Dry ice available: $15 per block</li>
        </ul>
      </section>

      {modalOpen && <CateringModal onClose={() => setModalOpen(false)} />}
    </section>
  );
}
