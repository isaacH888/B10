import { Link, useNavigate } from "react-router-dom";
import "./admin-dashboard.css";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";

// ---------------------------------------------------------------------------
// Data — static sample data matching the Figma design
// ---------------------------------------------------------------------------

const STAT_CARDS = [
  {
    id: "catering-requests",
    label: "New catering requests",
    value: "3",
    sub: "Awaiting your approval",
    color: "pink",
  },
  {
    id: "upcoming-events",
    label: "Upcoming events",
    value: "6",
    sub: "Through Nov 15 · 680 paletas",
    color: "yellow",
  },
  {
    id: "outstanding-balances",
    label: "Outstanding balances",
    value: "$1,860",
    sub: "Across 5 confirmed orders",
    color: "softpink",
  },
  {
    id: "low-stock",
    label: "Low-stock items",
    value: "3",
    sub: "Available below minimum",
    color: "pink",
  },
];

const UPCOMING_EVENTS = [
  {
    id: "e1",
    month: "NOV",
    day: "07",
    customer: "Elena Martinez",
    service: "Full Service",
    qty: 150,
    time: "Sat, 2:00–4:00 PM",
  },
  {
    id: "e2",
    month: "NOV",
    day: "08",
    customer: "Bayou Creative",
    service: "Delivery",
    qty: 120,
    time: "Sun, 11:00 AM",
  },
  {
    id: "e3",
    month: "NOV",
    day: "10",
    customer: "Priya Patel",
    service: "Full Service",
    qty: 100,
    time: "Tue, 3:00–5:00 PM",
  },
];

const ATTENTION_ITEMS = [
  {
    id: "a1",
    count: "03",
    label: "Requests awaiting approval",
    link: "Review requests →",
    href: "/admin/orders",
  },
  {
    id: "a2",
    count: "02",
    label: "Unverified deposits",
    link: "Check payments →",
    href: "/admin/orders",
  },
  {
    id: "a3",
    count: "03",
    label: "Inventory shortages",
    link: "Update inventory →",
    href: "/admin/inventory",
  },
];

const RECENT_ORDERS = [
  {
    id: "#1048",
    customer: "Sofia Ramirez",
    eventDate: "Nov 21",
    service: "Delivery",
    qty: 200,
    status: "Awaiting approval",
    statusType: "pending",
  },
  {
    id: "#1047",
    customer: "Oakwood PTA",
    eventDate: "Nov 20",
    service: "Full Service",
    qty: 150,
    status: "Awaiting approval",
    statusType: "pending",
  },
  {
    id: "#1046",
    customer: "James Wilson",
    eventDate: "Nov 18",
    service: "Delivery",
    qty: 80,
    status: "Awaiting approval",
    statusType: "pending",
  },
  {
    id: "#1045",
    customer: "Elena Martinez",
    eventDate: "Nov 07",
    service: "Full Service",
    qty: 150,
    status: "Confirmed",
    statusType: "confirmed",
  },
];

// ---------------------------------------------------------------------------
// Nav items
// ---------------------------------------------------------------------------

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

function UpcomingEventsCard() {
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
        {UPCOMING_EVENTS.map((event, index) => (
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
                <p className="adm-event-info__name">{event.customer}</p>
                <p className="adm-event-info__detail">
                  {event.service} · {event.qty} paletas
                </p>
              </div>
              <p className="adm-event-time">{event.time}</p>
            </div>
          </li>
        ))}
      </ul>

      <p className="adm-card__more-link">
        + 3 more confirmed events this month
      </p>
    </section>
  );
}

function AttentionCard() {
  return (
    <section
      className="adm-card adm-card--yellow adm-card--attention"
      aria-labelledby="attention-heading"
    >
      <h2 className="adm-card__title" id="attention-heading">
        NEEDS A LITTLE LOVE
      </h2>

      <ul className="adm-attention-list" role="list">
        {ATTENTION_ITEMS.map((item) => (
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

function RecentOrdersTable() {
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
            {RECENT_ORDERS.map((order) => (
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
                <td>{order.eventDate}</td>
                <td>{order.service}</td>
                <td>{order.qty}</td>
                <td>
                  <span
                    className={`adm-status adm-status--${order.statusType}`}
                  >
                    {order.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="adm-orders-table__note">
        Inventory is reserved for confirmed events only. New requests do not
        reduce available stock.
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
        <button type="button" className="adm-btn adm-btn--outline">
          Owner account ⌄
        </button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AdminDashboardPage() {
  const navigate = useNavigate();
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

          {/* Stat cards */}
          <div className="adm-stats-grid" aria-label="At-a-glance stats">
            {STAT_CARDS.map((card) => (
              <StatCard key={card.id} {...card} />
            ))}
          </div>

          {/* Middle row: events + attention */}
          <div className="adm-mid-row">
            <UpcomingEventsCard />
            <AttentionCard />
          </div>

          {/* Recent orders */}
          <RecentOrdersTable />

          {/* Footer note + action */}
          <div className="adm-content__footer">
            <p className="adm-content__footer-note">
              Inventory is reserved for confirmed events only. New requests do
              not reduce available stock.
            </p>
            <button
              type="button"
              className="adm-btn adm-btn--outline"
              onClick={() => navigate("/admin/inventory")}
            >
              Update inventory ↗
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
