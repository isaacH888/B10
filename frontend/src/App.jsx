import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import { AuthProvider, sessionDeadline, useAuth } from "./auth/AuthContext.jsx";
import { ApiError, apiRequest, callbackMessage, errorMessage, navigateToProvider } from "./auth/api.js";

function Layout({ children }) {
  return <div className="test-shell">
    <header>
      <p><strong>Popssibilities authentication test</strong></p>
      <nav aria-label="Main navigation">
        <Link to="/">Home</Link>
        <Link to="/login">Customer login</Link>
        <Link to="/account">Customer session</Link>
        <Link to="/admin/login">Admin login</Link>
        <Link to="/admin">Admin session</Link>
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
    try {
      await apiRequest("/live");
      const health = await apiRequest("/health");
      setResult(health.database === "ok" ? "Backend reachable. Database connectivity verified." : "Backend reachable. Database is unavailable or not configured.");
    } catch (error) {
      setResult(error.status === 503 ? "Backend readiness is unavailable. Check the database and service configuration." : "The backend connection could not be verified.");
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
        ? "Sign in with your team password or approved Google account. Your authenticator app is required each time you sign in."
        : "Sign in or create a customer account using email or Google."}</p>
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
        {busy === "password" ? "Opening secure sign-in…" : admin ? "Continue with password" : "Continue with email"}
      </button>
      <button type="button" disabled={Boolean(busy) || session.logoutPending} onClick={() => begin("google")}>
        {busy === "google" ? "Opening Google sign-in…" : "Continue with Google"}
      </button>
    </div>}
    <p>{admin
      ? "Need an invitation or help with your authenticator? Contact the account owner."
      : "Account registration and password reset are available on the secure sign-in screen."}</p>
  </section>;
}

const mfaStatuses = new Set(["approval_required", "enrollment_required", "challenge_required"]);

function validMfa(data) {
  return data && mfaStatuses.has(data.status)
    && typeof data.csrf_token === "string" && data.csrf_token.length > 0
    && Number.isFinite(Date.parse(data.expires_at))
    && (data.approval_code == null || (typeof data.approval_code === "string" && data.approval_code.length > 0 && data.approval_code.length <= 512))
    && (data.status !== "approval_required" || (typeof data.approval_code === "string" && data.approval_code.length > 0 && data.approval_code.length <= 512));
}

function AdminMfaPage() {
  const { refresh, expire, login } = useAuth();
  const navigate = useNavigate();
  const [pending, setPending] = useState({ status: "loading" });
  const [setup, setSetup] = useState(null);
  const [showRecovery, setShowRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [now, setNow] = useState(Date.now());
  const version = useRef(0);
  const mounted = useRef(false);

  const failure = useCallback((cause) => {
    setCode("");
    setError(errorMessage(cause));
    if (cause.status === 401 || cause.status === 403) {
      version.current += 1;
      setSetup(null);
      setShowRecovery(false);
      setPending({ status: cause.status === 401 ? "expired" : "denied" });
      setBusy("");
    }
  }, []);

  const checkPending = useCallback(async () => {
    const requestVersion = ++version.current;
    setBusy("refresh");
    setPending({ status: "loading" });
    setSetup(null);
    setShowRecovery(false);
    setCode("");
    setError("");
    try {
      const data = await apiRequest("/admin/mfa");
      if (!validMfa(data)) throw new ApiError(502, "invalid_response");
      if (!mounted.current || requestVersion !== version.current) return;
      setPending(Date.parse(data.expires_at) > Date.now() ? data : { status: "expired" });
    } catch (cause) {
      if (!mounted.current || requestVersion !== version.current) return;
      setPending({ status: "error" });
      failure(cause);
    } finally {
      if (mounted.current && requestVersion === version.current) setBusy("");
    }
  }, [failure]);

  useEffect(() => {
    mounted.current = true;
    expire("admin");
    checkPending();
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      mounted.current = false;
      version.current += 1;
      clearInterval(tick);
    };
  }, [checkPending, expire]);

  useEffect(() => {
    if (mfaStatuses.has(pending.status) && Date.parse(pending.expires_at) <= now) {
      version.current += 1;
      setPending({ status: "expired" });
      setSetup(null);
      setShowRecovery(false);
      setCode("");
      setError("");
      setBusy("");
    }
  }, [now, pending]);

  async function enroll() {
    const requestVersion = version.current;
    setBusy("enroll");
    setError("");
    try {
      const data = await apiRequest("/admin/mfa/enroll", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": pending.csrf_token }, body: "{}",
      });
      const uri = new URL(data.otpauth_uri);
      if (typeof data.secret !== "string" || !/^[A-Z2-7]{16,128}$/.test(data.secret)
        || uri.protocol !== "otpauth:" || uri.hostname !== "totp" || uri.searchParams.get("secret") !== data.secret
        || !Number.isFinite(Date.parse(data.expires_at))) throw new ApiError(502, "invalid_response");
      if (!mounted.current || requestVersion !== version.current) return;
      const deadline = Math.min(Date.parse(pending.expires_at), Date.parse(data.expires_at));
      if (deadline <= Date.now()) throw new ApiError(401, "mfa_challenge_expired");
      setSetup({ secret: data.secret });
      setPending((current) => ({ ...current, expires_at: new Date(deadline).toISOString() }));
    } catch (cause) {
      if (mounted.current && requestVersion === version.current) failure(cause);
    } finally {
      if (mounted.current && requestVersion === version.current) setBusy("");
    }
  }

  async function verify(event) {
    event.preventDefault();
    const requestVersion = version.current;
    setBusy("verify");
    setError("");
    try {
      const data = await apiRequest("/admin/mfa/verify", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": pending.csrf_token }, body: JSON.stringify({ code }),
      });
      if (!["authenticated", "enrolled"].includes(data.status)) throw new ApiError(502, "invalid_response");
      if (!mounted.current || requestVersion !== version.current) return;
      setSetup(null);
      setShowRecovery(false);
      setCode("");
      setPending({ status: data.status });
      if (data.status === "authenticated") {
        const session = await refresh("admin", { force: true });
        if (!mounted.current || requestVersion !== version.current) return;
        if (session.status === "authenticated") navigate("/admin", { replace: true });
        else {
          setPending({ status: "denied" });
          failure(session.error || new ApiError(403, "forbidden"));
        }
      }
    } catch (cause) {
      if (mounted.current && requestVersion === version.current) failure(cause);
    } finally {
      if (mounted.current && requestVersion === version.current) setBusy("");
    }
  }

  async function cancel() {
    const requestVersion = version.current;
    setBusy("cancel");
    setError("");
    setSetup(null);
    setShowRecovery(false);
    setCode("");
    setPending((current) => ({ ...current, approval_code: undefined }));
    try {
      const data = await apiRequest("/admin/mfa", {
        method: "DELETE", headers: { "X-CSRF-Token": pending.csrf_token },
      });
      if (!mounted.current || requestVersion !== version.current) return;
      setPending({ status: "cancelled" });
      navigateToProvider(data.logout_url);
    } catch (cause) {
      if (mounted.current && requestVersion === version.current) failure(cause);
    } finally {
      if (mounted.current && requestVersion === version.current) setBusy("");
    }
  }

  async function signInAgain() {
    setBusy("login");
    setError("");
    try { await login("admin", "google"); }
    catch (cause) { failure(cause); setBusy(""); }
  }

  const active = mfaStatuses.has(pending.status);
  return <section>
    <h1>Authenticator verification</h1>
    <p>Google sign-in requires separate administrator approval and authenticator verification.</p>
    {error && <Notice>{error}</Notice>}
    {pending.status === "loading" && <p role="status">Checking verification…</p>}
    {pending.status === "approval_required" && <>
      <h2>Administrator approval required</h2>
      <p>This Google sign-in has no administrator access. Share this approval code privately with the account operator, who must verify your identity and Google account ownership separately.</p>
      {pending.approval_code && <p>Approval code: <code>{pending.approval_code}</code></p>}
      <button type="button" onClick={checkPending} disabled={Boolean(busy)}>Check approval</button>
    </>}
    {pending.status === "enrollment_required" && <>
      <h2>Set up your authenticator</h2>
      <p>Add an account in your authenticator app using the setup key below. Completing enrollment does not grant a signed-in administrator session.</p>
      {!setup && <button type="button" onClick={enroll} disabled={Boolean(busy)}>{busy === "enroll" ? "Creating setup key…" : "Create authenticator setup key"}</button>}
      {setup && <p>Authenticator setup key: <code>{setup.secret}</code></p>}
    </>}
    {pending.status === "challenge_required" && pending.approval_code && <>
      <button type="button" onClick={() => setShowRecovery(true)} disabled={Boolean(busy)}>Recover authenticator</button>
      {showRecovery && <>
        <p>Contact the authorized account operator privately. The operator must verify your identity separately before approving a replacement authenticator. This code does not reset your authenticator or grant administrator access.</p>
        <p>Private recovery code: <code>{pending.approval_code}</code></p>
      </>}
    </>}
    {(pending.status === "challenge_required" || (pending.status === "enrollment_required" && setup)) && <form onSubmit={verify}>
      <p><label htmlFor="authenticator-code">Six-digit authenticator code</label></p>
      <input id="authenticator-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6}
        required value={code} onChange={(event) => setCode(event.target.value.replace(/[^0-9]/g, ""))} disabled={Boolean(busy)} />
      <p><button type="submit" disabled={Boolean(busy) || !/^[0-9]{6}$/.test(code)}>{busy === "verify" ? "Verifying…" : "Verify authenticator code"}</button></p>
    </form>}
    {active && <>
      <p>This verification expires at <time dateTime={pending.expires_at}>{new Date(pending.expires_at).toLocaleTimeString()}</time>.</p>
      <button type="button" onClick={cancel} disabled={Boolean(busy)}>{busy === "cancel" ? "Cancelling…" : "Cancel sign-in"}</button>
    </>}
    {pending.status === "enrolled" && <>
      <p role="status">Authenticator enrolled. Sign in again, then enter a new authenticator code.</p>
      <button type="button" onClick={signInAgain} disabled={Boolean(busy)}>Continue with Google</button>
    </>}
    {pending.status === "authenticated" && <p role="status">Checking verified access…</p>}
    {pending.status === "expired" && <Notice>This verification has expired. Sign in again to continue.</Notice>}
    {pending.status === "denied" && <p>No administrator access is available from this verification.</p>}
    {pending.status === "cancelled" && <p>Sign-in cancelled.</p>}
    {pending.status === "error" && <button type="button" onClick={checkPending} disabled={Boolean(busy)}>Try again</button>}
    {!active && pending.status !== "loading" && pending.status !== "authenticated" && <p><Link to="/admin/login?reauth=1">Back to admin sign-in</Link></p>}
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
    <h1>{admin ? "Team account" : `Welcome${identity.name ? `, ${identity.name}` : ""}.`}</h1>
    <p>{admin ? "Administrator session is authenticated." : "Customer session is authenticated."}</p>
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
    <Route path="/admin/mfa" element={<AdminMfaPage />} />
    <Route path="/admin" element={<ProtectedPage area="admin" />} />
    <Route path="*" element={<NotFound />} />
  </Routes></Layout></AuthProvider></BrowserRouter>;
}
