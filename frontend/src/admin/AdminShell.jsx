import { useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import logoSrc from "../assets/logo.png";
import paletasSrc from "../assets/paletas-flavor-preview.png";
import iconDashboard from "../assets/admin/icon-dashboard.svg";
import iconOrders from "../assets/admin/icon-orders.svg";
import iconCalendar from "../assets/admin/icon-calendar.svg";
import iconInventory from "../assets/admin/icon-inventory.svg";
import "./admin-dashboard.css";
import "./admin-shell.css";

const pages = [
  { label: "Dashboard", href: "/admin/dashboard", icon: iconDashboard },
  { label: "Orders", href: "/admin/orders", icon: iconOrders },
  { label: "Bookings", href: "/admin/automation", icon: iconOrders },
  { label: "Calendar", href: "/admin/calendar", icon: iconCalendar },
  { label: "Inventory", href: "/admin/inventory", icon: iconInventory },
];

export function AdminNav({ activeRoute }) {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const navId = useId();
  const toggle = useRef(null);
  const current = pathname.startsWith("/admin/bookings/")
    ? "/admin/automation"
    : activeRoute || pathname;

  useEffect(() => setOpen(false), [pathname]);

  function closeOnEscape(event) {
    if (event.key === "Escape" && open) {
      setOpen(false);
      toggle.current?.focus();
    }
  }

  return (
    <aside
      className="adm-nav adm-nav--shared"
      aria-label="Admin navigation"
      onKeyDown={closeOnEscape}
    >
      <div className="adm-nav__mobile-header">
        <Link
          to="/admin/dashboard"
          className="adm-nav__brand"
          aria-label="Popssibilities admin dashboard"
        >
          <img
            src={logoSrc}
            alt="Popssibilities logo"
            className="adm-nav__logo"
            width={48}
            height={44}
          />
          <div>
            <p className="adm-nav__site-name">POPSSIBILITIES</p>
            <p className="adm-nav__area">BUSINESS ADMIN</p>
          </div>
        </Link>
        <button
          ref={toggle}
          type="button"
          className="adm-nav__toggle"
          aria-label={open ? "Close admin navigation" : "Open admin navigation"}
          aria-expanded={open}
          aria-controls={navId}
          onClick={() => setOpen((value) => !value)}
        >
          <span aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d={open ? "M6 6l12 12M6 18L18 6" : "M4 6h16M4 12h16M4 18h16"}
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
              />
            </svg>
          </span>
          Menu
        </button>
      </div>
      <nav
        id={navId}
        aria-label="Admin pages"
        className="adm-nav__pages"
        data-open={open}
      >
        <ul className="adm-nav__list" role="list">
          {pages.map((page) => {
            const active = current === page.href;
            return (
              <li key={page.href}>
                <Link
                  to={page.href}
                  className={`adm-nav__link${active ? " adm-nav__link--active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setOpen(false)}
                >
                  <img
                    src={page.icon}
                    alt=""
                    aria-hidden="true"
                    className="adm-nav__icon"
                    width={22}
                    height={22}
                  />
                  {page.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="adm-nav__note" aria-label="Workspace info">
        <img src={paletasSrc} alt="" width={96} height={108} />
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

export function AdminPageHeader({ title, children }) {
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
        {children}
      </div>
    </header>
  );
}

export function AdminShell({ activeRoute, title, actions, children }) {
  return (
    <div className="adm-shell">
      <AdminNav activeRoute={activeRoute} />
      <div className="adm-main">
        <AdminPageHeader title={title}>{actions}</AdminPageHeader>
        <main className="adm-content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
