import { useEffect, useState } from "react";
import { fetchDashboard } from "./adminApi.js";
import { Link, useNavigate } from "react-router-dom";
import "./admin-dashboard.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";

const NAV_ITEMS = [
  { label: "Dashboard", icon: iconDashboard, href: "/admin/dashboard" },
  { label: "Orders", icon: iconOrders, href: "/admin/orders" },
  { label: "Calendar", icon: iconCalendar, href: "/admin/calendar" },
  { label: "Inventory", icon: iconInventory, href: "/admin/inventory" },
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AdminNav({ activeRoute }) {
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
            const isActive = item.href === activeRoute;
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

      <div className="adm-nav__note" aria-label="Workspace info">
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

function StatCard({ label, value, sub, color }) {
  return (
    <div
      className={`adm-stat-card adm-stat-card--${color}`}
      role="region"
      aria-label={label}
    >
      <p className="adm-stat-card__label">{label}</p>
      <p className="adm-stat-card__value" aria-live="polite">
        {value}
      </p>
      <p className="adm-stat-card__sub">{sub}</p>
    </div>
  );
}

function UpcomingEventsCard({ events, total }) {
  return (
    <section
      className="adm-card adm-card--outlined adm-card--events"
      aria-labelledby="upcoming-events-heading"
    >
      <div className="adm-card__header">
        <h2 className="adm-card__title" id="upcoming-events-heading">
          UPCOMING EVENTS
        </h2>
        <Link to="/admin/calendar" className="adm-card__link">
          View calendar ↗
        </Link>
      </div>

      <ul className="adm-event-list" role="list">
        {events.length === 0 && (
          <li>No confirmed events in the next 30 days.</li>
        )}
        {events.map((event, index) => (
          <li key={event.id} className="adm-event-row">
            {index > 0 && (
              <div className="adm-event-row__divider" role="separator" />
            )}
            <div className="adm-event-row__inner">
              <div
                className="adm-event-date"
                aria-label={`${event.month} ${event.day}`}
              >
                <span>{event.month}</span>
                <span>{event.day}</span>
              </div>
              <div className="adm-event-info">
                <p className="adm-event-info__name">
                  <Link className="adm-card__link" to={event.href}>
                    {event.customer}
                  </Link>
                </p>
                <p className="adm-event-info__detail">
                  {event.service} · {event.qty} paletas
                </p>
              </div>
              <p className="adm-event-time">{event.time}</p>
            </div>
          </li>
        ))}
      </ul>

      {total > events.length && (
        <p className="adm-card__more-link">
          + {total - events.length} more confirmed events in the next 30 days
        </p>
      )}
    </section>
  );
}

function AttentionCard({ items }) {
  return (
    <section
      className="adm-card adm-card--yellow adm-card--attention"
      aria-labelledby="attention-heading"
    >
      <h2 className="adm-card__title" id="attention-heading">
        NEEDS A LITTLE LOVE
      </h2>

      <ul className="adm-attention-list" role="list">
        {items.map((item) => (
          <li key={item.id} className="adm-attention-item">
            <p className="adm-attention-item__count-label">
              <span className="adm-attention-item__count">{item.count}</span>
              {"  "}
              {item.label}
            </p>
            <Link to={item.href} className="adm-attention-item__link">
              {item.link}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecentOrdersTable({ orders }) {
  return (
    <section
      className="adm-card adm-card--outlined adm-card--orders"
      aria-labelledby="recent-orders-heading"
    >
      <div className="adm-card__header">
        <h2 className="adm-card__title" id="recent-orders-heading">
          RECENT ORDERS
        </h2>
        <Link to="/admin/orders" className="adm-card__link">
          All orders ↗
        </Link>
      </div>

      <div
        className="adm-table-wrap"
        role="region"
        aria-label="Recent orders table"
        tabIndex={0}
      >
        <table className="adm-orders-table">
          <thead>
            <tr>
              <th scope="col">ORDER</th>
              <th scope="col">CUSTOMER</th>
              <th scope="col">EVENT DATE</th>
              <th scope="col">SERVICE</th>
              <th scope="col">QTY</th>
              <th scope="col">STATUS</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && (
              <tr>
                <td colSpan={6}>No customer orders yet.</td>
              </tr>
            )}
            {orders.map((order) => (
              <tr key={order.id}>
                <td>
                  <Link
                    to={`/admin/orders/${encodeURIComponent(order.id)}`}
                    className="adm-card__link"
                  >
                    {order.id}
                  </Link>
                </td>
                <td className="adm-orders-table__customer">{order.customer}</td>
                <td>{order.date}</td>
                <td>{order.service}</td>
                <td>{order.qty}</td>
                <td>
                  <span
                    className={`adm-status adm-status--${order.orderStatus}`}
                  >
                    {order.orderStatusLabel}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="adm-orders-table__note">
        Stock is reserved through explicit flavor allocations for confirmed
        bookings.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page header
// ---------------------------------------------------------------------------

function PageHeader({ title }) {
  return (
    <header className="adm-page-header">
      <p className="adm-page-header__title">{title}</p>
      <div className="adm-page-header__actions">
        <a href="/" className="adm-page-header__view-site">
          View website ↗
        </a>
        <Link to="/admin" className="adm-btn adm-btn--outline">
          Owner account
        </Link>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AdminDashboardPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    fetchDashboard()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  const cards = data
    ? [
        {
          id: "catering-requests",
          label: "New catering requests",
          value: data.requests,
          sub: "Awaiting availability review",
          color: "pink",
        },
        {
          id: "upcoming-events",
          label: "Upcoming events",
          value: data.upcoming_count,
          sub: `Next 30 days · ${data.upcoming_quantity} paletas`,
          color: "yellow",
        },
        {
          id: "outstanding-balances",
          label: "Outstanding balances",
          value: data.balances.length
            ? data.balances
                .map((b) =>
                  new Intl.NumberFormat("en-US", {
                    style: "currency",
                    currency: b.currency,
                  }).format(b.remaining_cents / 100),
                )
                .join(" / ")
            : "None",
          sub: "Remaining on confirmed bookings",
          color: "softpink",
        },
        {
          id: "low-stock",
          label: "Low-stock items",
          value: data.low_stock ?? "Unavailable",
          sub: "Available below minimum",
          color: "pink",
        },
      ]
    : [];
  const attention = data
    ? [
        {
          id: "requests",
          count: data.requests,
          label: "Requests awaiting approval",
          link: "Review requests →",
          href: "/admin/orders?status=pending",
        },
        {
          id: "deposits",
          count: data.awaiting_deposit,
          label: "Awaiting deposits",
          link: "Check payments →",
          href: "/admin/orders?status=awaiting_deposit",
        },
        {
          id: "review",
          count: data.owner_review,
          label: "Bookings needing owner review",
          link: "Review bookings →",
          href: "/admin/automation",
        },
        {
          id: "stock",
          count: data.low_stock ?? "Unavailable",
          label: "Low-stock items",
          link: "Update inventory →",
          href: "/admin/inventory",
        },
      ]
    : [];
  const today = new Date();
  const dateStr = today.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="/admin/dashboard" />

      <div className="adm-main">
        <PageHeader title="Dashboard" />

        <div className="adm-content">
          {/* Hero heading row */}
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">LET'S GET POPPING.</h1>
              <p className="adm-hero-row__sub">
                {dateStr} · Here&rsquo;s what needs your attention.
              </p>
            </div>
            <button
              type="button"
              className="adm-btn adm-btn--primary"
              onClick={() => navigate("/admin/orders")}
            >
              Review orders ↗
            </button>
          </div>

          {loading && <p role="status">Loading dashboard…</p>}
          {error && (
            <p role="alert">
              Could not load dashboard.{" "}
              <button onClick={() => setAttempt(attempt + 1)}>Try again</button>
            </p>
          )}
          {!loading && !error && data && (
            <>
              {/* Stat cards */}
              <div className="adm-stats-grid" aria-label="At-a-glance stats">
                {cards.map((card) => (
                  <StatCard key={card.id} {...card} />
                ))}
              </div>

              {/* Middle row: events + attention */}
              <div className="adm-mid-row">
                <UpcomingEventsCard
                  events={data.upcoming}
                  total={data.upcoming_count}
                />
                <AttentionCard items={attention} />
              </div>

              {/* Recent orders */}
              <RecentOrdersTable orders={data.recent_orders} />

              {/* Footer note + action */}
              <div className="adm-content__footer">
                <p className="adm-content__footer-note">
                  Stock is reserved through explicit flavor allocations for
                  confirmed bookings.
                </p>
                <button
                  type="button"
                  className="adm-btn adm-btn--outline"
                  onClick={() => navigate("/admin/inventory")}
                >
                  Update inventory ↗
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
