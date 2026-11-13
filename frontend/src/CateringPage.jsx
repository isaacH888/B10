import { useAuth } from "./auth/AuthContext.jsx";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import SocialLinks from "./SocialLinks.jsx";
import FlavorPicker, { FlavorMixSummary } from "./FlavorPicker.jsx";
import { flavorMixIssue, validFlavorDraft } from "./flavors.js";
import "./catering.css";
import heroImage from "./assets/Hero.webp";
import logoImage from "./assets/logo.png";
import venueImage from "./assets/Venue.webp";
import { apiRequest } from "./auth/api.js";
import {
  centralTimeToIso,
  EVENT_TIME_ZONE,
  formatEventTime,
} from "./eventTime.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Formats a cents integer as a USD dollar string, e.g. 20000 -> "$200.00"
function formatCents(cents) {
  return "$" + (cents / 100).toFixed(2);
}

function CateringContact() {
  return (
    <p className="catering-contact">
      <a href="mailto:info@popssibilities.com">Email our team</a> or{" "}
      <a href="tel:+12812487514">call 281-248-7514</a>.
    </p>
  );
}

function AllergyNotice({ id, className }) {
  return (
    <p id={id} className={`catering-allergy-note ${className}`}>
      <strong>Allergy information:</strong> Ingredients vary by flavor and may
      include nuts, coconut, strawberries, pineapple, and other fruits. Please{" "}
      <a href="mailto:info@popssibilities.com">contact our team</a> about
      specific ingredients and allergies before ordering.
    </p>
  );
}

function formatEnteredTime(value) {
  if (!value) return "Not provided";
  try {
    return formatEventTime(centralTimeToIso(value));
  } catch {
    return "Check this date and time";
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
  flavor_allocations: [],
  dry_ice_blocks: "",
};

const TOTAL_STEPS = 5;

const stepTitles = [
  "Contact",
  "Service & location",
  "Event schedule",
  "Paletas & extras",
  "Review",
];

// Subtitle shown below the step title inside the modal form area.
const stepSubtitles = [
  "How can we reach you about your request?",
  "Choose your service and tell us where the event will be.",
  "Tell us when your event starts and ends.",
  "Choose your quantity and share any requests.",
  "Check your details, then get your quote.",
];

const DRAFT_KEY = "popssibilities.catering-draft.v1";
const DRAFT_LIFETIME = 2 * 60 * 60 * 1000;

function readDraft() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY));
    const allocations = saved?.form?.flavor_allocations ?? [];
    if (
      saved &&
      Date.now() - saved.savedAt < DRAFT_LIFETIME &&
      Number.isInteger(saved.step) &&
      saved.step >= 1 &&
      saved.step <= TOTAL_STEPS &&
      validFlavorDraft(allocations) &&
      Object.keys(initialForm)
        .filter((key) => key !== "flavor_allocations")
        .every(
          (key) =>
            (typeof saved.form?.[key] === "string" ||
              (["quantity", "dry_ice_blocks"].includes(key) &&
                typeof saved.form?.[key] === "number" &&
                Number.isFinite(saved.form[key]))) &&
            String(saved.form[key]).length <= 2000,
        )
    ) {
      return {
        form: Object.fromEntries(
          Object.keys(initialForm).map((key) => [
            key,
            key === "flavor_allocations" ? allocations : saved.form[key],
          ]),
        ),
        step: saved.step,
      };
    }
  } catch {
    // Drafts are optional when browser storage is unavailable.
  }
  return { form: { ...initialForm }, step: 1 };
}

function clearDraft() {
  try {
    sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // The in-memory draft remains usable when storage is unavailable.
  }
}

function fieldAccessibility(errors, field, id, hint) {
  return {
    "aria-invalid": errors[field] ? true : undefined,
    "aria-describedby":
      [hint, errors[field] && `${id}-error`].filter(Boolean).join(" ") ||
      undefined,
  };
}

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
          {...fieldAccessibility(errors, "name", "cf-name")}
          type="text"
          value={form.name}
          onChange={(e) => onChange("name", e.target.value)}
          autoComplete="name"
          placeholder="Jane Doe"
          required
        />
        {errors.name && (
          <p id="cf-name-error" className="field-error" role="alert">
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
          {...fieldAccessibility(errors, "email", "cf-email")}
          type="email"
          value={form.email}
          onChange={(e) => onChange("email", e.target.value)}
          autoComplete="email"
          placeholder="jane@example.com"
          required
        />
        {errors.email && (
          <p id="cf-email-error" className="field-error" role="alert">
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
          {...fieldAccessibility(errors, "phone", "cf-phone")}
          type="tel"
          value={form.phone}
          onChange={(e) => onChange("phone", e.target.value)}
          autoComplete="tel"
          placeholder="(555) 123-4567"
          required
        />
        {errors.phone && (
          <p id="cf-phone-error" className="field-error" role="alert">
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
          Service type{" "}
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
          {...fieldAccessibility(errors, "location_line1", "cf-line1")}
          type="text"
          value={form.location_line1}
          onChange={(e) => onChange("location_line1", e.target.value)}
          autoComplete="street-address"
          placeholder="123 Example Street"
          required
        />
        {errors.location_line1 && (
          <p id="cf-line1-error" className="field-error" role="alert">
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
            {...fieldAccessibility(errors, "location_city", "cf-city")}
            type="text"
            value={form.location_city}
            onChange={(e) => onChange("location_city", e.target.value)}
            autoComplete="address-level2"
            required
          />
          {errors.location_city && (
            <p id="cf-city-error" className="field-error" role="alert">
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
            {...fieldAccessibility(errors, "location_region", "cf-region")}
            type="text"
            value={form.location_region}
            onChange={(e) => onChange("location_region", e.target.value)}
            autoComplete="address-level1"
            maxLength={2}
            placeholder="TX"
            required
          />
          {errors.location_region && (
            <p id="cf-region-error" className="field-error" role="alert">
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
            {...fieldAccessibility(errors, "location_postal_code", "cf-postal")}
            type="text"
            value={form.location_postal_code}
            onChange={(e) => onChange("location_postal_code", e.target.value)}
            autoComplete="postal-code"
            required
          />
          {errors.location_postal_code && (
            <p id="cf-postal-error" className="field-error" role="alert">
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

      <p id="event-timezone-hint" className="schedule-hint">
        All event times are in Houston/Central time. Enter the event start and,
        if known, the event end.
      </p>

      <div className="form-field">
        <label htmlFor="cf-event-type">
          Event type{" "}
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        </label>
        <input
          id="cf-event-type"
          {...fieldAccessibility(errors, "event_type", "cf-event-type")}
          type="text"
          value={form.event_type}
          onChange={(e) => onChange("event_type", e.target.value)}
          placeholder="Baby shower party"
          required
        />
        {errors.event_type && (
          <p id="cf-event-type-error" className="field-error" role="alert">
            {errors.event_type}
          </p>
        )}
      </div>

      <div className="form-row">
        <div className="form-field">
          <label htmlFor="cf-starts-at">
            Event start date and time{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-starts-at"
            {...fieldAccessibility(
              errors,
              "event_starts_at",
              "cf-starts-at",
              "event-timezone-hint",
            )}
            type="datetime-local"
            value={form.event_starts_at}
            onChange={(e) => onChange("event_starts_at", e.target.value)}
            required
          />
          {errors.event_starts_at && (
            <p id="cf-starts-at-error" className="field-error" role="alert">
              {errors.event_starts_at}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-ends-at">Event end date and time (optional)</label>
          <input
            id="cf-ends-at"
            {...fieldAccessibility(
              errors,
              "event_ends_at",
              "cf-ends-at",
              "event-timezone-hint",
            )}
            type="datetime-local"
            value={form.event_ends_at}
            onChange={(e) => onChange("event_ends_at", e.target.value)}
          />
          {errors.event_ends_at && (
            <p id="cf-ends-at-error" className="field-error" role="alert">
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
            Number of paletas{" "}
            <span className="required-mark" aria-hidden="true">
              *
            </span>
          </label>
          <input
            id="cf-quantity"
            {...fieldAccessibility(errors, "quantity", "cf-quantity")}
            type="number"
            value={form.quantity}
            onChange={(e) => onChange("quantity", e.target.value)}
            min={50}
            max={100000}
            required
          />
          <p className="field-hint">Minimum 50.</p>
          {errors.quantity && (
            <p id="cf-quantity-error" className="field-error" role="alert">
              {errors.quantity}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="cf-shape">Paleta shape</label>
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

      <FlavorPicker
        quantity={form.quantity}
        rows={form.flavor_allocations}
        onChange={(rows) => onChange("flavor_allocations", rows)}
        error={errors.flavor_allocations}
      />

      <div className="form-field">
        <label htmlFor="cf-flavors">
          Custom flavor, add-on, or allergy notes (optional)
        </label>
        <textarea
          id="cf-flavors"
          aria-describedby="cf-flavor-hint cf-allergy-hint"
          value={form.flavor_requests}
          onChange={(e) => onChange("flavor_requests", e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Share preferred flavors, add-ons, or allergy information"
        />
        <p id="cf-flavor-hint" className="field-hint">
          Flavors vary by batch. We’ll confirm available options for your event.
        </p>
        <AllergyNotice id="cf-allergy-hint" className="field-hint" />
      </div>

      <div className="form-field">
        <label htmlFor="cf-dry-ice">Dry ice blocks (optional)</label>
        <input
          id="cf-dry-ice"
          {...fieldAccessibility(errors, "dry_ice_blocks", "cf-dry-ice")}
          type="number"
          value={form.dry_ice_blocks}
          onChange={(e) => onChange("dry_ice_blocks", e.target.value)}
          min={0}
          max={1000}
          placeholder="0"
        />
        <p className="field-hint">$15 per block.</p>
        {errors.dry_ice_blocks && (
          <p id="cf-dry-ice-error" className="field-error" role="alert">
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
  onEdit,
  submitError,
}) {
  const isLoading = quoteStatus === "loading";
  const isSubmitting = quoteStatus === "submitting";
  const busy = isLoading || isSubmitting;

  return (
    <fieldset>
      <legend>{stepTitles[4]}</legend>

      <section className="summary-section" aria-label="Contact details">
        <div className="summary-heading">
          <h3>Contact</h3>
          <button
            type="button"
            onClick={() => onEdit(1)}
            disabled={busy}
            aria-label="Edit contact"
          >
            Edit
          </button>
        </div>
        <dl>
          <dt>Name</dt>
          <dd>{form.name}</dd>
          <dt>Email</dt>
          <dd>{form.email}</dd>
          <dt>Phone</dt>
          <dd>{form.phone}</dd>
        </dl>
      </section>
      <section className="summary-section" aria-label="Service and location">
        <div className="summary-heading">
          <h3>Service &amp; location</h3>
          <button
            type="button"
            onClick={() => onEdit(2)}
            disabled={busy}
            aria-label="Edit service and location"
          >
            Edit
          </button>
        </div>
        <dl>
          <dt>Service</dt>
          <dd>
            {form.service_type === "full_service" ? "Full service" : "Delivery"}
          </dd>
          <dt>Address</dt>
          <dd>
            {form.location_line1}, {form.location_city}, {form.location_region}{" "}
            {form.location_postal_code}
          </dd>
        </dl>
      </section>
      <section className="summary-section" aria-label="Event schedule">
        <div className="summary-heading">
          <h3>Event schedule</h3>
          <button
            type="button"
            onClick={() => onEdit(3)}
            disabled={busy}
            aria-label="Edit event schedule"
          >
            Edit
          </button>
        </div>
        <dl>
          <dt>Event</dt>
          <dd>{form.event_type}</dd>
          <dt>Starts</dt>
          <dd>{formatEnteredTime(form.event_starts_at)}</dd>
          <dt>Ends</dt>
          <dd>{formatEnteredTime(form.event_ends_at)}</dd>
          <dt>Time zone</dt>
          <dd>Houston / Central time</dd>
          {form.event_notes && (
            <>
              <dt>Notes</dt>
              <dd>{form.event_notes}</dd>
            </>
          )}
        </dl>
      </section>
      <section className="summary-section" aria-label="Paletas and extras">
        <div className="summary-heading">
          <h3>Paletas &amp; extras</h3>
          <button
            type="button"
            onClick={() => onEdit(4)}
            disabled={busy}
            aria-label="Edit paletas and extras"
          >
            Edit
          </button>
        </div>
        <dl>
          <dt>Quantity</dt>
          <dd>{form.quantity} paletas</dd>
          <dt>Shape</dt>
          <dd>
            {form.popsicle_shape === "heart" ? "Heart-shaped" : "Standard"}
          </dd>
          {form.flavor_allocations.length > 0 && (
            <>
              <dt>Flavor mix</dt>
              <dd>
                <FlavorMixSummary allocations={form.flavor_allocations} />
              </dd>
            </>
          )}
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

      <p className="request-explanation">
        Submitting a catering request does not secure your date. Our team
        reviews availability and sends payment instructions. Your booking is
        confirmed after the required deposit is verified.
      </p>

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
            Deposit after availability approval:{" "}
            {formatCents(quote.pricing.deposit_due_cents)}
          </p>
          <p className="field-hint">Quote expires in 15 minutes.</p>
          {submitError && (
            <div className="catering-notice" role="alert">
              <p>{submitError}</p>
              <p>Retrying will not create a duplicate order.</p>
              <CateringContact />
            </div>
          )}
          <div className="quote-actions">
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
              {isSubmitting
                ? "Submitting request..."
                : "Submit catering request"}
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
          <CateringContact />
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

      {["error", "expired"].includes(quoteStatus) && (
        <div className="catering-notice" role="alert">
          <p>
            {quoteStatus === "expired"
              ? "Your quote expired. Recalculate to continue. Your details are still here."
              : "We could not retrieve a quote. Your details are still here. Please try again."}
          </p>
          <CateringContact />
          <button
            type="button"
            className="btn-back"
            onClick={onGetQuote}
            style={{ marginTop: "0.5rem" }}
          >
            {quoteStatus === "expired" ? "Recalculate quote" : "Try again"}
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
    let start, end;
    for (const [field, value] of [
      ["event_starts_at", form.event_starts_at],
      ["event_ends_at", form.event_ends_at],
    ]) {
      if (!value) continue;
      try {
        const timestamp = Date.parse(centralTimeToIso(value));
        if (field === "event_starts_at") start = timestamp;
        else end = timestamp;
      } catch (error) {
        errors[field] = error.message;
      }
    }
    if (start <= Date.now())
      errors.event_starts_at = "Event start must be in the future.";
    if (end <= start)
      errors.event_ends_at = "Event end must be after the start time.";
  }
  if (step === 4) {
    const qty = Number(form.quantity);
    if (!Number.isInteger(qty))
      errors.quantity = "Enter a whole number of paletas.";
    else if (!form.quantity || qty < 50)
      errors.quantity = "Minimum order is 50 paletas.";
    else if (qty > 100000)
      errors.quantity = "Maximum order is 100,000 paletas.";
    if (!errors.quantity) {
      const issue = flavorMixIssue(form.flavor_allocations, form.quantity);
      if (issue) errors.flavor_allocations = issue.message;
    }
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
      starts_at: centralTimeToIso(form.event_starts_at),
      ends_at: form.event_ends_at ? centralTimeToIso(form.event_ends_at) : null,
      timezone: EVENT_TIME_ZONE,
      notes: form.event_notes.trim(),
    },
  };
  if (form.flavor_allocations.length) {
    body.catering_request.flavor_allocations = form.flavor_allocations.map(
      ({ flavor, quantity }) => ({ flavor, quantity: Number(quantity) }),
    );
  }
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

function CateringModal({ onClose, draft, onDraftChange }) {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(draft.step);
  const [form, setForm] = useState(draft.form);
  const [errors, setErrors] = useState({});
  const [validationFocus, setValidationFocus] = useState(0);
  // Quotes and retry keys stay in memory and are never restored from a draft.
  const [quoteStatus, setQuoteStatus] = useState("idle");
  const [quote, setQuote] = useState(null);
  const [submitError, setSubmitError] = useState("");
  // Generated once per submission attempt; reused on retry to prevent duplicates.
  const idempotencyKey = useRef(null);
  const modalRef = useRef(null);
  const headingRef = useRef(null);
  const hasDetails = Object.keys(initialForm).some((key) =>
    key === "flavor_allocations"
      ? form[key].length > 0
      : String(form[key]) !== String(initialForm[key]),
  );

  useEffect(() => {
    onDraftChange({ form, step: currentStep });
    if (!hasDetails) {
      clearDraft();
      return;
    }
    try {
      sessionStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({
          form,
          step: currentStep,
          savedAt: Date.now(),
        }),
      );
    } catch {
      // The parent also keeps this draft in memory for close/reopen.
    }
  }, [form, currentStep, hasDetails, onDraftChange]);

  useLayoutEffect(() => {
    const firstInvalid = modalRef.current?.querySelector(
      '[aria-invalid="true"]',
    );
    (firstInvalid || headingRef.current)?.focus();
    if (!firstInvalid) {
      const body = modalRef.current?.querySelector(".modal-body");
      if (body) body.scrollTop = 0;
    }
  }, [currentStep, validationFocus]);

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    if (quoteStatus !== "priced" || !quote) return;
    const timer = window.setTimeout(
      () => {
        setQuoteStatus("expired");
        idempotencyKey.current = null;
      },
      Math.max(0, Date.parse(quote.expires_at) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [quoteStatus, quote]);

  function resetForm() {
    if (
      hasDetails &&
      !window.confirm("Start over? This will clear the details you’ve entered.")
    )
      return;
    clearDraft();
    setForm({ ...initialForm });
    setCurrentStep(1);
    setErrors({});
    setQuote(null);
    setQuoteStatus("idle");
    setSubmitError("");
    idempotencyKey.current = null;
  }

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => {
      if (!prev[field] && !(field === "quantity" && prev.flavor_allocations))
        return prev;
      const next = { ...prev };
      delete next[field];
      if (field === "quantity") delete next.flavor_allocations;
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
      setValidationFocus((value) => value + 1);
      return;
    }
    setErrors({});
    setCurrentStep((prev) => prev + 1);
  }

  function handleBack() {
    setErrors({});
    setCurrentStep((prev) => prev - 1);
  }

  function handleEdit(step) {
    setErrors({});
    setCurrentStep(step);
  }

  async function handleGetQuote() {
    for (let step = 1; step < TOTAL_STEPS; step++) {
      const stepErrors = validateStep(step, form);
      if (Object.keys(stepErrors).length) {
        setErrors(stepErrors);
        setCurrentStep(step);
        setValidationFocus((value) => value + 1);
        return;
      }
    }
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
      setQuoteStatus("expired");
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
      clearDraft();
      onDraftChange({ form: { ...initialForm }, step: 1 });
      navigate("/order/confirm", { state: { order } });
    } catch (error) {
      // Keep the same idempotency key on retry to prevent duplicate orders.
      const refreshQuote = ["quote_expired", "quote_mismatch"].includes(
        error?.code,
      );
      setQuoteStatus(
        error?.code === "quote_expired"
          ? "expired"
          : refreshQuote
            ? "error"
            : "priced",
      );
      if (refreshQuote) {
        setQuote(null);
        idempotencyKey.current = null;
      }
      setSubmitError(
        error?.code === "quote_expired"
          ? "Your quote expired. Please recalculate to get a fresh quote."
          : error?.code === "idempotency_conflict"
            ? "A conflicting order was detected. Please contact us if this continues."
            : "Your catering request could not be submitted. Your details are still here. You can retry safely.",
      );
    }
  }

  function handleModalKeyDown(e) {
    if (
      e.key === "Escape" &&
      !["loading", "submitting"].includes(quoteStatus)
    ) {
      e.preventDefault();
      onClose();
    }
    if (e.key === "Tab") {
      const controls = [
        ...modalRef.current.querySelectorAll(
          "a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
        ),
      ].filter((element) => element.getClientRects().length);
      const first = controls[0],
        last = controls[controls.length - 1];
      if (
        e.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === headingRef.current)
      ) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <div
        className="modal"
        ref={modalRef}
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
            <h2
              id="modal-step-title"
              className="modal-step-title"
              ref={headingRef}
              tabIndex={-1}
            >
              {stepTitles[currentStep - 1]}
            </h2>
            <p className="modal-step-subtitle">
              {stepSubtitles[currentStep - 1]}
            </p>
            <p className="draft-hint">
              Closing keeps your progress. Use Start over to clear it.
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
                  onEdit={handleEdit}
                  submitError={submitError}
                />
              )}
            </div>
          </div>

          {/* Back/Next navigation sits at the bottom of the right form panel */}
          <div className="modal-footer">
            <button
              type="button"
              className="draft-reset"
              onClick={resetForm}
              disabled={["loading", "submitting"].includes(quoteStatus)}
            >
              Start over
            </button>
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
  const { sessions } = useAuth();
  const signedIn = sessions.customer.status === "authenticated";
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState(readDraft);
  const triggerRef = useRef(null);

  function openForm(event) {
    triggerRef.current = event.currentTarget;
    setModalOpen(true);
  }

  function closeForm() {
    setModalOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }

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
        <nav className="cat-nav__links" aria-label="Main navigation">
          <a href="/#paleta-life">The paleta life</a>
          <a href="/#flavors">Flavors</a>
          <a href="/#our-story">Our story</a>
          <a href="/order" aria-label="Catering order">
            Catering
          </a>
        </nav>
        <Link
          className="cat-btn cat-btn--red cat-nav__login"
          to={signedIn ? "/account" : "/login"}
        >
          {signedIn ? "My account" : "Sign in"}
        </Link>
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
              onClick={openForm}
            >
              Request a quote
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
              <p>Hand-crafted with organic ingredients and fresh fruit.</p>
            </div>
            <div className="cat-feature-card">
              <div className="cat-feature-card__icon" aria-hidden="true">
                &bull;
              </div>
              <h3>Rotating Flavors</h3>
              <p>
                Audrey’s flavors vary from batch to batch. Share your
                preferences and we’ll confirm what’s available for your event.
              </p>
            </div>
            <div className="cat-feature-card">
              <div className="cat-feature-card__icon" aria-hidden="true">
                &bull;
              </div>
              <h3>Full Event Service</h3>
              <p>
                Full service includes 1–2 staff, 30 minutes of setup, 2.5 hours
                of serving, and 30 minutes of breakdown.
              </p>
            </div>
          </div>
          <AllergyNotice className="cat-features__note" />
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
                  Get a price estimate or guidance on a custom quote. Delivery
                  within 30 miles: $25&ndash;$75.
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
                  After our team approves availability, follow the payment
                  instructions we send. Your date is secured after the required
                  deposit is verified.
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
            Planning an event?
          </h2>
          <p className="cat-cta__sub">
            Share your event details to request a quote. Availability is
            reviewed before your booking is confirmed.
          </p>
          <button
            type="button"
            className="cat-btn cat-btn--outline-white"
            onClick={openForm}
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
            <a href="/#paleta-life">The paleta life</a>
            <a href="/#flavors">Flavors</a>
            <a href="/order" aria-label="Catering order">
              Catering
            </a>
            <a href="/#our-story">About</a>
          </nav>
          <SocialLinks />
          <p className="cat-footer__copy">
            &copy; {new Date().getFullYear()} Popssibilities. All rights
            reserved.
          </p>
        </div>
      </footer>

      {modalOpen && (
        <CateringModal
          onClose={closeForm}
          draft={draft}
          onDraftChange={setDraft}
        />
      )}
    </div>
  );
}
