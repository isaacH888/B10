import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "./auth/api.js";
import { useAuth } from "./auth/AuthContext.jsx";
import { formatEventTime, EVENT_TIME_ZONE } from "./eventTime.js";

const statuses = {
  pending_review: "Under review",
  confirmed: "Confirmed",
  fulfilled: "Fulfilled",
  cancelled: "Cancelled",
};
const money = (cents) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );

export function CustomerOrders() {
  const { expire } = useAuth();
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let controller;
    setResult(null);
    setError("");
    async function load() {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      try {
        const data = await apiRequest(
          `/customer/orders?page=${page}&page_size=10`,
          { signal: request.signal },
        );
        if (active && !request.signal.aborted) {
          setResult(data);
          setError("");
        }
      } catch (failure) {
        if (!active || request.signal.aborted) return;
        if (failure.status === 401) expire("customer");
        else
          setError(
            "We couldn’t load your latest order status. Please try again.",
          );
      }
    }
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 30000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      active = false;
      controller?.abort();
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [page, retry, expire]);

  return (
    <section className="account-panel account-orders" aria-label="Your orders">
      <div className="account-orders-toolbar">
        <p>Your submitted catering requests and their latest status.</p>
        <button
          className="account-button"
          onClick={() => setRetry((value) => value + 1)}
        >
          Refresh orders
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!result && !error && <p role="status">Loading your orders…</p>}
      {result?.items.length === 0 && (
        <div className="account-catering">
          <h3>No orders yet</h3>
          <p>Submit a catering request to follow its status here.</p>
          <Link className="account-button" to="/order">
            Request a catering quote
          </Link>
        </div>
      )}
      {result?.items.map((order) => (
        <article
          className="account-order"
          key={order.id}
          aria-label={`Order ${order.id}`}
        >
          <div className="account-order-heading">
            <h3>{order.event.type}</h3>
            <span className="account-order-status">
              {statuses[order.status] || order.status}
            </span>
          </div>
          <p className="account-order-reference">Request ID: {order.id}</p>
          <dl>
            <div>
              <dt>Event date</dt>
              <dd>
                {formatEventTime(
                  order.event.starts_at,
                  order.event.timezone || EVENT_TIME_ZONE,
                )}
              </dd>
            </div>
            <div>
              <dt>Paletas</dt>
              <dd>
                {order.catering_request.quantity} ·{" "}
                {order.catering_request.service_type === "full_service"
                  ? "Full service"
                  : "Delivery"}
              </dd>
            </div>
            <div>
              <dt>Order total</dt>
              <dd>{money(order.pricing.total_cents)}</dd>
            </div>
            <div>
              <dt>Deposit</dt>
              <dd>
                {order.deposit.status === "confirmed"
                  ? "Verified"
                  : order.deposit.status === "reversed"
                    ? "Reversed"
                    : "Awaiting verification"}{" "}
                · {money(order.deposit.amount_confirmed_cents)} of{" "}
                {money(order.deposit.amount_due_cents)}
              </dd>
            </div>
          </dl>
        </article>
      ))}
      {result && result.total > result.page_size && (
        <nav className="account-order-pagination" aria-label="Order pages">
          <button
            className="account-button"
            disabled={page === 1}
            onClick={() => setPage((value) => value - 1)}
          >
            Previous
          </button>
          <span>
            Page {page} of {Math.ceil(result.total / result.page_size)}
          </span>
          <button
            className="account-button"
            disabled={page * result.page_size >= result.total}
            onClick={() => setPage((value) => value + 1)}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
