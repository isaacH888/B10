import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../auth/api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { squareDestination } from "./squareDestination.js";

export function CustomerDepositAction({ order, onRefresh }) {
  const { sessions, expire } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(null);
  const payment = order.payment;

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => setError(""), [payment?.revision, payment?.status]);

  async function pay() {
    if (request.current || !payment?.can_pay) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest(
        `/customer/orders/${encodeURIComponent(order.id)}/checkout`,
        {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": sessions.customer.data?.csrf_token,
          },
          body: JSON.stringify({ expected_revision: payment.revision }),
        },
      );
      if (!controller.signal.aborted) {
        if (result.environment !== payment.environment)
          throw new Error("environment_changed");
        window.location.assign(
          squareDestination(result.url, payment.environment),
        );
      }
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure.status === 401) expire("customer");
      else if (failure.status === 409) {
        setError(
          "Your payment details changed or the payment window closed. Refresh your orders before trying again.",
        );
      } else
        setError(
          "We couldn’t open Square Checkout. Your payment has not been confirmed. Please try again.",
        );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      request.current = null;
    }
  }

  if (!payment || ["paid", "cancelled"].includes(payment.status)) return null;
  return (
    <div className="account-order-payment" aria-label="Deposit payment">
      {payment.status === "awaiting_approval" ? (
        <p>Payment becomes available after your request is approved.</p>
      ) : payment.status === "expired" ? (
        <p>
          Your deposit payment window has closed. Please contact our team to
          reconfirm availability.
        </p>
      ) : payment.can_pay ? (
        <>
          <p>
            Your request is approved. Pay your deposit securely with Square to
            confirm your booking.
          </p>
          {payment.environment === "sandbox" && (
            <p>
              <strong>Square Sandbox — no real payments.</strong>
            </p>
          )}
          <button
            className="account-button"
            type="button"
            disabled={busy}
            onClick={pay}
          >
            {busy
              ? "Opening Square…"
              : `Pay deposit (${new Intl.NumberFormat("en-US", { style: "currency", currency: payment.currency }).format(payment.amount_due_cents / 100)})`}
          </button>
        </>
      ) : (
        <p>
          Online deposit payment is currently unavailable. Please contact our
          team for payment instructions.
        </p>
      )}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button className="account-button" type="button" onClick={onRefresh}>
            Refresh orders
          </button>
        </div>
      )}
    </div>
  );
}
