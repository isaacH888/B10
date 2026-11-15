import { Link } from "react-router-dom";
import logoSrc from "../assets/logo.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconBookings from "../assets/admin/icon-bookings.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";

export const NAV_ITEMS = [
  { label: "Dashboard", icon: iconDashboard, href: "/admin/dashboard" },
  { label: "Orders & Bookings", icon: iconOrders, href: "/admin/orders" },
  { label: "Calendar", icon: iconCalendar, href: "/admin/calendar" },
  { label: "Inventory", icon: iconInventory, href: "/admin/inventory" },
];

export function AdminNav({ activeRoute }) {
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
            const isActive = activeRoute
              ? item.href === activeRoute ||
                (item.href === "/admin/orders" &&
                  (activeRoute.startsWith("/admin/orders") ||
                    activeRoute.startsWith("/admin/automation") ||
                    activeRoute.startsWith("/admin/bookings/")))
              : false;
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

export function PageHeader({ title }) {
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
