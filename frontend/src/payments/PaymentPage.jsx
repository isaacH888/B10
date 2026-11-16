import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiRequest } from "../auth/api.js";

export function PaymentPage() {
  const [params] = useSearchParams();
  const checkout = params.get("checkout") || "";
  const [payment, setPayment] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setPayment(null);
    setError("");
    if (!/^[a-f0-9]{32}$/.test(checkout)) {
      setError(
        "This payment link is invalid. Contact Popssibilities for a new link.",
      );
      return;
    }
    apiRequest(`/payments/square/${checkout}`, {
      signal: controller.signal,
    }).then(
      (value) => {
        if (!controller.signal.aborted) setPayment(value);
      },
      (failure) => {
        if (!controller.signal.aborted)
          setError(
            failure.serverMessage ||
              "Payment details are temporarily unavailable. Please try again.",
          );
      },
    );
    return () => controller.abort();
  }, [checkout]);
  async function pay() {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest(`/payments/square/${checkout}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const destination = new URL(result.url);
      const hosts =
        payment.environment === "sandbox"
          ? ["sandbox.square.link", "connect.squareupsandbox.com"]
          : ["square.link", "checkout.square.site"];
      if (
        destination.protocol !== "https:" ||
        destination.username ||
        destination.password ||
        !hosts.includes(destination.hostname) ||
        (destination.port && destination.port !== "443")
      )
        throw new Error("invalid_destination");
      window.location.assign(destination.href);
    } catch (failure) {
      setError(
        failure.serverMessage ||
          "We could not open Square Checkout. Please try again.",
      );
      setBusy(false);
    }
  }
  return (
    <section className="order-confirmation" aria-labelledby="pay-title">
      <div className="confirmation-intro">
        <h1 id="pay-title">Your catering payment</h1>
      </div>
      {payment?.environment === "sandbox" && (
        <p>
          <strong>Square Sandbox — no real payments.</strong>
        </p>
      )}
      {payment && (
        <>
          <p>
            {payment.purpose === "deposit" ? "Deposit" : "Remaining balance"}:{" "}
            <strong>
              {new Intl.NumberFormat("en-US", {
                style: "currency",
                currency: payment.currency,
              }).format(payment.amount_minor / 100)}
            </strong>
          </p>
          {payment.status === "paid" ? (
            <p>
              This payment has already been verified.{" "}
              <Link to={`/payment/return?checkout=${checkout}`}>
                View payment confirmation
              </Link>
              .
            </p>
          ) : payment.can_pay ? (
            <>
              <p>
                Continue to Square to pay securely by card or an available card
                wallet. Popssibilities does not receive your card details.
              </p>
              <button
                className="confirmation-button confirmation-button--primary"
                type="button"
                disabled={busy}
                onClick={pay}
              >
                {busy ? "Opening Square…" : "Pay securely with Square"}
              </button>
              <p>
                <Link to={`/payment/return?checkout=${checkout}&cancelled=1`}>
                  Cancel and return
                </Link>
              </p>
            </>
          ) : (
            <p>
              This payment link is no longer available. Contact Popssibilities
              for your booking status or a new link.
            </p>
          )}
        </>
      )}
      {!payment && !error && <p>Loading payment details…</p>}
      {error && <p role="alert">{error}</p>}
      <p>
        <Link to="/">Return to Popssibilities</Link>
      </p>
    </section>
  );
}
