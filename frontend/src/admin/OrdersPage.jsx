import { AdminNav, AdminPageHeader } from "./AdminShell.jsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import "./admin-dashboard.css";
import { fetchOrders } from "./orderApi.js";
import { downloadOrders } from "./adminApi.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { AdminRefreshStatus, useAdminRefresh } from "./useAdminRefresh.jsx";

function dateParam(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
    ? value
    : "";
}

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

export function OrdersPage() {
  const [params, setParams] = useSearchParams();
  const { sessions } = useAuth();
  const canExport =
    sessions.admin.data.administrator.permissions.includes("customers:export");
  const [orders, setOrders] = useState([]);
  const [loadState, setLoadState] = useState("loading");
  const search = (params.get("q") || "").slice(0, 150);
  const statusFilter = [
    "pending",
    "awaiting_deposit",
    "confirmed",
    "owner_review",
    "fulfilled",
    "cancelled",
  ].includes(params.get("status"))
    ? params.get("status")
    : "";
  const paymentFilter = ["unpaid", "partial", "paid"].includes(
    params.get("payment_status"),
  )
    ? params.get("payment_status")
    : "";
  const serviceFilter = ["delivery", "full_service"].includes(
    params.get("service_type"),
  )
    ? params.get("service_type")
    : "";
  const rawPage = Number(params.get("page") || 1);
  const page =
    Number.isSafeInteger(rawPage) && rawPage > 0 && rawPage <= 10000
      ? rawPage
      : 1;
  const [total, setTotal] = useState(0);
  const [storage, setStorage] = useState("");
  const fromDate = dateParam(params.get("from"));
  const throughDate = dateParam(params.get("through"));
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState(null);
  const [exportBusy, setExportBusy] = useState(false);
  const latestRequest = useRef(0);
  const hasData = useRef(false);

  function updateFilter(key, value) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value && !(key === "page" && Number(value) === 1))
          next.set(key, String(value));
        else next.delete(key);
        if (key !== "page") next.delete("page");
        return next;
      },
      { replace: key !== "page" },
    );
  }

  const load = useCallback(
    async ({ background = false } = {}) => {
      const version = ++latestRequest.current;
      if (!background || !hasData.current) setLoadState("loading");
      setError("");
      if (fromDate && throughDate && fromDate > throughDate) {
        setError("The end date must be on or after the start date.");
        setLoadState("error");
        return false;
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
        if (version !== latestRequest.current) return false;
        const lastPage = Math.max(1, Math.ceil(count / 25));
        if (page > lastPage) {
          setParams(
            (current) => {
              const next = new URLSearchParams(current);
              if (lastPage === 1) next.delete("page");
              else next.set("page", String(lastPage));
              return next;
            },
            { replace: true },
          );
          return;
        }
        setOrders(data);
        setTotal(count);
        setStorage(mode);
        hasData.current = true;
        setLoadState("ready");
      } catch (failure) {
        if (version !== latestRequest.current) return false;
        if (!background || [401, 403].includes(failure.status)) {
          setLoadState("error");
          setError(failure.serverMessage || "Could not load orders.");
          if ([401, 403].includes(failure.status)) {
            setOrders([]);
            hasData.current = false;
          }
        }
        return false;
      }
    },
    [
      search,
      statusFilter,
      paymentFilter,
      serviceFilter,
      page,
      fromDate,
      throughDate,
      setParams,
    ],
  );

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

  const refreshState = useAdminRefresh(load, { debounceMs: 250 });
  useEffect(() => {
    setLoadState("loading");
    return () => {
      latestRequest.current += 1;
    };
  }, [load]);

  const requests = orders.filter((o) => o.orderStatus === "pending").length;
  const confirmed = orders.filter((o) => o.orderStatus === "confirmed").length;

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="/admin/orders" />

      <div className="adm-main">
        <AdminPageHeader title="Orders">
          <AdminRefreshStatus {...refreshState} />
          <button
            className="adm-btn adm-btn--outline"
            disabled={!canExport || exportBusy || loadState !== "ready"}
            onClick={handleExport}
          >
            {exportBusy ? "Exporting…" : "Export filtered orders"}
          </button>
        </AdminPageHeader>

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

          {loadState === "loading" && (
            <p role="status" style={{ fontFamily: "'DM Sans',sans-serif" }}>
              Loading orders…
            </p>
          )}
          {loadState === "error" && (
            <p role="alert" style={{ fontFamily: "'DM Sans',sans-serif" }}>
              {error}{" "}
              <button
                onClick={refreshState.refresh}
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

          <>
            {loadState === "ready" && (
              <>
                {/* Attention banner */}
                <div className="ord-alert" role="status">
                  <p className="ord-alert__main">
                    {total} matching customer {total === 1 ? "order" : "orders"}
                  </p>
                  <p className="ord-alert__sub">
                    {storage === "memory"
                      ? "Temporary development storage. These orders will not survive a backend restart."
                      : "Saved requests and linked bookings. Open an order to review its current status."}
                  </p>
                </div>
              </>
            )}
            {/* Search + filters */}
            <div className="ord-filters-panel">
              <div className="ord-filters-top">
                <input
                  type="search"
                  className="inv-search"
                  placeholder="Search customer or order number…"
                  value={search}
                  onChange={(e) => {
                    updateFilter("q", e.target.value);
                  }}
                  maxLength={150}
                  aria-label="Search orders"
                />
                {(search ||
                  statusFilter ||
                  paymentFilter ||
                  serviceFilter ||
                  fromDate ||
                  throughDate) && (
                  <button
                    type="button"
                    className="adm-btn adm-btn--outline"
                    onClick={() => setParams({}, { replace: true })}
                  >
                    Clear filters
                  </button>
                )}
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
                    EVENT DATES (YOUR LOCAL TIME)
                  </label>
                  <input
                    id="ord-from"
                    className="ord-select"
                    type="date"
                    aria-label="Event date from"
                    value={fromDate}
                    onChange={(e) => {
                      updateFilter("from", e.target.value);
                    }}
                  />
                  <input
                    className="ord-select"
                    type="date"
                    aria-label="Event date through"
                    min={fromDate}
                    value={throughDate}
                    onChange={(e) => {
                      updateFilter("through", e.target.value);
                    }}
                  />
                </div>
                <div className="ord-filter-group">
                  <label htmlFor="ord-status" className="ord-filter-label">
                    ORDER STATUS
                  </label>
                  <select
                    id="ord-status"
                    className="ord-select"
                    value={statusFilter}
                    onChange={(e) => {
                      updateFilter("status", e.target.value);
                    }}
                    aria-label="Filter by order status"
                  >
                    <option value="">All order statuses ⌄</option>
                    <option value="pending">Pending request</option>
                    <option value="confirmed">Confirmed</option>
                    <option value="awaiting_deposit">Awaiting deposit</option>
                    <option value="owner_review">Owner review</option>
                    <option value="fulfilled">Fulfilled</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div className="ord-filter-group">
                  <label htmlFor="ord-payment" className="ord-filter-label">
                    PAYMENT STATUS
                  </label>
                  <select
                    id="ord-payment"
                    className="ord-select"
                    value={paymentFilter}
                    onChange={(e) => {
                      updateFilter("payment_status", e.target.value);
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
                  <label htmlFor="ord-service" className="ord-filter-label">
                    SERVICE TYPE
                  </label>
                  <select
                    id="ord-service"
                    className="ord-select"
                    aria-label="Filter by service type"
                    value={serviceFilter}
                    onChange={(e) => {
                      updateFilter("service_type", e.target.value);
                    }}
                  >
                    <option value="">Delivery &amp; Full Service</option>
                    <option value="delivery">Delivery</option>
                    <option value="full_service">Full Service</option>
                  </select>
                </div>
              </div>
            </div>

            {loadState === "ready" && (
              <>
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
                                state={{ ordersQuery: params.toString() }}
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
                    onClick={() => updateFilter("page", page - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page} of {Math.max(1, Math.ceil(total / 25))}
                  </span>
                  <button
                    className="adm-btn adm-btn--outline"
                    disabled={page * 25 >= total}
                    onClick={() => updateFilter("page", page + 1)}
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
        </div>
      </div>
    </div>
  );
}
