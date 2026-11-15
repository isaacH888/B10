import { Link, useSearchParams } from "react-router-dom";
import { AdminNav, PageHeader } from "./AdminNav.jsx";
import "./admin-dashboard.css";
import "./automation.css";

const LABELS = {
  "bookings:read": "View bookings",
  "bookings:contacts": "View contact details",
  "bookings:notes": "Update booking notes",
  "bookings:fulfill": "Mark fulfillment",
  "bookings:confirm": "Confirm bookings",
  "bookings:cancel": "Cancel bookings",
  "bookings:price": "Update booking prices",
  "payments:manage": "Manage payments",
  "customers:export": "Export customer data",
};

export function AdminAccountPage({
  identity,
  session,
  deadline,
  remaining,
  onLogout,
}) {
  const [params] = useSearchParams();
  const returnTo = params.get("returnTo") || params.get("from");
  const isReauth = Boolean(params.get("reauth"));

  const capabilities = [
    ...new Set(
      identity.permissions
        .map((p) => (Object.hasOwn(LABELS, p) ? LABELS[p] : null))
        .filter(Boolean),
    ),
  ];

  return (
    <div className="adm-shell">
      <AdminNav activeRoute="" />

      <div className="adm-main">
        <PageHeader title="Team Account" />

        <div className="adm-content" style={{ maxWidth: 860 }}>
          {/* Hero row with Anton font */}
          <div className="adm-hero-row">
            <div className="adm-hero-row__text">
              <h1 className="adm-hero-row__heading">Team account</h1>
              <p className="adm-hero-row__sub">
                Welcome{identity.name ? `, ${identity.name}` : ""}. Your
                administrator session is authenticated.
              </p>
            </div>
            <span className="adm-account-role-badge">
              Role: {identity.role}
            </span>
          </div>

          {/* Re-verification or Return-to Notice */}
          {returnTo && (
            <div
              className="od-confirm-banner"
              style={{ background: "#ffadd2", marginBottom: 24 }}
              role="status"
            >
              <p className="od-confirm-banner__heading">
                Owner access verified
              </p>
              <p className="od-confirm-banner__body">
                You can now return to the workflow you were working on. Click
                below to return. Actions and payments are never resubmitted
                automatically.
              </p>
              <div style={{ marginTop: 12 }}>
                <Link to={returnTo} className="adm-btn adm-btn--primary">
                  Continue to originating page ↗
                </Link>
              </div>
            </div>
          )}

          {isReauth && !returnTo && (
            <div
              className="od-confirm-banner"
              style={{ background: "#ffed00", marginBottom: 24 }}
              role="status"
            >
              <p className="od-confirm-banner__heading">Fresh session active</p>
              <p className="od-confirm-banner__body">
                Your credentials and two-factor code have been verified.
                Privileged financial and export operations are unlocked.
              </p>
            </div>
          )}

          {remaining <= 5 && (
            <div
              className="od-confirm-banner"
              style={{ background: "#fee2e2", marginBottom: 24 }}
              role="alert"
            >
              <p className="od-confirm-banner__heading">
                Session expiring soon
              </p>
              <p className="od-confirm-banner__body">
                Your session expires in{" "}
                {remaining
                  ? `${remaining} minute${remaining === 1 ? "" : "s"}`
                  : "less than a minute"}
                . Sign in again after it expires to continue.
              </p>
            </div>
          )}

          {/* Quick links for owners */}
          {identity.role === "owner" &&
            identity.permissions.includes("bookings:read") && (
              <div style={{ marginBottom: 24 }}>
                <p style={{ margin: "0 0 12px", fontWeight: 700 }}>
                  Workspace shortcuts:
                </p>
                <div className="adm-workspace-shortcuts">
                  <Link
                    to="/admin/automation"
                    className="adm-workspace-shortcut-card"
                  >
                    <span className="adm-workspace-shortcut-title">
                      Manage catering bookings and Calendar ↗
                    </span>
                    <span className="adm-workspace-shortcut-desc">
                      Requests, deposits, external payments & sync
                    </span>
                  </Link>
                  <Link
                    to="/admin/dashboard"
                    className="adm-workspace-shortcut-card"
                  >
                    <span className="adm-workspace-shortcut-title">
                      Open admin dashboard ↗
                    </span>
                    <span className="adm-workspace-shortcut-desc">
                      Metrics, attention items & upcoming events
                    </span>
                  </Link>
                  <Link
                    to="/admin/orders"
                    className="adm-workspace-shortcut-card"
                  >
                    <span className="adm-workspace-shortcut-title">
                      View customer orders ↗
                    </span>
                    <span className="adm-workspace-shortcut-desc">
                      Customer catering requests and orders
                    </span>
                  </Link>
                </div>
              </div>
            )}

          {!identity.permissions.includes("bookings:read") && (
            <p role="status">Booking access is not assigned to this account.</p>
          )}

          {/* Session Details Card */}
          <section
            className="adm-card adm-card--outlined od-section"
            style={{ marginBottom: 24 }}
            aria-labelledby="session-details-heading"
          >
            <h2
              className="od-section__title"
              id="session-details-heading"
              style={{ marginBottom: 16 }}
            >
              Session details
            </h2>

            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "160px 1fr",
                gap: "12px 16px",
                margin: 0,
                fontSize: 14,
              }}
            >
              <dt style={{ fontWeight: 700, color: "#3b003d" }}>Name</dt>
              <dd style={{ margin: 0, color: "#3b003d" }}>
                {identity.name || "Not provided"}
              </dd>

              <dt style={{ fontWeight: 700, color: "#3b003d" }}>Email</dt>
              <dd style={{ margin: 0, color: "#3b003d" }}>{identity.email}</dd>

              <dt style={{ fontWeight: 700, color: "#3b003d" }}>Role</dt>
              <dd style={{ margin: 0, color: "#3b003d" }}>
                {identity.role === "owner" ? "Owner" : "Staff"}
              </dd>

              <dt style={{ fontWeight: 700, color: "#3b003d" }}>
                Current session ends
              </dt>
              <dd style={{ margin: 0, color: "#3b003d" }}>
                <time dateTime={deadline.toISOString()}>
                  {deadline.toLocaleString()}
                </time>
              </dd>
            </dl>

            <p
              style={{
                margin: "16px 0 0",
                fontSize: 13,
                color: "#4b004b",
                lineHeight: 1.4,
              }}
            >
              Administrator sessions end after 15 minutes of inactivity or eight
              hours.
            </p>
          </section>

          {/* Team Permissions Card */}
          <section
            className="od-section od-section--pink"
            style={{ marginBottom: 28 }}
            aria-labelledby="permissions-heading"
          >
            <h2 className="od-section__title" id="permissions-heading">
              Your team permissions
            </h2>

            {capabilities.length ? (
              <ul className="adm-perm-grid" role="list">
                {capabilities.map((label) => (
                  <li key={label} className="adm-perm-pill">
                    {label}
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ margin: "8px 0 0", fontSize: 14 }}>
                No business permissions are assigned to this account.
              </p>
            )}
          </section>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Link
              to="/admin/login?reauth=1"
              className="adm-btn adm-btn--outline"
            >
              Verify again
            </Link>
            <button
              type="button"
              className="adm-btn adm-btn--primary"
              onClick={onLogout}
            >
              Sign out
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
