import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import { AuthProvider, sessionDeadline, useAuth } from "./auth/AuthContext.jsx";
import { apiRequest, callbackMessage, errorMessage } from "./auth/api.js";
import {
  quoteReturn,
  rememberCustomerReturn,
  readCustomerReturn,
} from "./auth/customerReturn.js";
import { AdminDashboardPage } from "./admin/AdminDashboardPage.jsx";
import { CalendarPage } from "./admin/CalendarPage.jsx";
import { InventoryPage } from "./admin/InventoryPage.jsx";
import { OrderDetailPage } from "./admin/OrderDetailPage.jsx";
import { OrdersPage } from "./admin/OrdersPage.jsx";
import { AdminPasswordLogin } from "./auth/AdminPasswordLogin.jsx";
import { PasswordRecoveryHelp } from "./auth/PasswordRecoveryHelp.jsx";
import { BookingWorkspacePage } from "./admin/BookingWorkspacePage.jsx";
import "./admin/admin-preview.css";
import { CateringPage } from "./CateringPage.jsx";
import { FaqPage } from "./FaqPage.jsx";
import { CustomerAccount } from "./CustomerAccount.jsx";
import { OrderConfirmation } from "./OrderConfirmation.jsx";
import { PaymentReturn } from "./payments/PaymentReturn.jsx";
import { PaymentPage } from "./payments/PaymentPage.jsx";
import { RouteScroll } from "./RouteScroll.jsx";
import {
  AdminSignInLayout,
  CustomerSignInLayout,
  PublicHome,
  PublicLayout,
} from "./PublicSite.jsx";
import restrictedAccessArt from "./assets/illustrations/restricted-access.svg";
import errorMascot from "./assets/illustrations/Popssibilities Popsicle.svg";

const adminPreview =
  import.meta.env.DEV && import.meta.env.MODE === "admin-preview";

function Layout({ children }) {
  const { pathname } = useLocation();
  if (
    /^\/admin\/(dashboard|orders|calendar|inventory|automation|bookings)(\/|$)/.test(
      pathname,
    )
  ) {
    return children;
  }
  if (pathname === "/login") {
    return <CustomerSignInLayout>{children}</CustomerSignInLayout>;
  }
  if (pathname === "/admin/login") {
    return <AdminSignInLayout>{children}</AdminSignInLayout>;
  }
  if (
    pathname === "/" ||
    pathname === "/order" ||
    pathname === "/faq" ||
    pathname === "/account" ||
    pathname === "/order/confirm" ||
    pathname === "/error-preview" ||
    pathname === "/payment/return" ||
    pathname === "/payment/pay"
  ) {
    return <PublicLayout>{children}</PublicLayout>;
  }
  if (pathname === "/diagnostics") {
    return (
      <div className="test-shell">
        <header>
          <p>
            <strong>Popssibilities authentication test</strong>
          </p>
          <nav aria-label="Main navigation">
            <Link to="/">Home</Link>
            <Link to="/order">Catering order</Link>
            <Link to="/login">Customer login</Link>
            <Link to="/account">Customer session</Link>
            <Link to="/admin/login">Admin login</Link>
            <Link to="/admin">Admin dashboard</Link>
            <Link to="/diagnostics">Connection diagnostics</Link>
          </nav>
        </header>
        <main id="main-content">{children}</main>
        <footer>
          This is a temporary interface for testing authentication. The frontend
          design is not final.
        </footer>
      </div>
    );
  }
  return <PublicLayout>{children}</PublicLayout>;
}

function DiagnosticsPage() {
  const [result, setResult] = useState("");
  const [checking, setChecking] = useState(false);
  async function checkConnection() {
    setChecking(true);
    let reachable = false;
    try {
      await apiRequest("/live");
      reachable = true;
      const health = await apiRequest("/health");
      const database =
        health.database === "ok"
          ? "Database connectivity verified."
          : "Database unavailable or not configured.";
      const authentication =
        health.authentication === "disabled"
          ? "Sign-in is disabled."
          : health.authentication === "unavailable"
            ? "Authentication storage is unavailable."
            : "Authentication configuration and storage are ready.";
      setResult(`Backend reachable. ${database} ${authentication}`);
    } catch {
      setResult(
        reachable
          ? "Backend reachable. Readiness could not be checked. Please try again."
          : "The backend connection could not be verified. Check that the backend is running.",
      );
    } finally {
      setChecking(false);
    }
  }
  return (
    <section>
      <h1>Connection diagnostics</h1>
      <p>
        Use the navigation links to test customer login, administrator login,
        and protected sessions.
      </p>
      <p>
        Sign-in requires the configured authentication provider and database.
      </p>
      <button type="button" onClick={checkConnection} disabled={checking}>
        {checking ? "Checking connection…" : "Check backend connection"}
      </button>
      <p role="status">{result}</p>
    </section>
  );
}

function Notice({ children, className }) {
  return (
    <div className={`notice ${className || ""}`.trim()} role="alert">
      {children}
    </div>
  );
}

function LoginPage() {
  const area = "customer";
  const { sessions, login, logout, refresh } = useAuth();
  const [params] = useSearchParams();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const session = sessions[area];
  const queryMessage = callbackMessage(params.get("error"));
  const destination =
    params.get("return_to") === quoteReturn
      ? quoteReturn
      : readCustomerReturn();

  useEffect(() => {
    if (session.status === "authenticated" && !queryMessage)
      rememberCustomerReturn(null);
  }, [session.status, queryMessage]);

  async function begin(provider) {
    setBusy(provider);
    setError("");
    try {
      rememberCustomerReturn(destination);
      await login(area, provider);
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy("");
    }
  }

  if (session.status === "authenticated" && !queryMessage) {
    return <Navigate to={destination || "/account"} replace />;
  }
  return (
    <section>
      <h1>Customer Sign-In</h1>
      <p>
        Sign in or create a customer account using email and password or Google.
      </p>
      {destination && (
        <p>
          Sign in first to request a catering quote and track your order in My
          Orders. After signing in, you’ll go straight to your quote form.
        </p>
      )}
      {queryMessage && <Notice>{queryMessage}</Notice>}
      {error && <Notice>{error}</Notice>}
      {session.status === "error" && !error && (
        <Notice>
          <p>{errorMessage(session.error)}</p>
          <button type="button" onClick={() => refresh(area)}>
            Try again
          </button>
        </Notice>
      )}
      {session.logoutPending && (
        <Notice>
          <p>We couldn’t confirm sign-out. Please retry to end your session.</p>
          <button type="button" onClick={() => logout(area)}>
            Retry sign-out
          </button>
        </Notice>
      )}
      {session.status === "loading" ? (
        <p role="status">Checking your session…</p>
      ) : (
        <div className="actions customer-login-actions">
          <button
            type="button"
            className="pill red"
            disabled={Boolean(busy) || session.logoutPending}
            onClick={() => begin("password")}
          >
            {busy === "password"
              ? "Opening secure sign-in…"
              : "Continue with email and password"}
          </button>
          <button
            type="button"
            className="pill outline"
            disabled={Boolean(busy) || session.logoutPending}
            onClick={() => begin("google")}
          >
            {busy === "google"
              ? "Opening Google sign-in…"
              : "Continue with Google"}
          </button>
        </div>
      )}
      <PasswordRecoveryHelp />
      <p>
        Account registration and password reset are available on the secure
        sign-in screen.
      </p>
    </section>
  );
}

function ProtectedPage({
  area,
  workspace = false,
  liveOrders = false,
  children,
}) {
  const location = useLocation();
  const { sessions, refresh, expire, logout } = useAuth();
  const [now, setNow] = useState(Date.now());
  const session = sessions[area];
  const admin = area === "admin";

  useEffect(() => {
    const poll = setInterval(() => refresh(area), 60000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [area, refresh]);

  useEffect(() => {
    if (
      session.status === "authenticated" &&
      sessionDeadline(session.data) <= now
    )
      expire(area);
  }, [area, expire, now, session]);

  if (session.status === "loading")
    return (
      <div className="session-loading-view" role="status">
        <span className="auth-spinner" aria-hidden="true" />
        <span>Checking your session…</span>
      </div>
    );
  if (session.status === "signed-out") {
    return (
      <Navigate
        to={`${admin ? "/admin/login" : "/login"}${session.expired ? "?error=session_expired" : ""}`}
        replace
      />
    );
  }
  if (session.status === "error") {
    const isForbidden = session.error.status === 403;
    const isReauth = session.error.code === "reauthentication_required";
    return (
      <section className="error-view session-error-view">
        <div className="error-card">
          <div className="error-card__visual">
            <img
              src={isForbidden ? restrictedAccessArt : errorMascot}
              alt=""
              className="error-card__art"
              width="140"
              height="140"
              aria-hidden="true"
            />
          </div>
          <div className="error-card__content">
            <span
              className={`error-badge ${isForbidden ? "error-badge--restricted" : ""}`}
            >
              {isReauth
                ? "AUTH CHECK"
                : isForbidden
                  ? "403 RESTRICTED ACCESS"
                  : "SERVER NOTICE"}
            </span>
            <h1 className="error-title">
              {isReauth
                ? "Verification required"
                : isForbidden
                  ? "Access unavailable"
                  : "Sign-in unavailable"}
            </h1>
            <Notice>
              <p>{errorMessage(session.error)}</p>
            </Notice>
            <div className="actions error-actions">
              <button
                type="button"
                className="pill red"
                onClick={() => refresh(area)}
              >
                Try again
              </button>
              {session.canLogout && (
                <button
                  type="button"
                  className="pill outline"
                  onClick={() => logout(area)}
                >
                  Sign out
                </button>
              )}
              <Link
                to={admin ? "/admin/login?reauth=1" : "/login"}
                className="pill outline"
              >
                Back to sign-in
              </Link>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const identity = session.data[admin ? "administrator" : "customer"];
  const deadline = new Date(sessionDeadline(session.data));
  const remaining = Math.max(0, Math.ceil((deadline.getTime() - now) / 60000));
  if (
    admin &&
    (location.pathname.startsWith("/admin/automation") ||
      location.pathname.startsWith("/admin/bookings/"))
  ) {
    return <BookingWorkspacePage />;
  }
  if (workspace || liveOrders) {
    if (
      identity.role !== "owner" ||
      !identity.permissions.includes("bookings:read")
    ) {
      return (
        <section className="error-view session-error-view">
          <div className="error-card">
            <div className="error-card__visual">
              <img
                src={restrictedAccessArt}
                alt=""
                className="error-card__art"
                width="140"
                height="140"
                aria-hidden="true"
              />
            </div>
            <div className="error-card__content">
              <span className="error-badge error-badge--restricted">
                403 RESTRICTED ACCESS
              </span>
              <h1 className="error-title">Owner access required</h1>
              <p className="error-desc">
                Only an owner with booking access can open this workspace.
              </p>
              {remaining <= 5 && (
                <Notice className="session-expiry-notice">
                  Your session expires in{" "}
                  {remaining ? `${remaining} minutes` : "less than a minute"}.
                </Notice>
              )}
              <div className="actions error-actions">
                <Link to="/admin/login?reauth=1" className="pill red">
                  Back to owner sign-in
                </Link>
                <Link to="/admin/login?reauth=1" className="pill outline">
                  Verify again
                </Link>
                <button
                  type="button"
                  className="pill outline"
                  onClick={() => logout(area, session.data.csrf_token)}
                >
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </section>
      );
    }
    return (
      <div className="admin-preview">
        {remaining <= 5 && (
          <Notice>
            Your session expires in{" "}
            {remaining ? `${remaining} minutes` : "less than a minute"}.
          </Notice>
        )}
        {children}
      </div>
    );
  }
  if (!admin) {
    return (
      <CustomerAccountLanding
        key={identity.id}
        identity={identity}
        csrfToken={session.data.csrf_token}
        deadline={deadline}
        remaining={remaining}
        onSignOut={() => logout(area, session.data.csrf_token)}
      />
    );
  }
  return <Navigate to="/admin/dashboard" replace />;
}

function CustomerAccountLanding(props) {
  const [destination] = useState(readCustomerReturn);
  useEffect(() => {
    if (destination) rememberCustomerReturn(null);
  }, [destination]);
  if (destination) return <Navigate to={destination} replace />;
  return <CustomerAccount {...props} />;
}

function NotFound() {
  return (
    <section className="error-view not-found-view">
      <div className="error-card">
        <div className="error-card__visual">
          <img
            src={errorMascot}
            alt=""
            className="error-card__art"
            width="140"
            height="140"
            aria-hidden="true"
          />
        </div>
        <div className="error-card__content">
          <span className="error-badge">404</span>
          <h1 className="error-title">Page not found</h1>
          <p className="error-desc">
            Looks like this page melted in the Texas sun. The flavor or link
            you're looking for doesn't exist or has moved.
          </p>
          <div className="actions error-actions">
            <Link to="/" className="pill red">
              Back home
            </Link>
            <Link to="/order" className="pill outline">
              Explore catering
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function ErrorPreviewPage() {
  const [tab, setTab] = useState("404");
  return (
    <div className="error-preview-container">
      <div
        className="error-preview-switcher"
        style={{
          display: "flex",
          gap: "8px",
          justifyContent: "center",
          padding: "16px",
          background: "#35162f",
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          className={`pill ${tab === "404" ? "red" : "outline"}`}
          style={{ minHeight: "36px", padding: "8px 16px", fontSize: "13px" }}
          onClick={() => setTab("404")}
        >
          404 Page Not Found
        </button>
        <button
          type="button"
          className={`pill ${tab === "403" ? "red" : "outline"}`}
          style={{ minHeight: "36px", padding: "8px 16px", fontSize: "13px" }}
          onClick={() => setTab("403")}
        >
          403 Access Unavailable
        </button>
        <button
          type="button"
          className={`pill ${tab === "403-owner" ? "red" : "outline"}`}
          style={{ minHeight: "36px", padding: "8px 16px", fontSize: "13px" }}
          onClick={() => setTab("403-owner")}
        >
          403 Owner Required
        </button>
        <button
          type="button"
          className={`pill ${tab === "500" ? "red" : "outline"}`}
          style={{ minHeight: "36px", padding: "8px 16px", fontSize: "13px" }}
          onClick={() => setTab("500")}
        >
          500 Server Outage
        </button>
        <button
          type="button"
          className={`pill ${tab === "loading" ? "red" : "outline"}`}
          style={{ minHeight: "36px", padding: "8px 16px", fontSize: "13px" }}
          onClick={() => setTab("loading")}
        >
          Session Loading
        </button>
      </div>
      <div>
        {tab === "404" && <NotFound />}
        {tab === "403" && (
          <section className="error-view session-error-view">
            <div className="error-card">
              <div className="error-card__visual">
                <img
                  src={restrictedAccessArt}
                  alt=""
                  className="error-card__art"
                  width="140"
                  height="140"
                  aria-hidden="true"
                />
              </div>
              <div className="error-card__content">
                <span className="error-badge error-badge--restricted">
                  403 RESTRICTED ACCESS
                </span>
                <h1 className="error-title">Access unavailable</h1>
                <Notice>
                  <p>
                    You do not have permission to view this protected workspace.
                  </p>
                </Notice>
                <div className="actions error-actions">
                  <button type="button" className="pill red">
                    Try again
                  </button>
                  <Link to="/admin/login" className="pill outline">
                    Back to sign-in
                  </Link>
                </div>
              </div>
            </div>
          </section>
        )}
        {tab === "403-owner" && (
          <section className="error-view session-error-view">
            <div className="error-card">
              <div className="error-card__visual">
                <img
                  src={restrictedAccessArt}
                  alt=""
                  className="error-card__art"
                  width="140"
                  height="140"
                  aria-hidden="true"
                />
              </div>
              <div className="error-card__content">
                <span className="error-badge error-badge--restricted">
                  403 RESTRICTED ACCESS
                </span>
                <h1 className="error-title">Owner access required</h1>
                <p className="error-desc">
                  Only an owner with booking access can open this workspace.
                </p>
                <Notice className="session-expiry-notice">
                  Your session expires in less than a minute.
                </Notice>
                <div className="actions error-actions">
                  <Link to="/admin/login?reauth=1" className="pill red">
                    Back to owner sign-in
                  </Link>
                  <Link to="/admin/login?reauth=1" className="pill outline">
                    Verify again
                  </Link>
                  <button type="button" className="pill outline">
                    Sign out
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}
        {tab === "500" && (
          <section className="error-view session-error-view">
            <div className="error-card">
              <div className="error-card__visual">
                <img
                  src={errorMascot}
                  alt=""
                  className="error-card__art"
                  width="140"
                  height="140"
                  aria-hidden="true"
                />
              </div>
              <div className="error-card__content">
                <span className="error-badge">SERVER NOTICE</span>
                <h1 className="error-title">Sign-in unavailable</h1>
                <Notice>
                  The backend connection could not be verified. Check that the
                  server is running.
                </Notice>
                <div className="actions error-actions">
                  <button type="button" className="pill red">
                    Try again
                  </button>
                  <Link to="/login" className="pill outline">
                    Back to sign-in
                  </Link>
                </div>
              </div>
            </div>
          </section>
        )}
        {tab === "loading" && (
          <div className="session-loading-view" role="status">
            <span className="auth-spinner" aria-hidden="true" />
            <span>Checking your session…</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <RouteScroll />
      <AuthProvider>
        {adminPreview && (
          <aside className="admin-sample-banner" aria-label="Sample preview">
            <p>
              <strong>Admin preview</strong> · Sample data · Viewing only
            </p>
            <a href="http://localhost:5173/admin/login">
              Open real admin sign-in ↗
            </a>
          </aside>
        )}
        <Layout>
          <Routes>
            <Route
              path="/"
              element={
                adminPreview ? (
                  <Navigate to="/admin/dashboard" replace />
                ) : (
                  <PublicHome />
                )
              }
            />
            <Route path="/diagnostics" element={<DiagnosticsPage />} />
            <Route path="/order" element={<CateringPage />} />
            <Route path="/faq" element={<FaqPage />} />
            <Route path="/order/confirm" element={<OrderConfirmation />} />
            <Route path="/payment/return" element={<PaymentReturn />} />
            <Route path="/payment/pay" element={<PaymentPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/account"
              element={<ProtectedPage area="customer" />}
            />
            <Route
              path="/admin/login"
              element={
                adminPreview ? (
                  <Navigate to="/admin/dashboard" replace />
                ) : (
                  <AdminPasswordLogin />
                )
              }
            />
            <Route
              path="/admin/mfa"
              element={<Navigate to="/admin/login?reauth=1" replace />}
            />
            <Route
              path="/admin"
              element={<Navigate to="/admin/dashboard" replace />}
            />
            <Route
              path="/admin/automation"
              element={<ProtectedPage area="admin" />}
            />
            <Route
              path="/admin/bookings/:bookingId"
              element={<ProtectedPage area="admin" />}
            />
            <Route
              path="/admin/dashboard"
              element={
                <ProtectedPage area="admin" workspace>
                  <AdminDashboardPage />
                </ProtectedPage>
              }
            />
            <Route
              path="/admin/orders"
              element={
                <ProtectedPage area="admin" liveOrders>
                  <OrdersPage />
                </ProtectedPage>
              }
            />
            <Route
              path="/admin/orders/:orderId"
              element={
                <ProtectedPage area="admin" liveOrders>
                  <OrderDetailPage />
                </ProtectedPage>
              }
            />
            <Route
              path="/admin/calendar"
              element={
                <ProtectedPage area="admin" workspace>
                  <CalendarPage />
                </ProtectedPage>
              }
            />
            <Route
              path="/admin/inventory"
              element={
                <ProtectedPage area="admin" workspace>
                  <InventoryPage />
                </ProtectedPage>
              }
            />
            <Route path="/error-preview" element={<ErrorPreviewPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Layout>
      </AuthProvider>
    </BrowserRouter>
  );
}
