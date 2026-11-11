import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import "./admin-dashboard.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";
import { fetchOrders } from "./adminApi.js";

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
          {NAV_ITEMS.map((item) => {
            const isActive = item.href === "/admin/orders";
            return (
              <li key={item.label}>
                <Link
                  to={item.href}
                  className={
                    isActive
                      ? "adm-nav__link adm-nav__link--active"
                      : "adm-nav__link"
                  }
                  aria-current={isActive ? "page" : undefined}
                >
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
            );
          })}
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

export function OrdersPage() {
  const [orders, setOrders] = useState([]);
  const [loadState, setLoadState] = useState("loading");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [paymentFilter, setPaymentFilter] = useState("");

  const load = useCallback(async () => {
    setLoadState("loading");
    try {
      const { orders: data } = await fetchOrders();
      setOrders(data);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const requests = orders.filter((o) => o.orderStatus === "pending").length;
  const confirmed = orders.filter((o) => o.orderStatus === "confirmed").length;

  const filtered = orders.filter((o) => {
    const matchSearch =
      o.customer.toLowerCase().includes(search.toLowerCase()) ||
      o.id.toLowerCase().includes(search.toLowerCase());
    const matchStatus = !statusFilter || o.orderStatus === statusFilter;
    const matchPayment = !paymentFilter || o.paymentStatus === paymentFilter;
    return matchSearch && matchStatus && matchPayment;
  });

  return (
    <div className="adm-shell">
      <AdminNav />

      <div className="adm-main">
        <header className="adm-page-header">
          <p className="adm-page-header__title">Orders</p>
          <div className="adm-page-header__actions">
            <a href="/" className="adm-page-header__view-site">
              View website ↗
            </a>
            <Link to="/admin" className="adm-btn adm-btn--outline">
              Owner account
            </Link>
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

          {loadState === "loading" && (
            <p role="status" style={{ fontFamily: "'DM Sans',sans-serif" }}>
              Loading orders…
            </p>
          )}
          {loadState === "error" && (
            <p role="alert" style={{ fontFamily: "'DM Sans',sans-serif" }}>
              Could not load orders.{" "}
              <button
                onClick={load}
                style={{ fontFamily: "inherit", cursor: "pointer" }}
              >
                Try again
              </button>
            </p>
          )}

          {loadState === "ready" && (
            <>
              {/* Attention banner */}
              <div className="ord-alert" role="status">
                <p className="ord-alert__main">
                  {requests} awaiting approval &nbsp;·&nbsp; $1,860 remaining
                  across 5 bookings
                </p>
                <p className="ord-alert__sub">
                  Existing bookings have verified deposits. Any payments
                  awaiting review are additional payments.
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
                    onChange={(e) => setSearch(e.target.value)}
                    aria-label="Search orders"
                  />
                  <div className="ord-filter-counts">
                    <span className="ord-count-badge">
                      ALL ORDERS · {orders.length}
                    </span>
                    <span className="ord-filter-breakdown">
                      Requests {requests} &nbsp;&nbsp; Confirmed {confirmed}
                    </span>
                  </div>
                </div>

                <div className="ord-filters-row">
                  <div className="ord-filter-group">
                    <label htmlFor="ord-date" className="ord-filter-label">
                      DATE RANGE
                    </label>
                    <select
                      id="ord-date"
                      className="ord-select"
                      aria-label="Filter by date range"
                    >
                      <option>Nov 1 – Nov 30, 2026 ⌄</option>
                    </select>
                  </div>
                  <div className="ord-filter-group">
                    <label htmlFor="ord-status" className="ord-filter-label">
                      ORDER STATUS
                    </label>
                    <select
                      id="ord-status"
                      className="ord-select"
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      aria-label="Filter by order status"
                    >
                      <option value="">All order statuses ⌄</option>
                      <option value="pending">Pending request</option>
                      <option value="confirmed">Confirmed</option>
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
                      onChange={(e) => setPaymentFilter(e.target.value)}
                      aria-label="Filter by payment status"
                    >
                      <option value="">All payment statuses ⌄</option>
                      <option value="unpaid">Unpaid</option>
                      <option value="partial">50% verified</option>
                      <option value="review">Part paid · Review</option>
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
                    >
                      <option>Delivery &amp; Full Service ⌄</option>
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
                      {filtered.map((order) => (
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

              <p className="adm-content__footer-note">
                Booking, payment, and sync are independent. Click "View details"
                to manage an individual order.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
