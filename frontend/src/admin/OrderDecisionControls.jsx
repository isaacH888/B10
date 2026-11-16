import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiRequest } from "../auth/api.js";
import { centralInputValue, centralTimeToIso } from "../eventTime.js";

export function OrderDecisionControls({ order, booking, onSaved }) {
  const { sessions } = useAuth();
  const [message, setMessage] = useState("");
  const [contract, setContract] = useState(booking?.contract_url || "");
  const [end, setEnd] = useState(
    centralInputValue(
      booking?.end_unspecified ? null : booking?.end || order?.event.ends_at,
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const status = booking?.status || order?.status;
  if (["cancelled", "fulfilled"].includes(status)) return null;
  const confirmed = status === "confirmed";

  async function decide(event) {
    event.preventDefault();
    const decision = event.nativeEvent.submitter?.value;
    setError(null);
    setNotice("");
    if (decision === "conditionally_confirm" && !message.trim()) {
      setError({
        message: "Explain the conditions to discuss with the customer.",
      });
      return;
    }
    setBusy(true);
    try {
      const body = { decision, message: message.trim() };
      if (booking) body.expected_revision = booking.revision;
      else body.expected_version = order.version;
      if (decision === "confirm") {
        if (!contract.trim() || !end)
          throw new Error(
            "Add the contract link and event end time before confirming availability.",
          );
        body.contract_url = contract.trim();
        body.end = new Date(centralTimeToIso(end)).toISOString();
      }
      await apiRequest(
        `/admin/automation/${booking ? `bookings/${encodeURIComponent(booking.id)}` : `orders/${encodeURIComponent(order.id)}`}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": sessions.admin.data.csrf_token,
          },
          body: JSON.stringify(body),
        },
      );
      setNotice("Decision saved. A customer email has been queued.");
      await onSaved();
    } catch (failure) {
      setError(failure);
    } finally {
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
            <>
              <label>
                Customer contract link (required to confirm)
                <input
                  type="url"
                  value={contract}
                  onChange={(event) => setContract(event.target.value)}
                  placeholder="https://"
                />
              </label>
              <label>
                Event end (Houston/Central time, required to confirm)
                <input
                  type="datetime-local"
                  value={end}
                  onChange={(event) => setEnd(event.target.value)}
                />
              </label>
            </>
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
