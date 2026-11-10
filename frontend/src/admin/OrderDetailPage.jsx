import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import "./admin-dashboard.css";
import "./order-detail.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";
import {
  approveOrder,
  cancelOrder,
  fetchOrder,
  recordPayment,
  retryCalsync,
} from "./adminApi.js";

const NAV_ITEMS = [
  { label: "Dashboard", icon: iconDashboard, href: "/admin/dashboard" },
  { label: "Orders", icon: iconOrders, href: "/admin/orders" },
  { label: "Calendar", icon: iconCalendar, href: "/admin/calendar" },
  { label: "Inventory", icon: iconInventory, href: "/admin/inventory" },
];

function AdminNav() {
  return (
    <aside className="adm-nav" aria-label="Admin navigation">
      <div className="adm-nav__brand">
        <img
          src={logoSrc}
          alt="Popssibilities logo"
          className="adm-nav__logo"
          width={64}
          height={58}
        />
        <p className="adm-nav__site-name">POPSSIBILITIES</p>
        <p className="adm-nav__area">BUSINESS ADMIN</p>
      </div>
      <nav aria-label="Admin pages">
        <ul className="adm-nav__list" role="list">
          {NAV_ITEMS.map((item) => (
            <li key={item.label}>
              <Link to={item.href} className="adm-nav__link">
                <img
                  src={item.icon}
                  alt=""
                  aria-hidden="true"
                  className="adm-nav__icon"
                  width={24}
                  height={24}
                />
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="adm-nav__note">
        <p className="adm-nav__note-heading">
          A LITTLE ORDER.
          <br />A LOT OF JOY.
        </p>
        <p className="adm-nav__note-sub">
          Houston, TX
          <br />
          Owner workspace
        </p>
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Record Payment modal
// ---------------------------------------------------------------------------
function RecordPaymentModal({ order, onClose, onSaved }) {
  const [form, setForm] = useState({
    method: "Venmo",
    amountDollars: "",
    reference: "",
    note: "",
  });
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({});
  const [apiError, setApiError] = useState("");
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function set(field, val) {
    setForm((f) => ({ ...f, [field]: val }));
    setErrors((e) => {
      const n = { ...e };
      delete n[field];
      return n;
    });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = {};
    const amt = parseFloat(form.amountDollars);
    if (isNaN(amt) || amt <= 0) errs.amountDollars = "Enter a valid amount.";
    if (!form.reference.trim()) errs.reference = "Reference is required.";
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    setBusy(true);
    setApiError("");
    try {
      const result = await recordPayment(order.id, form);
      onSaved(result.order);
    } catch (err) {
      setApiError(err.message || "Could not record payment. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="od-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="od-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pay-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="od-modal__header">
          <h2 className="od-modal__title" id="pay-modal-title">
            RECORD EXTERNAL PAYMENT
          </h2>
          <button
            type="button"
            className="od-modal__close"
            onClick={onClose}
            aria-label="Close"
            ref={firstRef}
          >
            Close ×
          </button>
        </div>

        <div className="od-modal__context">
          <p className="od-modal__context-label">
            Order {order.id} · {order.customer}
          </p>
          <p className="od-modal__context-note">
            Payments happen externally (Venmo, PayPal, Square, Zelle, check).
            <br />
            Record them here after you've verified receipt. This workspace does
            not charge customers.
          </p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="od-modal__field-row">
            <div className="od-modal__field">
              <label htmlFor="pay-method" className="od-modal__label">
                Payment method
              </label>
              <select
                id="pay-method"
                className="od-modal__input"
                value={form.method}
                onChange={(e) => set("method", e.target.value)}
              >
                {[
                  "Venmo",
                  "PayPal",
                  "Zelle",
                  "Square",
                  "Cash",
                  "Check",
                  "Other",
                ].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </div>
            <div className="od-modal__field">
              <label htmlFor="pay-amount" className="od-modal__label">
                Amount ($){" "}
                <span className="od-modal__required" aria-hidden="true">
                  *
                </span>
              </label>
              <input
                id="pay-amount"
                type="number"
                min="1"
                step="0.01"
                className={`od-modal__input${errors.amountDollars ? " od-modal__input--error" : ""}`}
                value={form.amountDollars}
                onChange={(e) => set("amountDollars", e.target.value)}
                placeholder="e.g. 650.00"
                aria-describedby={
                  errors.amountDollars ? "pay-amount-err" : undefined
                }
              />
              {errors.amountDollars && (
                <p id="pay-amount-err" className="od-modal__error" role="alert">
                  {errors.amountDollars}
                </p>
              )}
            </div>
          </div>

          <div className="od-modal__field">
            <label htmlFor="pay-ref" className="od-modal__label">
              Reference / confirmation number{" "}
              <span className="od-modal__required" aria-hidden="true">
                *
              </span>
            </label>
            <input
              id="pay-ref"
              type="text"
              className={`od-modal__input${errors.reference ? " od-modal__input--error" : ""}`}
              value={form.reference}
              onChange={(e) => set("reference", e.target.value)}
              placeholder="e.g. VM-1028-1045"
              aria-describedby={errors.reference ? "pay-ref-err" : undefined}
            />
            {errors.reference && (
              <p id="pay-ref-err" className="od-modal__error" role="alert">
                {errors.reference}
              </p>
            )}
          </div>

          <div className="od-modal__field">
            <label htmlFor="pay-note" className="od-modal__label">
              Note <span className="od-modal__optional">(optional)</span>
            </label>
            <input
              id="pay-note"
              type="text"
              className="od-modal__input"
              value={form.note}
              onChange={(e) => set("note", e.target.value)}
              placeholder="e.g. Receipt screenshot verified"
            />
          </div>

          {apiError && (
            <p className="od-modal__error" role="alert">
              {apiError}
            </p>
          )}

          <div className="od-modal__actions">
            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="adm-btn adm-btn--primary"
              disabled={busy}
            >
              {busy ? "Recording…" : "Record payment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cancel Order modal
// ---------------------------------------------------------------------------
function CancelModal({ order, onClose, onCancelled }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const firstRef = useRef(null);

  useEffect(() => {
    firstRef.current?.focus();
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function handleCancel(e) {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please provide a reason for cancellation.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await cancelOrder(order.id, reason);
      onCancelled(result.order);
    } catch (err) {
      setError(err.message || "Could not cancel order. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="od-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="od-modal od-modal--warn"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cancel-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="od-modal__header">
          <h2
            className="od-modal__title od-modal__title--warn"
            id="cancel-modal-title"
          >
            CANCEL ORDER
          </h2>
          <button
            type="button"
            className="od-modal__close"
            onClick={onClose}
            aria-label="Close"
            ref={firstRef}
          >
            Close ×
          </button>
        </div>
        <p className="od-modal__context-note">
          Cancellation does not issue external refunds automatically. Any
          deposits already paid will need to be handled separately with the
          customer.
        </p>
        <form onSubmit={handleCancel} noValidate>
          <div className="od-modal__field">
            <label htmlFor="cancel-reason" className="od-modal__label">
              Reason for cancellation{" "}
              <span className="od-modal__required" aria-hidden="true">
                *
              </span>
            </label>
            <textarea
              id="cancel-reason"
              className="od-modal__textarea"
              rows={3}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                setError("");
              }}
              placeholder="e.g. Customer requested cancellation"
            />
            {error && (
              <p className="od-modal__error" role="alert">
                {error}
              </p>
            )}
          </div>
          <div className="od-modal__actions">
            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={onClose}
              disabled={busy}
            >
              Keep order
            </button>
            <button
              type="submit"
              className="adm-btn adm-btn--danger"
              disabled={busy}
            >
              {busy ? "Cancelling…" : "Cancel order"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status card
// ---------------------------------------------------------------------------
function StatusCard({ label, value, sub, color }) {
  return (
    <div className={`od-status-card od-status-card--${color}`}>
      <p className="od-status-card__label">{label}</p>
      <p className="od-status-card__value">{value}</p>
      <p className="od-status-card__sub">{sub}</p>
    </div>
  );
}

const SYNC_COLOR = {
  failed: "yellow",
  synced: "pink",
  not_eligible: "softpink",
};

// ---------------------------------------------------------------------------
// Order Detail Page
// ---------------------------------------------------------------------------
export function OrderDetailPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();

  const [order, setOrder] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [toast, setToast] = useState(null);
  const [showPayModal, setShowPayModal] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [approveBusy, setApproveBusy] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const { order: data } = await fetchOrder(orderId);
      setOrder(data);
      setLoadState("ready");
    } catch (err) {
      setLoadState(err.status === 404 ? "notfound" : "error");
    }
  }, [orderId]);

  useEffect(() => {
    load();
  }, [load]);

  function showToast(msg, type = "success") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  }

  async function handleApprove() {
    setApproveBusy(true);
    try {
      const result = await approveOrder(order.id);
      setOrder(result.order);
      showToast("Availability approved.");
    } catch (err) {
      showToast(err.message || "Could not approve.", "error");
    } finally {
      setApproveBusy(false);
    }
  }

  async function handleRetrySync() {
    setSyncBusy(true);
    try {
      const result = await retryCalsync(order.id);
      setOrder(result.order);
      showToast("Calendar sync retried successfully.");
    } catch (err) {
      showToast(err.message || "Sync failed again.", "error");
    } finally {
      setSyncBusy(false);
    }
  }

  // ---- Render ----
  if (loadState === "loading") {
    return (
      <div className="adm-shell">
        <AdminNav />
        <div className="adm-main">
          <div className="adm-content">
            <p
              role="status"
              style={{ padding: "32px 0", fontFamily: "'DM Sans', sans-serif" }}
            >
              Loading order…
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (loadState === "notfound") {
    return (
      <div className="adm-shell">
        <AdminNav />
        <div className="adm-main">
          <div className="adm-content">
            <p style={{ fontFamily: "'DM Sans', sans-serif" }}>
              Order not found.
            </p>
            <Link to="/admin/orders" className="adm-card__link">
              ← All orders
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="adm-shell">
        <AdminNav />
        <div className="adm-main">
          <div className="adm-content">
            <p role="alert" style={{ fontFamily: "'DM Sans', sans-serif" }}>
              Could not load order. <button onClick={load}>Try again</button>
            </p>
          </div>
        </div>
      </div>
    );
  }

  const isPending = order.orderStatus === "pending";
  const isConfirmed = order.orderStatus === "confirmed";
  const isCancelled = order.orderStatus === "cancelled";
  const syncFailed = order.calendarSync === "failed";

  return (
    <div className="adm-shell">
      <AdminNav />

      <div className="adm-main">
        {/* Page header */}
        <header className="adm-page-header">
          <p className="adm-page-header__title">Orders / {order.id}</p>
          <div className="adm-page-header__actions">
            <a href="/" className="adm-page-header__view-site">
              View website ↗
            </a>
            <button type="button" className="adm-btn adm-btn--outline">
              Owner account ⌄
            </button>
          </div>
        </header>

        <div className="adm-content">
          {/* Back + heading */}
          <div>
            <Link to="/admin/orders" className="od-back-link">
              ← All orders
            </Link>
            <div className="od-heading-row">
              <h1 className="od-heading">
                {order.id} · {order.customer.toUpperCase()}
              </h1>
              <button type="button" className="adm-btn adm-btn--outline">
                Export summary ↓
              </button>
            </div>
            <p className="od-created">{order.createdLabel}</p>
          </div>

          {/* Three status cards */}
          <div className="od-status-row" aria-label="Order status overview">
            <StatusCard
              label="BOOKING STATUS"
              value={order.orderStatusLabel}
              sub={
                order.orderStatus === "confirmed"
                  ? `Availability approved`
                  : "Availability not approved"
              }
              color="pink"
            />
            <StatusCard
              label="PAYMENT STATUS"
              value={order.paymentStatusLabel}
              sub={order.paymentSub}
              color="softpink"
            />
            <StatusCard
              label="CALENDAR SYNC STATUS"
              value={order.calendarSyncLabel}
              sub={order.calendarSyncSub}
              color={SYNC_COLOR[order.calendarSync] || "yellow"}
            />
          </div>

          {/* Confirm banner */}
          {!isCancelled && (
            <div
              className="od-confirm-banner"
              role={isPending ? "alert" : "status"}
            >
              <p className="od-confirm-banner__heading">
                {order.confirmBanner.heading}
              </p>
              <p className="od-confirm-banner__body">
                {order.confirmBanner.body}
              </p>
            </div>
          )}

          {/* Two-column layout */}
          <div className="od-columns">
            {/* Left column */}
            <div className="od-col-left">
              {/* Customer & Event */}
              <section
                className="adm-card adm-card--outlined od-section"
                aria-labelledby="od-customer-heading"
              >
                <h2 className="od-section__title" id="od-customer-heading">
                  CUSTOMER &amp; EVENT
                </h2>
                <div className="od-section__two-col">
                  <div>
                    <p className="od-field-value od-field-value--bold">
                      {order.customer}
                    </p>
                    <p className="od-field-value">{order.email}</p>
                    <p className="od-field-value">{order.phone}</p>
                  </div>
                  <div>
                    <p className="od-field-label">
                      {order.service.toUpperCase()}
                    </p>
                    <p className="od-field-value">{order.date}</p>
                    <p className="od-field-value">
                      Team arrival: {order.arrivalWindow}
                    </p>
                  </div>
                </div>
                <div className="od-section__divider" />
                <p className="od-field-label">EVENT LOCATION</p>
                <p className="od-field-value">
                  {order.location.name} · {order.location.address}
                </p>
                <p className="od-field-value">{order.location.city}</p>
              </section>

              {/* Paleta plan */}
              <section
                className="od-section od-section--softpink"
                aria-labelledby="od-paleta-heading"
              >
                <h2 className="od-section__title" id="od-paleta-heading">
                  THE PALETA PLAN
                </h2>
                <div className="od-section__two-col">
                  <div>
                    <p className="od-field-value od-field-value--large">
                      {order.qty} PALETAS
                    </p>
                    <p className="od-field-value">{order.flavors}</p>
                  </div>
                  <div>
                    <p className="od-field-label">SHAPES</p>
                    <p className="od-field-value">{order.shapes}</p>
                  </div>
                </div>
                <div
                  className="od-section__two-col"
                  style={{ marginTop: "12px" }}
                >
                  <div>
                    <p className="od-field-label">ADD-ONS</p>
                    <p className="od-field-value">{order.addOns}</p>
                  </div>
                  <div>
                    <p className="od-field-label">FLAVOR REQUESTS</p>
                    <p className="od-field-value">{order.flavorRequests}</p>
                  </div>
                </div>
              </section>

              {/* Special instructions */}
              <section
                className="adm-card adm-card--outlined od-section"
                aria-labelledby="od-instr-heading"
              >
                <p className="od-field-label" id="od-instr-heading">
                  SPECIAL INSTRUCTIONS
                </p>
                <p className="od-field-value" style={{ marginTop: "8px" }}>
                  {order.specialInstructions || "None"}
                </p>
              </section>
            </div>

            {/* Right column */}
            <div className="od-col-right">
              {/* Pricing */}
              <section
                className="od-section od-section--pink"
                aria-labelledby="od-pricing-heading"
              >
                <h2 className="od-section__title" id="od-pricing-heading">
                  PRICING
                </h2>
                <ul className="od-line-items" role="list">
                  {order.lineItems.map((li, i) => (
                    <li key={i} className="od-line-item">
                      <span>{li.desc}</span>
                      <span>{li.amount}</span>
                    </li>
                  ))}
                </ul>
                <div className="od-pricing-divider" />
                <div className="od-pricing-row od-pricing-row--total">
                  <span>Order total</span>
                  <span>{order.total}</span>
                </div>
                <div className="od-pricing-row">
                  <span className="od-field-label-sm">
                    Required 50% deposit
                  </span>
                  <span className="od-field-label-sm">{order.deposit}</span>
                </div>
                <div className="od-pricing-row">
                  <span>Verified payments</span>
                  <span>{order.verified}</span>
                </div>
                <div className="od-pricing-row od-pricing-row--total">
                  <span>Remaining balance</span>
                  <span>{order.remaining}</span>
                </div>
              </section>

              {/* Verified payments */}
              <section
                className="adm-card adm-card--outlined od-section"
                aria-labelledby="od-payments-heading"
              >
                <h2 className="od-section__title" id="od-payments-heading">
                  VERIFIED PAYMENTS
                </h2>
                {order.payments.length === 0 ? (
                  <>
                    <p
                      className="od-field-value od-field-value--bold"
                      style={{ marginTop: "12px" }}
                    >
                      No verified payments yet.
                    </p>
                    <p className="od-field-value" style={{ marginTop: "8px" }}>
                      Required to confirm: {order.deposit}.<br />
                      Record a payment below after external verification.
                    </p>
                  </>
                ) : (
                  <ul className="od-payment-list" role="list">
                    {order.payments.map((p, i) => (
                      <li key={i} className="od-payment-item">
                        <p className="od-field-value od-field-value--bold">
                          {p.method} · {p.amount} · Verified
                        </p>
                        <p className="od-field-value">Reference: {p.ref}</p>
                        <p className="od-field-value">
                          {p.date} · Verified by {p.verifiedBy}
                        </p>
                        {p.note && (
                          <p className="od-field-value">Notes: {p.note}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="od-payments-note">
                  Payments happen externally. This workspace records payments;
                  it does not charge.
                </p>
              </section>
            </div>
          </div>

          {/* Action bar */}
          {!isCancelled && (
            <section className="od-action-bar" aria-label="Order actions">
              <div className="od-action-bar__buttons">
                {isPending && (
                  <button
                    type="button"
                    className="adm-btn adm-btn--primary"
                    onClick={handleApprove}
                    disabled={approveBusy}
                    aria-label="Approve availability for this order"
                  >
                    {approveBusy ? "Approving…" : "Approve availability"}
                  </button>
                )}
                {isConfirmed && (
                  <button
                    type="button"
                    className="adm-btn adm-btn--outline"
                    disabled
                    aria-label="Availability already approved"
                  >
                    Availability approved (confirmed)
                  </button>
                )}
                <button
                  type="button"
                  className="adm-btn adm-btn--primary"
                  onClick={() => setShowPayModal(true)}
                >
                  Record external payment
                </button>
                {syncFailed && (
                  <button
                    type="button"
                    className="adm-btn adm-btn--outline"
                    onClick={handleRetrySync}
                    disabled={syncBusy}
                  >
                    {syncBusy ? "Retrying…" : "Retry calendar sync ↗"}
                  </button>
                )}
                <button
                  type="button"
                  className="adm-btn adm-btn--outline adm-btn--danger-outline"
                  onClick={() => setShowCancelModal(true)}
                >
                  Cancel order
                </button>
              </div>
              <p className="od-action-bar__note">
                {isPending
                  ? "Approval alone does not confirm a booking. A verified 50% deposit is also required."
                  : "Rescheduling requires a fresh availability check. Cancellation does not issue external refunds automatically."}
              </p>
            </section>
          )}

          {isCancelled && (
            <div className="od-cancelled-notice" role="status">
              This order has been cancelled.{" "}
              <Link to="/admin/orders" className="adm-card__link">
                Back to orders
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Modals */}
      {showPayModal && (
        <RecordPaymentModal
          order={order}
          onClose={() => setShowPayModal(false)}
          onSaved={(updated) => {
            setOrder(updated);
            setShowPayModal(false);
            showToast("Payment recorded.");
          }}
        />
      )}
      {showCancelModal && (
        <CancelModal
          order={order}
          onClose={() => setShowCancelModal(false)}
          onCancelled={(updated) => {
            setOrder(updated);
            setShowCancelModal(false);
            showToast("Order cancelled.", "error");
          }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`inv-toast inv-toast--${toast.type}`}
          role="status"
          aria-live="polite"
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}
