import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiRequest } from "../auth/api.js";

export function PaymentReturn() {
  const [params] = useSearchParams();
  const checkout = params.get("checkout") || "";
  const cancelled = params.get("cancelled") === "1";
  const [payment, setPayment] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const activeRequest = useRef(null);
  const refresh = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setBusy(true);
    try {
      if (!/^[a-f0-9]{32}$/.test(checkout))
        throw new Error(
          "This payment link is invalid. Please contact Popssibilities.",
        );
      const result = await apiRequest(`/payments/square/${checkout}`, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setPayment(result);
      setError("");
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(
        failure.serverMessage ||
          (failure.code
            ? "Payment status is temporarily unavailable. Please try again."
            : failure.message),
      );
    } finally {
      if (activeRequest.current === controller) setBusy(false);
    }
  }, [checkout]);
  useEffect(() => {
    setPayment(null);
    refresh();
    return () => activeRequest.current?.abort();
  }, [refresh]);
  useEffect(() => {
    if (!payment || payment.status !== "pending" || cancelled) return;
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [payment, cancelled, refresh]);
  const paid = payment?.status === "paid";
  return (
    <section className="order-confirmation" aria-labelledby="payment-title">
      <div className="confirmation-intro">
        <h1 id="payment-title">
          {paid
            ? "Payment received"
            : cancelled
              ? "Checkout cancelled"
              : "Payment status"}
        </h1>
      </div>
      {payment?.environment === "sandbox" && (
        <p>
          <strong>Test payment — no real money was charged.</strong>
        </p>
      )}
      {paid ? (
        <p>
          Your {payment.purpose} payment of{" "}
          {new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: payment.currency,
          }).format(payment.amount_minor / 100)}{" "}
          has been verified. Check your booking confirmation email or contact
          Popssibilities for your booking status.
        </p>
      ) : payment?.status === "failed" ? (
        <p>
          Square could not complete this payment. Contact Popssibilities for a
          new payment link.
        </p>
      ) : payment?.status === "expired" ? (
        <p>
          This payment link has expired. Contact Popssibilities for a new link.
        </p>
      ) : cancelled ? (
        <p>
          You left Checkout. Your payment has not been verified. You can return
          to the payment link in your email or contact Popssibilities.
        </p>
      ) : (
        payment && (
          <p>
            We’re waiting for Square to confirm your payment. This page will
            update automatically. Please keep your payment receipt.
          </p>
        )
      )}
      {error && <p role="alert">{error}</p>}
      {!paid && (
        <button
          className="confirmation-button"
          type="button"
          disabled={busy}
          onClick={refresh}
        >
          {busy ? "Checking…" : "Check payment status"}
        </button>
      )}
      <p>
        <Link to="/">Return to Popssibilities</Link>
      </p>
    </section>
  );
}
