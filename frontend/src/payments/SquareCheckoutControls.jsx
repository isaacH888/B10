import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiRequest } from "../auth/api.js";

const base = "/admin/automation";
const money = (amount, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    amount / 100,
  );

export function SquareCheckoutControls({ booking }) {
  const { sessions } = useAuth();
  const csrfToken = sessions.admin.data?.csrf_token;
  const [status, setStatus] = useState(null);
  const [link, setLink] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    apiRequest(base + "/square").then(
      (value) => active && setStatus(value),
      () => active && setStatus({ enabled: false }),
    );
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    setLink(null);
    setError("");
  }, [booking.id, booking.revision]);
  const purpose = booking.status === "awaiting_deposit" ? "deposit" : "balance";
  const amount =
    purpose === "deposit"
      ? booking.deposit_minor - booking.paid_minor
      : booking.remaining_minor;
  const allowed =
    ["awaiting_deposit", "confirmed"].includes(booking.status) && amount > 0;
  async function create() {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest(
        `${base}/bookings/${booking.id}/checkout`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({
            purpose,
            expected_revision: booking.revision,
          }),
        },
      );
      const destination = new URL(result.url);
      if (
        destination.origin !== window.location.origin ||
        destination.pathname !== "/payment/pay" ||
        destination.username ||
        destination.password
      )
        throw new Error("Invalid payment destination. Please try again.");
      setLink(result);
    } catch (failure) {
      setError(
        failure.serverMessage ||
          "Could not create the payment link. Try again to retrieve the same link.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Square Checkout">
      <h4>Square Checkout</h4>
      {!status ? (
        <p>Loading payment options…</p>
      ) : !status.enabled ? (
        <p>
          Square payments are awaiting setup. External payments can still be
          verified below.
        </p>
      ) : (
        <>
          {status.environment === "sandbox" && (
            <p>
              <strong>Square Sandbox — no real payments.</strong>
            </p>
          )}
          <p>
            Approved deposits and remaining balances can be paid securely
            through Square.
          </p>
          {allowed ? (
            <button type="button" disabled={busy} onClick={create}>
              {busy
                ? "Creating payment link…"
                : `Create and email ${purpose} link (${money(amount, booking.currency)})`}
            </button>
          ) : (
            <p>
              {booking.remaining_minor === 0
                ? "This booking is paid in full."
                : "Confirm availability before requesting payment."}
            </p>
          )}
          {link && (
            <p role="status">
              Payment email queued.{" "}
              <a href={link.url} target="_blank" rel="noreferrer">
                Open secure {link.purpose} payment link
              </a>
              . Link expires {new Date(link.expires_at * 1000).toLocaleString()}
              .
            </p>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
