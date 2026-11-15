import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import "./admin-dashboard.css";
import "./automation.css";
import { AdminNav } from "./AdminNav.jsx";
import { fetchOrders } from "./orderApi.js";
import { downloadOrders } from "./adminApi.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiRequest, navigateToProvider } from "../auth/api.js";
import {
  GoogleCalendarBox,
  CustomerOrder,
  ManualBookingForm,
} from "./BookingsPage.jsx";

function eventBounds(from, through) {
  const bounds = {};
  if (from) bounds.event_from = new Date(`${from}T00:00:00`).toISOString();
  if (through) {
    const end = new Date(`${through}T00:00:00`);
    end.setDate(end.getDate() + 1);
    bounds.event_to = end.toISOString();
  }
  return bounds;
}

const money = (value, currency = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    (value || 0) / 100,
  );

export function OrdersPage() {
  const [params] = useSearchParams();
  const { sessions } = useAuth();
  const canExport =
    sessions.admin.data.administrator.permissions.includes("customers:export");
  const [orders, setOrders] = useState([]);
  const [loadState, setLoadState] = useState("loading");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(() =>
    [
      "pending",
      "awaiting_deposit",
      "confirmed",
      "owner_review",
      "fulfilled",
      "cancelled",
    ].includes(params.get("status"))
      ? params.get("status")
      : "",
  );
  const [paymentFilter, setPaymentFilter] = useState("");
  const [serviceFilter, setServiceFilter] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [storage, setStorage] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [throughDate, setThroughDate] = useState("");
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState(null);
  const [exportBusy, setExportBusy] = useState(false);
  const latestRequest = useRef(0);
  const [activeTab, setActiveTab] = useState(
    () => params.get("tab") || "orders",
  );

  const isOwner = sessions.admin?.data?.administrator?.role === "owner";
  const csrfToken = sessions.admin?.data?.csrf_token;
  const [connection, setConnection] = useState(null);
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [intakeOrders, setIntakeOrders] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [bookingStatusFilter, setBookingStatusFilter] = useState("all");
  const [automationBusy, setAutomationBusy] = useState(false);

  const refreshAutomation = useCallback(async () => {
    if (!isOwner) return;
    setConnectionLoading(true);
    setConnectionError("");
    try {
      const [googleRes, intakeRes, bookingsRes] = await Promise.allSettled([
        apiRequest("/admin/automation/google"),
        apiRequest("/admin/automation/orders"),
        apiRequest("/admin/automation/bookings"),
      ]);
      if (googleRes.status === "fulfilled") {
        setConnection(googleRes.value);
      } else if (googleRes.reason?.status !== 401) {
        setConnectionError(
          googleRes.reason?.serverMessage ||
            "Could not load Google Calendar status.",
        );
      }
      if (intakeRes.status === "fulfilled") {
        setIntakeOrders(intakeRes.value);
      }
      if (bookingsRes.status === "fulfilled") {
        setBookings(bookingsRes.value || []);
      }
    } catch {
      // Ignored if unauthenticated or not configured
    } finally {
      setConnectionLoading(false);
    }
  }, [isOwner]);

  const filteredBookings = bookings.filter((b) => {
    if (bookingStatusFilter === "all") return true;
    return b.status === bookingStatusFilter;
  });

  useEffect(() => {
    if (isOwner) {
      refreshAutomation();
    }
  }, [isOwner, refreshAutomation]);

  const mutateAutomation = async (path, body = {}) => {
    setAutomationBusy(true);
    if (path.startsWith("/google/")) setConnectionError("");
    try {
      const result = await apiRequest(`/admin/automation${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(body),
      });
      if (result.authorization_url) {
        navigateToProvider(result.authorization_url);
      } else {
        await refreshAutomation();
        await load();
      }
      return true;
    } catch (failure) {
      if (path.startsWith("/google/")) {
        setConnectionError(
          failure.serverMessage || "Google Calendar action failed.",
        );
      } else {
        setError(failure.serverMessage || "Action failed.");
      }
      return false;
    } finally {
      setAutomationBusy(false);
    }
  };

  const createManualBooking = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const rawTotal = String(form.get("total_minor") || "")
      .trim()
      .replace(/^\$/, "");
    const totalMinor = rawTotal.includes(".")
      ? Math.round(parseFloat(rawTotal) * 100)
      : Number(rawTotal);

    const ok = await mutateAutomation("/bookings", {
      start: form.get("start"),
      end: form.get("end"),
      timezone: form.get("timezone"),
      venue: form.get("venue"),
      quantity: Number(form.get("quantity")),
      total_minor: totalMinor,
      currency: form.get("currency"),
      service_type: form.get("service_type"),
      customer_email: form.get("customer_email"),
      contract_url: form.get("contract_url"),
    });
    if (ok) event.currentTarget.reset();
  };

  const load = useCallback(async () => {
    const version = ++latestRequest.current;
    setLoadState("loading");
    setError("");
    if (fromDate && throughDate && fromDate > throughDate) {
      setError("The end date must be on or after the start date.");
      setLoadState("error");
      return;
    }
    try {
      const {
        orders: data,
        total: count,
        storage: mode,
      } = await fetchOrders({
        q: search,
        status: statusFilter,
        payment_status: paymentFilter,
        service_type: serviceFilter,
        page,
        page_size: 25,
        ...eventBounds(fromDate, throughDate),
      });
      if (version !== latestRequest.current) return;
      setOrders(data);
      setTotal(count);
      setStorage(mode);
      setLoadState("ready");
    } catch (failure) {
      if (version !== latestRequest.current) return;
      setLoadState("error");
      setError(failure.serverMessage || "Could not load orders.");
    }
  }, [
    search,
    statusFilter,
    paymentFilter,
    serviceFilter,
    page,
    fromDate,
    throughDate,
  ]);

  async function handleExport() {
    setExportBusy(true);
    setExportError(null);
    try {
      await downloadOrders({
        q: search,
        status: statusFilter,
        payment_status: paymentFilter,
        service_type: serviceFilter,
        ...eventBounds(fromDate, throughDate),
      });
    } catch (failure) {
      setExportError(failure);
    } finally {
      setExportBusy(false);
    }
  }

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => {
      clearTimeout(timer);
      latestRequest.current += 1;
    };
  }, [load]);

  const requests = orders.filter((o) => o.orderStatus === "pending").length;
  const confirmed = orders.filter((o) => o.orderStatus === "confirmed").length;

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="/admin/orders" />

      <div className="adm-main">
        <header className="adm-page-header">
          <p className="adm-page-header__title">Orders &amp; Bookings</p>
          <div className="adm-page-header__actions">
            <a href="/" className="adm-page-header__view-site">
              View website ↗
            </a>
            <Link to="/admin" className="adm-btn adm-btn--outline">
              Owner account
            </Link>
            <button
              className="adm-btn adm-btn--outline"
              disabled={!canExport || exportBusy || loadState !== "ready"}
              onClick={handleExport}
            >
              {exportBusy ? "Exporting…" : "Export filtered orders"}
            </button>
          </div>
        </header>

        <div className="adm-content">
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">
                GOOD THINGS IN THE WORKS.
              </h1>
              <p className="adm-hero-row__sub">
                Requests, bookings, and external payments – all in one place.
              </p>
            </div>
          </div>

          {/* Sub-tabs Navigation: Orders | Bookings | Connection */}
          {isOwner && (
            <div
              className="bkg-filter-tabs"
              role="tablist"
              aria-label="Orders and bookings workspace views"
              style={{ marginBottom: 0 }}
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "orders"}
                className={`bkg-filter-btn ${activeTab === "orders" ? "bkg-filter-btn--active" : ""}`}
                onClick={() => setActiveTab("orders")}
                style={{ fontWeight: 700 }}
              >
                Orders
              </button>

              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "bookings"}
                className={`bkg-filter-btn ${activeTab === "bookings" ? "bkg-filter-btn--active" : ""}`}
                onClick={() => setActiveTab("bookings")}
                style={{ fontWeight: 700 }}
              >
                Bookings
              </button>

              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "connection"}
                className={`bkg-filter-btn ${activeTab === "connection" ? "bkg-filter-btn--active" : ""}`}
                onClick={() => setActiveTab("connection")}
                style={{
                  fontWeight: 700,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span>Connection</span>
                {connection?.status === "connected" && (
                  <span
                    className="bkg-badge bkg-sync--synced"
                    style={{ fontSize: 11, padding: "2px 7px" }}
                  >
                    Connected
                  </span>
                )}
                {connection?.status === "reconnect_required" && (
                  <span
                    className="bkg-badge bkg-sync--failed"
                    style={{ fontSize: 11, padding: "2px 7px" }}
                  >
                    Reconnect
                  </span>
                )}
              </button>
            </div>
          )}

          {/* TAB 2: BOOKINGS */}
          {activeTab === "bookings" && isOwner && (
            <section
              aria-label="Catering bookings"
              style={{ marginBottom: 32 }}
            >
              <div className="bkg-section-header">
                <h2 className="bkg-section-title" style={{ fontSize: 18 }}>
                  Catering Bookings
                </h2>
                <span className="ord-count-badge">
                  {filteredBookings.length}{" "}
                  {filteredBookings.length === 1 ? "booking" : "bookings"}
                </span>
              </div>

              {/* Booking status filter buttons */}
              <div className="bkg-filter-tabs" style={{ marginBottom: 16 }}>
                {[
                  { id: "all", label: "All" },
                  { id: "requested", label: "Requested" },
                  { id: "awaiting_deposit", label: "Awaiting deposit" },
                  { id: "confirmed", label: "Confirmed" },
                  { id: "owner_review", label: "Owner review" },
                  { id: "fulfilled", label: "Fulfilled" },
                  { id: "cancelled", label: "Cancelled" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    className={`bkg-filter-btn ${bookingStatusFilter === tab.id ? "bkg-filter-btn--active" : ""}`}
                    onClick={() => setBookingStatusFilter(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div
                className="adm-table-wrap"
                role="region"
                aria-label="Catering bookings table"
                tabIndex={0}
              >
                <table className="adm-orders-table">
                  <thead>
                    <tr>
                      <th scope="col">REFERENCE</th>
                      <th scope="col">BOOKING STATUS</th>
                      <th scope="col">PAYMENT STATUS</th>
                      <th scope="col">REMAINING BALANCE</th>
                      <th scope="col">CALENDAR SYNC</th>
                      <th scope="col">DETAILS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredBookings.length === 0 ? (
                      <tr>
                        <td
                          colSpan={6}
                          style={{
                            textAlign: "center",
                            padding: 24,
                            color: "#6b7280",
                          }}
                        >
                          No catering bookings match this filter.
                        </td>
                      </tr>
                    ) : (
                      filteredBookings.map((b) => (
                        <tr key={b.id}>
                          <td>
                            <Link
                              to={`/admin/bookings/${b.id}`}
                              className="adm-card__link"
                              style={{ fontWeight: 700 }}
                            >
                              {b.reference}
                            </Link>
                          </td>
                          <td>
                            <span
                              className={`bkg-badge bkg-badge--${b.status}`}
                            >
                              {b.status}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`bkg-badge bkg-pay--${b.payment_status}`}
                            >
                              {b.payment_status}
                            </span>
                          </td>
                          <td style={{ fontWeight: 700 }}>
                            {money(b.remaining_minor, b.currency)}
                          </td>
                          <td>
                            <span
                              className={`bkg-badge bkg-sync--${b.calendar_status}`}
                            >
                              {b.calendar_status}
                            </span>
                          </td>
                          <td>
                            <Link
                              to={`/admin/bookings/${b.id}`}
                              className="adm-card__link"
                              style={{ fontWeight: 700, whiteSpace: "nowrap" }}
                            >
                              View details ↗
                            </Link>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Add manual booking */}
              <div style={{ marginTop: 24 }}>
                <ManualBookingForm
                  busy={automationBusy}
                  create={createManualBooking}
                />
              </div>
            </section>
          )}

          {/* TAB 3: CONNECTION */}
          {activeTab === "connection" && isOwner && (
            <div style={{ marginBottom: 32 }}>
              <GoogleCalendarBox
                connection={connection}
                connectionLoading={connectionLoading}
                connectionError={connectionError}
                busy={automationBusy}
                mutate={mutateAutomation}
                refresh={refreshAutomation}
              />
            </div>
          )}

          {/* TAB 1: ORDERS TABLE */}
          {activeTab === "orders" && (
            <>
              {loadState === "loading" && (
                <p role="status" style={{ fontFamily: "'DM Sans',sans-serif" }}>
                  Loading orders…
                </p>
              )}
              {loadState === "error" && (
                <p role="alert" style={{ fontFamily: "'DM Sans',sans-serif" }}>
                  {error}{" "}
                  <button
                    onClick={load}
                    style={{ fontFamily: "inherit", cursor: "pointer" }}
                  >
                    Try again
                  </button>
                </p>
              )}
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

              {loadState === "ready" && (
                <>
                  {/* Attention banner */}
                  <div className="ord-alert" role="status">
                    <p className="ord-alert__main">
                      {total} matching customer{" "}
                      {total === 1 ? "order" : "orders"}
                    </p>
                    <p className="ord-alert__sub">
                      {storage === "memory"
                        ? "Temporary development storage. These orders will not survive a backend restart."
                        : "Saved requests and linked bookings. Open an order to review its current status."}
                    </p>
                  </div>

                  {/* Search + filters */}
                  <div className="ord-filters-panel">
                    <div className="ord-filters-top">
                      <input
                        type="search"
                        className="inv-search"
                        placeholder="Search customer or order number…"
                        value={search}
                        onChange={(e) => {
                          setSearch(e.target.value);
                          setPage(1);
                        }}
                        maxLength={150}
                        aria-label="Search orders"
                      />
                      <div className="ord-filter-counts">
                        <span className="ord-count-badge">
                          ON THIS PAGE · {orders.length}
                        </span>
                        <span className="ord-filter-breakdown">
                          Requests {requests} &nbsp;&nbsp; Confirmed {confirmed}
                        </span>
                      </div>
                    </div>

                    <div className="ord-filters-row">
                      <div className="ord-filter-group">
                        <label htmlFor="ord-from" className="ord-filter-label">
                          EVENT DATES (FROM → TO)
                        </label>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          <input
                            id="ord-from"
                            className="ord-select"
                            type="date"
                            aria-label="Event date from"
                            title="Start date (From)"
                            value={fromDate}
                            onChange={(e) => {
                              setFromDate(e.target.value);
                              setPage(1);
                            }}
                          />
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 700,
                              color: "#4b004b",
                            }}
                          >
                            to
                          </span>
                          <input
                            id="ord-through"
                            className="ord-select"
                            type="date"
                            aria-label="Event date through"
                            title="End date (To)"
                            min={fromDate}
                            value={throughDate}
                            onChange={(e) => {
                              setThroughDate(e.target.value);
                              setPage(1);
                            }}
                          />
                        </div>
                      </div>
                      <div className="ord-filter-group">
                        <label
                          htmlFor="ord-status"
                          className="ord-filter-label"
                        >
                          ORDER STATUS
                        </label>
                        <select
                          id="ord-status"
                          className="ord-select"
                          value={statusFilter}
                          onChange={(e) => {
                            setStatusFilter(e.target.value);
                            setPage(1);
                          }}
                          aria-label="Filter by order status"
                        >
                          <option value="">All order statuses ⌄</option>
                          <option value="pending">Pending request</option>
                          <option value="confirmed">Confirmed</option>
                          <option value="awaiting_deposit">
                            Awaiting deposit
                          </option>
                          <option value="owner_review">Owner review</option>
                          <option value="fulfilled">Fulfilled</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                      </div>
                      <div className="ord-filter-group">
                        <label
                          htmlFor="ord-payment"
                          className="ord-filter-label"
                        >
                          PAYMENT STATUS
                        </label>
                        <select
                          id="ord-payment"
                          className="ord-select"
                          value={paymentFilter}
                          onChange={(e) => {
                            setPaymentFilter(e.target.value);
                            setPage(1);
                          }}
                          aria-label="Filter by payment status"
                        >
                          <option value="">All payment statuses ⌄</option>
                          <option value="unpaid">Unpaid</option>
                          <option value="partial">Part paid</option>
                          <option value="paid">Paid in full</option>
                        </select>
                      </div>
                      <div className="ord-filter-group">
                        <label
                          htmlFor="ord-service"
                          className="ord-filter-label"
                        >
                          SERVICE TYPE
                        </label>
                        <select
                          id="ord-service"
                          className="ord-select"
                          aria-label="Filter by service type"
                          value={serviceFilter}
                          onChange={(e) => {
                            setServiceFilter(e.target.value);
                            setPage(1);
                          }}
                        >
                          <option value="">Delivery &amp; Full Service</option>
                          <option value="delivery">Delivery</option>
                          <option value="full_service">Full Service</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Orders table */}
                  <section
                    className="adm-card adm-card--outlined"
                    aria-labelledby="orders-table-heading"
                  >
                    <h2 className="visually-hidden" id="orders-table-heading">
                      Order management
                    </h2>
                    <div
                      className="adm-table-wrap"
                      role="region"
                      aria-label="Orders table"
                      tabIndex={0}
                    >
                      <table className="adm-orders-table ord-table">
                        <thead>
                          <tr>
                            <th scope="col">ORDER #</th>
                            <th scope="col">CUSTOMER</th>
                            <th scope="col">EVENT DATE</th>
                            <th scope="col">SERVICE</th>
                            <th scope="col">QTY</th>
                            <th scope="col">ORDER STATUS</th>
                            <th scope="col">PAYMENT STATUS</th>
                            <th scope="col">TOTAL</th>
                            <th scope="col">DETAILS</th>
                          </tr>
                        </thead>
                        <tbody>
                          {orders.length === 0 && (
                            <tr>
                              <td colSpan={9}>
                                No customer orders match these filters.
                              </td>
                            </tr>
                          )}
                          {orders.map((order) => (
                            <tr key={order.id}>
                              <td>{order.id}</td>
                              <td className="adm-orders-table__customer">
                                {order.customer}
                              </td>
                              <td>{order.date}</td>
                              <td>{order.service}</td>
                              <td>{order.qty}</td>
                              <td>
                                <span
                                  className={`ord-status ord-status--${order.orderStatus}`}
                                >
                                  {order.orderStatusLabel}
                                </span>
                              </td>
                              <td>
                                <span
                                  className={`ord-payment ord-payment--${order.paymentStatus}`}
                                >
                                  {order.paymentStatusLabel}
                                </span>
                                <br />
                                <span className="ord-payment-sub">
                                  {order.paymentSub}
                                </span>
                              </td>
                              <td>{order.total}</td>
                              <td>
                                <Link
                                  to={`/admin/orders/${encodeURIComponent(order.id)}`}
                                  className="adm-card__link"
                                >
                                  View details ↗
                                </Link>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                  <nav aria-label="Order pages" className="actions">
                    <button
                      className="adm-btn adm-btn--outline"
                      disabled={page === 1}
                      onClick={() => setPage(page - 1)}
                    >
                      Previous
                    </button>
                    <span>
                      Page {page} of {Math.max(1, Math.ceil(total / 25))}
                    </span>
                    <button
                      className="adm-btn adm-btn--outline"
                      disabled={page * 25 >= total}
                      onClick={() => setPage(page + 1)}
                    >
                      Next
                    </button>
                  </nav>

                  <p className="adm-content__footer-note">
                    Booking, payment, and sync are independent. Click "View
                    details" to manage an individual order.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
