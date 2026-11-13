import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CustomerTestEmail } from "./CustomerTestEmail.jsx";
import "./customer-account.css";

const views = [
  { id: "overview", label: "Account Overview", href: "/account" },
  {
    id: "security",
    label: "Sign-In & Security",
    href: "/account?view=security",
  },
  { id: "email", label: "Email Preview", href: "/account?view=email" },
];

export function CustomerAccount({
  identity,
  csrfToken,
  deadline,
  remaining,
  onSignOut,
}) {
  const [params] = useSearchParams();
  const view =
    views.find((item) => item.id === params.get("view"))?.id || "overview";
  const heading = useRef(null);
  const name = identity.name?.trim();
  const title =
    view === "overview"
      ? `Welcome${name ? `, ${name}` : ""}.`
      : views.find((item) => item.id === view).label;

  useEffect(() => {
    heading.current?.focus();
  }, [view]);

  return (
    <div className="customer-account">
      <header className="account-intro">
        <p className="account-eyebrow">A little space of your own</p>
        <h1>My Account</h1>
        <p>Your details and your next celebration, all in one place.</p>
      </header>

      <div className="account-layout">
        <aside className="account-sidebar" aria-label="Account menu">
          <nav aria-label="My account navigation">
            {views.map((item) => (
              <Link
                key={item.id}
                to={item.href}
                aria-current={view === item.id ? "page" : undefined}
              >
                {item.label}
                <span aria-hidden="true">›</span>
              </Link>
            ))}
          </nav>
          <div className="account-sidebar__help">
            <p>Need a hand with your event?</p>
            <a href="mailto:info@popssibilities.com">Email our team</a>
          </div>
          <button className="account-signout" type="button" onClick={onSignOut}>
            Sign out
          </button>
        </aside>

        <div className="account-content">
          <header className="account-section-heading">
            <div>
              <h2 ref={heading} tabIndex={-1}>
                {title}
              </h2>
              <p>
                {view === "overview"
                  ? "A few details that make this account yours."
                  : view === "security"
                    ? "Keep track of your current sign-in."
                    : "See what a sample order confirmation looks like in your inbox."}
              </p>
            </div>
            {view === "overview" && (
              <span className="account-avatar" aria-hidden="true">
                {(name || identity.email).slice(0, 1).toUpperCase()}
              </span>
            )}
          </header>

          {remaining <= 5 && (
            <div className="account-warning" role="alert">
              Your session expires in{" "}
              {remaining
                ? `${remaining} minute${remaining === 1 ? "" : "s"}`
                : "less than a minute"}
              . Sign in again after it expires to continue.
            </div>
          )}

          <section
            className="account-panel"
            aria-label="Account details"
            hidden={view !== "overview"}
          >
            <div className="account-details">
              <h3>Your Details</h3>
              <dl>
                <div>
                  <dt>Full name</dt>
                  <dd>{name || "Not provided"}</dd>
                </div>
                <div>
                  <dt>Email address</dt>
                  <dd>{identity.email}</dd>
                </div>
              </dl>
            </div>
            <div className="account-catering">
              <div>
                <p className="account-eyebrow">Good times, great paletas</p>
                <h3>Something to celebrate?</h3>
                <p>
                  Bring fresh, handcrafted paletas to your next event. Share a
                  few details and we’ll help with the rest.
                </p>
              </div>
              <Link
                className="account-button account-button--primary"
                to="/order"
              >
                Request a catering quote
              </Link>
            </div>
          </section>

          <section
            className="account-panel account-security"
            aria-label="Sign-in details"
            hidden={view !== "security"}
          >
            <h3>Current Sign-In</h3>
            <dl>
              <div>
                <dt>Signed in as</dt>
                <dd>{identity.email}</dd>
              </div>
              <div>
                <dt>Current session ends</dt>
                <dd>
                  <time dateTime={deadline.toISOString()}>
                    {deadline.toLocaleString()}
                  </time>
                </dd>
              </div>
            </dl>
            <p>
              For your privacy, your account signs out when this session ends.
              You can also sign out whenever you’re finished.
            </p>
          </section>

          {/* Keep this mounted so switching sections preserves send/retry state. */}
          <div
            className="account-panel account-email"
            hidden={view !== "email"}
          >
            <CustomerTestEmail
              key={identity.id}
              csrfToken={csrfToken}
              email={identity.email}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
