import { AdminNav, AdminPageHeader } from "./AdminShell.jsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import "./admin-dashboard.css";
import "./order-detail.css";
import { downloadOrders } from "./adminApi.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { fetchOrder } from "./orderApi.js";
import { AdminRefreshStatus, useAdminRefresh } from "./useAdminRefresh.jsx";

// ---------------------------------------------------------------------------
// Record Payment modal
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
  const location = useLocation();
  const ordersQuery =
    typeof location.state?.ordersQuery === "string"
      ? location.state.ordersQuery
      : "";
  const ordersHref =
    "/admin/orders" +
    (ordersQuery ? `?${new URLSearchParams(ordersQuery)}` : "");
  const { sessions } = useAuth();
  const canExport =
    sessions.admin.data.administrator.permissions.includes("customers:export");

  const [order, setOrder] = useState(null);
  const [loadState, setLoadState] = useState("loading");
  const [exportError, setExportError] = useState(null);
  const [exportBusy, setExportBusy] = useState(false);
  const latestRequest = useRef(0);
  const loadedId = useRef(null);

  const load = useCallback(
    async ({ background = false } = {}) => {
      const version = ++latestRequest.current;
      if (loadedId.current !== orderId) setLoadState("loading");
      try {
        const { order: data } = await fetchOrder(orderId);
        if (version !== latestRequest.current) return false;
        setOrder(data);
        loadedId.current = orderId;
        setLoadState("ready");
      } catch (err) {
        if (version !== latestRequest.current) return false;
        if (
          !background ||
          loadedId.current !== orderId ||
          [401, 403, 404].includes(err.status)
        ) {
          setOrder(null);
          loadedId.current = null;
          setLoadState(err.status === 404 ? "notfound" : "error");
        }
        return false;
      }
    },
    [orderId],
  );

  const refreshState = useAdminRefresh(load);
  useEffect(
    () => () => {
      latestRequest.current += 1;
    },
    [load],
  );

  async function handleExport() {
    setExportBusy(true);
    setExportError(null);
    try {
      await downloadOrders({}, order.id);
    } catch (error) {
      setExportError(error);
    } finally {
      setExportBusy(false);
    }
  }

  // ---- Render ----
  if (loadState === "loading") {
    return (
      <div className="adm-shell">
        <AdminNav activeRoute="/admin/orders" />
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
        <AdminNav activeRoute="/admin/orders" />
        <div className="adm-main">
          <div className="adm-content">
            <p style={{ fontFamily: "'DM Sans', sans-serif" }}>
              Order not found.
            </p>
            <Link to={ordersHref} className="adm-card__link">
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
        <AdminNav activeRoute="/admin/orders" />
        <div className="adm-main">
          <div className="adm-content">
            <p role="alert" style={{ fontFamily: "'DM Sans', sans-serif" }}>
              Could not load order.{" "}
              <button onClick={refreshState.refresh}>Try again</button>
            </p>
          </div>
        </div>
      </div>
    );
  }

  const isPending = order.orderStatus === "pending";
  const isCancelled = order.orderStatus === "cancelled";

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="/admin/orders" />

      <div className="adm-main">
        {/* Page header */}
        <AdminPageHeader title={`Orders / ${order.id}`}>
          <AdminRefreshStatus {...refreshState} />
        </AdminPageHeader>

        <div className="adm-content">
          {/* Back + heading */}
          <div>
            <Link to={ordersHref} className="od-back-link">
              ← All orders
            </Link>
            <div className="od-heading-row">
              <h1 className="od-heading">
                {order.id} · {order.customer.toUpperCase()}
              </h1>
              <button
                type="button"
                className="adm-btn adm-btn--outline"
                disabled={exportBusy || !canExport}
                onClick={handleExport}
              >
                {exportBusy ? "Exporting…" : "Export summary ↓"}
              </button>
            </div>
            <p className="od-created">{order.createdLabel}</p>
            {exportError && (
              <p role="alert">
                {exportError.message}{" "}
                {exportError.code === "reauthentication_required" && (
                  <Link to="/admin/login?reauth=1">
                    Verify owner access again
                  </Link>
                )}
              </p>
            )}
          </div>

          {/* Three status cards */}
          <div className="od-status-row" aria-label="Order status overview">
            <StatusCard
              label="BOOKING STATUS"
              value={order.orderStatusLabel}
              sub={
                order.live
                  ? order.availabilityLabel
                  : order.orderStatus === "confirmed"
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
                      Event time: {order.arrivalWindow}
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
                {order.live ? (
                  <p className="od-field-value">
                    {order.verified} verified.{" "}
                    <Link to={order.managementHref}>
                      Review payment records in the booking workspace
                    </Link>
                    .
                  </p>
                ) : order.payments.length === 0 ? (
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

          {order.live && (
            <section className="od-action-bar" aria-label="Order actions">
              <Link
                className="adm-btn adm-btn--primary"
                to={order.managementHref}
              >
                {order.bookingId
                  ? "Manage linked booking"
                  : "Review customer order intake"}
              </Link>
              <p className="od-action-bar__note">
                Availability approval, payment verification, rescheduling and
                cancellation use the booking workspace.
              </p>
            </section>
          )}

          {isCancelled && (
            <div className="od-cancelled-notice" role="status">
              This order has been cancelled.{" "}
              <Link to={ordersHref} className="adm-card__link">
                Back to orders
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
