import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { AuthProvider, sessionDeadline, useAuth } from "./auth/AuthContext.jsx";
import { apiRequest, callbackMessage, errorMessage } from "./auth/api.js";
import { AdminDashboard } from "./AdminDashboard.jsx";

function Layout({ children }) {
  return <div className="test-shell">
    <header>
      <p><strong>Popssibilities authentication test</strong></p>
      <nav aria-label="Main navigation">
        <Link to="/">Home</Link>
        <Link to="/login">Customer login</Link>
        <Link to="/account">Customer session</Link>
        <Link to="/admin/login">Admin login</Link>
        <Link to="/admin">Admin dashboard</Link>
      </nav>
    </header>
    <main id="main-content">{children}</main>
    <footer>This is a temporary interface for testing authentication. The frontend design is not final.</footer>
  </div>;
}

function HomePage() {
  const [result, setResult] = useState("");
  const [checking, setChecking] = useState(false);
  async function checkConnection() {
    setChecking(true);
    let reachable = false;
    try {
      await apiRequest("/live");
      reachable = true;
      const health = await apiRequest("/health");
      const database = health.database === "ok" ? "Database connectivity verified." : "Database unavailable or not configured.";
      const authentication = health.authentication === "disabled" ? "Sign-in is disabled."
        : health.authentication === "unavailable" ? "Authentication storage is unavailable."
        : "Authentication configuration and storage are ready.";
      setResult(`Backend reachable. ${database} ${authentication}`);
    } catch {
      setResult(reachable ? "Backend reachable. Readiness could not be checked. Please try again."
        : "The backend connection could not be verified. Check that the backend is running.");
    } finally { setChecking(false); }
  }
  return <section>
    <h1>Authentication test</h1>
    <p>Use the navigation links to test customer login, administrator login, and protected sessions.</p>
    <p>Sign-in requires the configured authentication provider and database.</p>
    <button type="button" onClick={checkConnection} disabled={checking}>
      {checking ? "Checking connection…" : "Check backend connection"}
    </button>
    <p role="status">{result}</p>
  </section>;
}

function Notice({ children }) {
  return <div className="notice" role="alert">{children}</div>;
}

function LoginPage({ area }) {
  const admin = area === "admin";
  const { sessions, login, logout, refresh } = useAuth();
  const [params] = useSearchParams();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const session = sessions[area];
  const queryMessage = callbackMessage(params.get("error"));
  const reauthentication = admin && (params.get("reauth") === "1" || (session.status === "authenticated" && Boolean(queryMessage)));

  async function begin(provider) {
    setBusy(provider);
    setError("");
    try { await login(area, provider); }
    catch (failure) { setError(errorMessage(failure)); setBusy(""); }
  }

  if (session.status === "authenticated" && !reauthentication && !queryMessage) {
    return <Navigate to={admin ? "/admin" : "/account"} replace />;
  }
  return <section>
    <h1>{reauthentication ? "Verify your access" : admin ? "Team sign-in" : "Customer sign-in"}</h1>
    <p>{reauthentication
      ? "Sign in again and complete authenticator verification before sensitive actions."
      : admin
        ? "Sign in with your team email and password. Your authenticator app is required each time you sign in."
        : "Sign in or create a customer account using email and password or Google."}</p>
    {admin && <p>Administrator access is invitation only.</p>}
    {queryMessage && <Notice>{queryMessage}</Notice>}
    {error && <Notice>{error}</Notice>}
    {session.status === "error" && !error && <Notice>
      <p>{errorMessage(session.error)}</p>
      <button type="button" onClick={() => refresh(area)}>Try again</button>
    </Notice>}
    {session.logoutPending && <Notice>
      <p>We couldn’t confirm sign-out. Please retry to end your session.</p>
      <button type="button" onClick={() => logout(area)}>Retry sign-out</button>
    </Notice>}
    {session.status === "loading" ? <p role="status">Checking your session…</p> : <div className="actions">
      <button type="button" disabled={Boolean(busy) || session.logoutPending} onClick={() => begin("password")}>
        {busy === "password" ? "Opening secure sign-in…" : admin ? "Continue with password" : "Continue with email and password"}
      </button>
      {!admin && <button type="button" disabled={Boolean(busy) || session.logoutPending} onClick={() => begin("google")}>
        {busy === "google" ? "Opening Google sign-in…" : "Continue with Google"}
      </button>}
    </div>}
    <p>{admin
      ? "Need an invitation or help with your authenticator? Contact the account owner."
      : "Account registration and password reset are available on the secure sign-in screen."}</p>
  </section>;
}

function ProtectedPage({ area }) {
  const { sessions, refresh, expire, logout } = useAuth();
  const [now, setNow] = useState(Date.now());
  const session = sessions[area];
  const admin = area === "admin";

  useEffect(() => {
    const poll = setInterval(() => refresh(area), 60000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [area, refresh]);

  useEffect(() => {
    if (session.status === "authenticated" && sessionDeadline(session.data) <= now) expire(area);
  }, [area, expire, now, session]);

  if (session.status === "loading") return <p role="status">Checking your session…</p>;
  if (session.status === "signed-out") {
    return <Navigate to={`${admin ? "/admin/login" : "/login"}${session.expired ? "?error=session_expired" : ""}`} replace />;
  }
  if (session.status === "error") return <section>
    <h1>{session.error.code === "reauthentication_required" ? "Verification required" : session.error.status === 403 ? "Access unavailable" : "Sign-in unavailable"}</h1>
    <Notice>{errorMessage(session.error)}</Notice>
    <div className="actions">
      <button type="button" onClick={() => refresh(area)}>Try again</button>
      {session.canLogout && <button type="button" onClick={() => logout(area)}>Sign out</button>}
      <Link to={admin ? "/admin/login?reauth=1" : "/login"}>Back to sign-in</Link>
    </div>
  </section>;

  const identity = session.data[admin ? "administrator" : "customer"];
  const deadline = new Date(sessionDeadline(session.data));
  const remaining = Math.max(0, Math.ceil((deadline.getTime() - now) / 60000));
  return <section>
    <h1>{admin ? "Admin dashboard" : `Welcome${identity.name ? `, ${identity.name}` : ""}.`}</h1>
    <p>{admin ? `Welcome${identity.name ? `, ${identity.name}` : ""}. Your administrator session is authenticated.` : "Customer session is authenticated."}</p>
    {admin && <AdminDashboard identity={identity} />}
    {remaining <= 5 && <Notice>
      Your session expires in {remaining ? `${remaining} minute${remaining === 1 ? "" : "s"}` : "less than a minute"}. Sign in again after it expires to continue.
    </Notice>}
    <h2>Session details</h2>
    <dl>
      <dt>Name</dt><dd>{identity.name || "Not provided"}</dd>
      <dt>Email</dt><dd>{identity.email}</dd>
      {admin && <><dt>Role</dt><dd>{identity.role === "owner" ? "Owner" : "Staff"}</dd></>}
      <dt>Current session ends</dt><dd><time dateTime={deadline.toISOString()}>{deadline.toLocaleString()}</time></dd>
    </dl>
    {admin && <>
      <p>Administrator sessions end after 15 minutes of inactivity or eight hours.</p>
      <AdminCapabilities identity={identity} />
    </>}
    <div className="actions">
      {admin && <Link to="/admin/login?reauth=1">Verify again</Link>}
      <button type="button" onClick={() => logout(area, session.data.csrf_token)}>Sign out</button>
    </div>
  </section>;
}

function AdminCapabilities({ identity }) {
  const labels = {
    "bookings:read": "View bookings", "bookings:contacts": "View contact details",
    "bookings:notes": "Update booking notes", "bookings:fulfill": "Mark fulfillment",
    "bookings:confirm": "Confirm bookings", "bookings:cancel": "Cancel bookings",
    "bookings:price": "Update booking prices", "payments:manage": "Manage payments",
    "customers:export": "Export customer data",
  };
  const capabilities = [...new Set(identity.permissions.map((permission) => Object.hasOwn(labels, permission) ? labels[permission] : null).filter(Boolean))];
  return <section>
    <h2>Your team permissions</h2>
    {capabilities.length ? <ul>{capabilities.map((label) => <li key={label}>{label}</li>)}</ul> : <p>No business permissions are assigned to this account.</p>}
  </section>;
}

function NotFound() {
  return <section><h1>Page not found</h1><Link to="/">Back home</Link></section>;
}

export default function App() {
  return <BrowserRouter><AuthProvider><Layout><Routes>
    <Route path="/" element={<HomePage />} />
    <Route path="/login" element={<LoginPage area="customer" />} />
    <Route path="/account" element={<ProtectedPage area="customer" />} />
    <Route path="/admin/login" element={<LoginPage area="admin" />} />
    <Route path="/admin/mfa" element={<Navigate to="/admin/login?reauth=1" replace />} />
    <Route path="/admin" element={<ProtectedPage area="admin" />} />
    <Route path="*" element={<NotFound />} />
  </Routes></Layout></AuthProvider></BrowserRouter>;
}
