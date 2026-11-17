import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiRequest } from "../auth/api.js";
import { DecisionConfirmation } from "./DecisionConfirmation.jsx";
import { EventEndSelect } from "./EventEndSelect.jsx";
import "./order-decision.css";

export function OrderDecisionControls({ order, booking, onSaved }) {
  const { sessions } = useAuth();
  const [message, setMessage] = useState("");
  const [contract, setContract] = useState(booking?.contract_url || "");
  const [end, setEnd] = useState(
    (booking?.end_unspecified ? "" : booking?.end || order?.event.ends_at) ||
      "",
  );
  const [pending, setPending] = useState(null);
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const status = booking?.status || order?.status;
  if (["cancelled", "fulfilled"].includes(status)) return null;
  const confirmed = status === "confirmed";

  const start = booking?.start || order?.event.starts_at;

  function decide(event) {
    event.preventDefault();
    const decision = event.nativeEvent.submitter?.value;
    if (
      submitting.current ||
      !["confirm", "conditionally_confirm", "deny"].includes(decision)
    )
      return;
    setError(null);
    setNotice("");
    if (decision === "conditionally_confirm" && !message.trim()) {
      setError({
        message: "Explain the conditions to discuss with the customer.",
      });
      return;
    }
    try {
      const body = { decision, message: message.trim() };
      if (booking) body.expected_revision = booking.revision;
      else body.expected_version = order.version;
      if (decision === "confirm") {
        if (!end)
          throw new Error(
            "Add the event end time before confirming availability.",
          );
        if (contract.trim()) body.contract_url = contract.trim();
        body.end = new Date(end).toISOString();
        if (Date.parse(body.end) <= Date.parse(start))
          throw new Error("Event end must be after the event start.");
      }
      setPending({
        body,
        path: `/admin/automation/${booking ? `bookings/${encodeURIComponent(booking.id)}` : `orders/${encodeURIComponent(order.id)}`}/decision`,
        customer:
          booking?.source_order?.customer?.name ||
          order?.customer?.name ||
          booking?.customer_email ||
          booking?.reference ||
          order?.id,
        start,
      });
    } catch (failure) {
      setError(failure);
    }
  }

  async function confirmDecision() {
    if (!pending || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setPending(null);
    try {
      await apiRequest(pending.path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessions.admin.data.csrf_token,
        },
        body: JSON.stringify(pending.body),
      });
      setNotice("Decision saved. A customer email has been queued.");
      await onSaved();
    } catch (failure) {
      setError(failure);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <section
      className="od-review"
      aria-labelledby={`review-${booking?.id || order?.id}`}
    >
      <h2 id={`review-${booking?.id || order?.id}`}>Review customer request</h2>
      <p>
        Confirm availability, deny the request, or explain conditions to discuss
        with the customer. Confirmation requests the deposit; a verified deposit
        confirms the booking.
      </p>
      {booking?.customer_message && (
        <p>Last customer message: {booking.customer_message}</p>
      )}
      <form onSubmit={decide}>
        <fieldset disabled={busy}>
          <legend>Decision and customer email</legend>
          <label>
            Message to customer (required for conditional confirmation)
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={3}
              maxLength={2000}
            />
          </label>
          {!confirmed && (
            <div className="od-review-inline-fields">
              <label>
                Customer contract link (optional, HTTPS)
                <input
                  type="url"
                  pattern="https://.*"
                  value={contract}
                  onChange={(event) => setContract(event.target.value)}
                  placeholder="https://"
                />
              </label>
              <EventEndSelect
                start={start}
                value={end}
                onChange={setEnd}
                label="Event end (Houston/Central time, required to confirm)"
              />
            </div>
          )}
          <div className="actions">
            {!confirmed && (
              <button
                className="adm-btn adm-btn--primary"
                type="submit"
                value="confirm"
              >
                Confirm availability
              </button>
            )}
            {!confirmed && (
              <button
                className="adm-btn adm-btn--outline"
                type="submit"
                value="conditionally_confirm"
                formNoValidate
              >
                Conditionally confirm
              </button>
            )}
            <button
              className="adm-btn adm-btn--outline"
              type="submit"
              value="deny"
              formNoValidate
            >
              Deny request
            </button>
          </div>
        </fieldset>
      </form>
      {pending && (
        <DecisionConfirmation
          pending={pending}
          onCancel={() => setPending(null)}
          onConfirm={confirmDecision}
        />
      )}
      {(busy || notice) && (
        <p role="status">{busy ? "Saving decision…" : notice}</p>
      )}
      {error && (
        <p role="alert">
          {error.serverMessage || error.message}
          {error.code === "reauthentication_required" && (
            <>
              {" "}
              <Link to="/admin/login?reauth=1">Verify owner access again</Link>
            </>
          )}
        </p>
      )}
    </section>
  );
}
