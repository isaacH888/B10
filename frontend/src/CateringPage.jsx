import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./catering.css";
import heroImage from "./assets/Hero.webp";
import logoImage from "./assets/logo.png";
import venueImage from "./assets/Venue.webp";
import { apiRequest } from "./auth/api.js";

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
  event_date: "",
  event_time: "",
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
          <label htmlFor="cf-event-date">
            Event date{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-event-date"
            type="date"
            value={form.event_date}
            onChange={(e) => onChange("event_date", e.target.value)}
            required
          />
          {errors.event_date && (
            <p className="field-error" role="alert">
              {errors.event_date}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-event-time">
            Event time{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-event-time"
            type="time"
            value={form.event_time}
            onChange={(e) => onChange("event_time", e.target.value)}
            required
          />
          {errors.event_time && (
            <p className="field-error" role="alert">
              {errors.event_time}
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
          <dt>Date &amp; Time</dt>
          <dd>
            {form.event_starts_at
              ? new Date(form.event_starts_at).toLocaleString([], {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : form.event_date && form.event_time
                ? `${form.event_date} at ${form.event_time}`
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

      {["priced", "submitting"].includes(quoteStatus) && quote && (
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
            Your request needs a manual pricing review. Please contact our team
            for a custom quote. Your order has not been submitted.
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

    const dateVal =
      form.event_date ||
      (form.event_starts_at ? form.event_starts_at.split("T")[0] : "");
    const timeVal =
      form.event_time ||
      (form.event_starts_at && form.event_starts_at.includes("T")
        ? form.event_starts_at.split("T")[1].slice(0, 5)
        : "");

    if (!dateVal) {
      errors.event_date = "Event date is required.";
    }
    if (!timeVal) {
      errors.event_time = "Event time is required.";
    }

    if (dateVal && timeVal) {
      const combined = `${dateVal}T${timeVal}`;
      if (isNaN(new Date(combined).getTime())) {
        errors.event_date = "Please enter a valid date and time.";
      } else if (new Date(combined) <= new Date()) {
        errors.event_date = "Event date and time must be in the future.";
      }
    }
  }
  if (step === 4) {
    const qty = Number(form.quantity);
    if (!Number.isInteger(qty))
      errors.quantity = "Enter a whole number of popsicles.";
    else if (!form.quantity || qty < 50)
      errors.quantity = "Minimum order is 50 popsicles.";
    else if (qty > 100000)
      errors.quantity = "Maximum order is 100,000 popsicles.";
    const dryIce = form.dry_ice_blocks;
    if (
      dryIce !== "" &&
      (!Number.isInteger(Number(dryIce)) ||
        Number(dryIce) < 0 ||
        Number(dryIce) > 1000)
    )
      errors.dry_ice_blocks =
        "Enter a whole number of dry ice blocks from 0 to 1,000.";
  }
  return errors;
}

// Builds the request body the API expects from the flat form state.
function buildRequestBody(form, quoteId) {
  const startsAt =
    form.event_starts_at ||
    (form.event_date && form.event_time
      ? `${form.event_date}T${form.event_time}`
      : "");

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
      starts_at: toIsoWithOffset(startsAt),
      ends_at: null,
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
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "event_date" || field === "event_time") {
        const d = field === "event_date" ? value : prev.event_date;
        const t = field === "event_time" ? value : prev.event_time;
        if (d && t) {
          next.event_starts_at = `${d}T${t}`;
        }
      }
      return next;
    });
    setErrors((prev) => {
      if (!prev[field]) return prev;
      const next = { ...prev };
      delete next[field];
      return next;
    });
    // Back/edit/Next must never submit a price or retry key for older details.
    setQuoteStatus("idle");
    setQuote(null);
    setSubmitError("");
    idempotencyKey.current = null;
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
    idempotencyKey.current = null;
    try {
      const requestBody = buildRequestBody(form, null);
      const data = await apiRequest("/quotes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
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
    if (Date.parse(quote.expires_at) <= Date.now()) {
      setQuoteStatus("error");
      setQuote(null);
      idempotencyKey.current = null;
      return;
    }
    idempotencyKey.current ||= crypto.randomUUID();
    setQuoteStatus("submitting");
    setSubmitError("");
    try {
      const requestBody = buildRequestBody(form, quote.id);
      const order = await apiRequest("/orders", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey.current,
        },
        body: JSON.stringify(requestBody),
      });
      navigate("/order/confirm", { state: { order } });
    } catch (error) {
      // Keep the same idempotency key on retry to prevent duplicate orders.
      const refreshQuote = ["quote_expired", "quote_mismatch"].includes(
        error?.code,
      );
      setQuoteStatus(refreshQuote ? "error" : "priced");
      if (refreshQuote) {
        setQuote(null);
        idempotencyKey.current = null;
      }
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
    if (e.key === "Escape" && !["loading", "submitting"].includes(quoteStatus))
      onClose();
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
                disabled={["loading", "submitting"].includes(quoteStatus)}
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
    <div className="cat-shell">
      {/* ---- Status bar: dark purple strip at very top ---- */}
      <div className="cat-status-bar" aria-label="Site announcement">
        <p className="cat-status-bar__text">
          Mexican Paletas. Endless Popssibilities.
        </p>
      </div>

      {/* ---- Navbar: hot pink ---- */}
      <header className="cat-nav">
        <a href="/" className="cat-nav__brand" aria-label="Popssibilities home">
          <img
            src={logoImage}
            alt="Popssibilities"
            className="cat-nav__logo"
            width={58}
            height={58}
          />
        </a>
        <nav className="cat-nav__links" aria-label="Site navigation">
          <a href="/#menu">The paleta life</a>
          <a href="/#about">Our story</a>
          <a href="/#contact">Stay in the loop</a>
          <a href="/order">Catering</a>
        </nav>
        <button
          type="button"
          className="cat-btn cat-btn--red cat-nav__login"
          onClick={() => setModalOpen(true)}
        >
          Get pop updates ↗
        </button>
      </header>

      <main id="main-content">
        {/* ---- Hero: full-bleed image, text overlaid at bottom ---- */}
        <section className="cat-hero" aria-labelledby="cat-hero-heading">
          <img
            src={heroImage}
            alt="Colorful paletas at a catering event"
            className="cat-hero__image"
          />
          <div className="cat-hero__overlay" aria-hidden="true" />
          <div className="cat-hero__content">
            <h1 id="cat-hero-heading" className="cat-hero__heading">
              Bring the Chill
              <br />
              to Your Event
            </h1>
            <p className="cat-hero__sub">
              From weddings to corporate events, our hand-crafted paletas make
              every moment sweeter. Delivery or full service within 30 miles of
              Houston.
            </p>
            <button
              type="button"
              className="cat-btn cat-btn--red"
              onClick={() => setModalOpen(true)}
            >
              Book now
            </button>
          </div>
        </section>

        {/* ---- Features: yellow background ---- */}
        <section
          className="cat-features"
          aria-labelledby="cat-features-heading"
        >
          <h2 id="cat-features-heading" className="cat-section-title">
            Why Popssibilities?
          </h2>
          <p className="cat-section-sub">
            Everything you need for a sweet, stress-free event.
          </p>
          <div className="cat-features__grid">
            <div className="cat-feature-card">
              <div className="cat-feature-card__icon" aria-hidden="true">
                &bull;
              </div>
              <h3>Premium Paletas</h3>
              <p>
                Hand-crafted with real fruit and natural ingredients. Every
                paleta is made fresh for your event.
              </p>
            </div>
            <div className="cat-feature-card">
              <div className="cat-feature-card__icon" aria-hidden="true">
                &bull;
              </div>
              <h3>Custom Flavors</h3>
              <p>
                Choose from our signature menu or work with us on a custom
                flavor made just for your event.
              </p>
            </div>
            <div className="cat-feature-card">
              <div className="cat-feature-card__icon" aria-hidden="true">
                &bull;
              </div>
              <h3>Full Event Service</h3>
              <p>
                Delivery or full-service staff included. We show up ready so you
                can enjoy every moment.
              </p>
            </div>
          </div>
        </section>

        {/* ---- How it works: white background, red numbers ---- */}
        <section className="cat-how" aria-labelledby="cat-how-heading">
          <h2 id="cat-how-heading" className="cat-section-title">
            How it works
          </h2>
          <p className="cat-section-sub">
            From quote to delivery in just a few steps.
          </p>
          <ol className="cat-how__steps">
            <li className="cat-how__step">
              <span className="cat-how__step-num" aria-hidden="true">
                01
              </span>
              <div>
                <h3>Fill out the form</h3>
                <p>
                  Tell us about your event, how many paletas you need, and any
                  flavor requests.
                </p>
              </div>
            </li>
            <li className="cat-how__step">
              <span className="cat-how__step-num" aria-hidden="true">
                02
              </span>
              <div>
                <h3>Get your quote</h3>
                <p>
                  Receive an instant price. Delivery within 30 miles:
                  $25&ndash;$75.
                </p>
              </div>
            </li>
            <li className="cat-how__step">
              <span className="cat-how__step-num" aria-hidden="true">
                03
              </span>
              <div>
                <h3>Confirm with a deposit</h3>
                <p>
                  Lock in your date with a 50% deposit via Square, PayPal, or
                  Venmo.
                </p>
              </div>
            </li>
            <li className="cat-how__step">
              <span className="cat-how__step-num" aria-hidden="true">
                04
              </span>
              <div>
                <h3>We handle the rest</h3>
                <p>
                  Delivery or full-service staff&mdash;we show up ready so you
                  can enjoy your event.
                </p>
              </div>
            </li>
          </ol>
          <div className="cat-how__rules" aria-label="Pricing quick facts">
            <span>Minimum 50 paletas</span>
            <span aria-hidden="true">&middot;</span>
            <span>Delivery within 30 miles: $25&ndash;$75</span>
            <span aria-hidden="true">&middot;</span>
            <span>Dry ice: $15 per block</span>
            <span aria-hidden="true">&middot;</span>
            <span>50% deposit to confirm</span>
          </div>
        </section>

        {/* ---- CTA: red background, white text ---- */}
        <section className="cat-cta" aria-labelledby="cat-cta-heading">
          <h2 id="cat-cta-heading" className="cat-cta__heading">
            Ready to book?
          </h2>
          <p className="cat-cta__sub">
            Fill out the form in just a few minutes and get your instant quote.
          </p>
          <button
            type="button"
            className="cat-btn cat-btn--outline-white"
            onClick={() => setModalOpen(true)}
          >
            Request a quote
          </button>
        </section>
      </main>

      {/* ---- Footer ---- */}
      <footer className="cat-footer">
        <div className="cat-footer__inner">
          <div className="cat-footer__brand">
            <img
              src={logoImage}
              alt=""
              aria-hidden="true"
              className="cat-footer__logo"
              width={36}
              height={36}
            />
            <span className="cat-footer__name">POPSSIBILITIES</span>
          </div>
          <p className="cat-footer__tagline">
            Houston, TX &middot; info@popssibilities.com &middot; 281-248-7514
          </p>
          <nav className="cat-footer__links" aria-label="Footer navigation">
            <a href="/#menu">Menu</a>
            <a href="/order">Catering</a>
            <a href="/#about">About</a>
            <a href="/#contact">Contact</a>
          </nav>
          <p className="cat-footer__copy">
            &copy; {new Date().getFullYear()} Popssibilities. All rights
            reserved.
          </p>
        </div>
      </footer>

      {modalOpen && <CateringModal onClose={() => setModalOpen(false)} />}
    </div>
  );
}
