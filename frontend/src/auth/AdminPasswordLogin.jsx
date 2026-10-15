import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";
import { ApiError, apiRequest, callbackMessage, errorMessage } from "./api.js";

const endpoint = "/admin/password/transaction";
const steps = new Set(["password", "new_password", "totp_enrollment", "totp", "complete"]);

function validTransaction(data) {
  return data && steps.has(data.step) && typeof data.csrf_token === "string" && data.csrf_token.length > 0
    && Number.isFinite(Date.parse(data.expires_at))
    && (data.enrollment_complete == null || typeof data.enrollment_complete === "boolean")
    && (data.enrollment_secret == null || (data.step === "totp_enrollment" && typeof data.enrollment_secret === "string"
      && /^[A-Z2-7]{16,256}$/.test(data.enrollment_secret)));
}

function Alert({ children }) {
  return <div className="notice" role="alert">{children}</div>;
}

function PasswordForm() {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [transaction, setTransaction] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const form = useRef(null);
  const mounted = useRef(false);
  const pending = useRef(null);
  const inFlight = useRef(false);
  const version = useRef(0);

  async function accept(data, requestVersion) {
    if (!validTransaction(data)) throw new ApiError(502, "invalid_response");
    if (!mounted.current || requestVersion !== version.current) return;
    if (data.step !== "complete" && Date.parse(data.expires_at) <= Date.now()) throw new ApiError(401, "login_expired");
    if (data.step === "complete") {
      setTransaction(null);
      setNotice("Checking verified administrator access…");
      // Confirm the protected session before displaying the dashboard.
      const session = await refresh("admin", { force: true });
      if (!mounted.current || requestVersion !== version.current) return;
      if (session.status !== "authenticated") throw session.error || new ApiError(401, "session_expired");
      navigate("/admin", { replace: true });
      return;
    }
    setTransaction(data);
    setNotice(data.enrollment_complete ? "Authenticator enrolled. Enter your password again, then use a new authenticator code to sign in." : "");
  }

  useEffect(() => {
    mounted.current = true;
    const requestVersion = version.current;
    // Share bootstrap during StrictMode's effect replay so cookies cannot race.
    pending.current ||= apiRequest(endpoint);
    let active = true;
    pending.current.then((data) => {
      if (active) return accept(data, requestVersion);
    }).catch((cause) => {
      if (active && mounted.current) setError(errorMessage(cause));
    }).finally(() => {
      if (active && mounted.current) setBusy(false);
    });
    return () => {
      active = false;
      mounted.current = false;
      form.current?.reset();
    };
  }, []);

  useEffect(() => {
    if (!transaction) return;
    const expire = () => {
      if (Date.parse(transaction.expires_at) <= Date.now()) {
        version.current += 1;
        form.current?.reset();
        setTransaction(null);
        setNotice("");
        setError("This sign-in has expired. Start again to continue.");
        setBusy(false);
      }
    };
    const timer = setInterval(expire, 1000);
    expire();
    return () => clearInterval(timer);
  }, [transaction]);

  async function submit(event) {
    event.preventDefault();
    if (inFlight.current || !transaction) return;
    const values = new FormData(event.currentTarget);
    let payload;
    if (transaction.step === "password") payload = { email: values.get("email"), password: values.get("password") };
    else if (transaction.step === "new_password") {
      if (values.get("new_password") !== values.get("confirm_password")) {
        form.current?.reset();
        setError("Enter the same new password in both fields.");
        return;
      }
      payload = { new_password: values.get("new_password") };
    } else payload = { code: values.get("code") };
    const csrf = transaction.csrf_token;
    const requestVersion = ++version.current;
    form.current?.reset();
    // Hide the setup key as soon as its confirmation is submitted.
    setTransaction((current) => ({ ...current, enrollment_secret: undefined }));
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await apiRequest(endpoint, {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(payload),
      });
      await accept(data, requestVersion);
    } catch (cause) {
      if (mounted.current && requestVersion === version.current) {
        setTransaction(null);
        setNotice("");
        setError(errorMessage(cause));
      }
    } finally {
      inFlight.current = false;
      if (mounted.current && requestVersion === version.current) setBusy(false);
    }
  }

  async function restart() {
    if (inFlight.current) return;
    const csrf = transaction?.csrf_token;
    const requestVersion = ++version.current;
    form.current?.reset();
    setTransaction(null);
    setNotice("");
    setError("");
    setBusy(true);
    inFlight.current = true;
    try {
      if (csrf) await apiRequest(endpoint, { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
      await accept(await apiRequest(endpoint), requestVersion);
    } catch (cause) {
      if (mounted.current && requestVersion === version.current) setError(errorMessage(cause));
    } finally {
      inFlight.current = false;
      if (mounted.current && requestVersion === version.current) setBusy(false);
    }
  }

  const step = transaction?.step;
  const missingSetupKey = step === "totp_enrollment" && !transaction.enrollment_secret && !busy;
  return <div className="admin-password-login">
    {error && <Alert>{error}</Alert>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">{transaction ? "Verifying sign-in…" : "Preparing secure sign-in…"}</p>}
    {transaction && <>
      {step === "new_password" && <><h2>Choose a new password</h2><p>Replace your temporary password with a password of at least 16 characters.</p></>}
      {step === "totp_enrollment" && <><h2>Set up your authenticator</h2>
        {transaction.enrollment_secret ? <>
          <p>Add a time-based account to your authenticator app using this private setup key, then enter the six-digit code.</p>
          <p>Setup key: <code className="setup-key">{transaction.enrollment_secret}</code></p>
        </> : missingSetupKey && <p>The private setup key is no longer shown. Start again to set up your authenticator.</p>}
      </>}
      {step === "totp" && <><h2>Verify your authenticator</h2><p>Enter a new six-digit code from your authenticator app.</p></>}
      {!missingSetupKey && <form key={step} ref={form} onSubmit={submit}>
        {step === "password" && <>
          <p><label htmlFor="admin-email">Team email</label></p>
          <input id="admin-email" name="email" type="email" autoComplete="username" maxLength={254} required disabled={busy} />
          <p><label htmlFor="admin-password">Password</label></p>
          <input id="admin-password" name="password" type="password" autoComplete="current-password" maxLength={256} required disabled={busy} />
        </>}
        {step === "new_password" && <>
          <p><label htmlFor="admin-new-password">New password</label></p>
          <input id="admin-new-password" name="new_password" type="password" autoComplete="new-password" minLength={16} maxLength={256} required disabled={busy} />
          <p><label htmlFor="admin-confirm-password">Confirm new password</label></p>
          <input id="admin-confirm-password" name="confirm_password" type="password" autoComplete="new-password" minLength={16} maxLength={256} required disabled={busy} />
        </>}
        {["totp", "totp_enrollment"].includes(step) && <>
          <p><label htmlFor="admin-authenticator-code">Six-digit authenticator code</label></p>
          <input id="admin-authenticator-code" name="code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required disabled={busy} />
        </>}
        <p><button type="submit" disabled={busy}>{step === "password" ? "Continue with password" : step === "new_password" ? "Save new password" : "Verify authenticator code"}</button></p>
      </form>}
      <p>This sign-in expires at <time dateTime={transaction.expires_at}>{new Date(transaction.expires_at).toLocaleTimeString()}</time>.</p>
    </>}
    {!busy && (error || missingSetupKey || (transaction && step !== "password")) && <button type="button" onClick={restart}>Start again</button>}
  </div>;
}

export function AdminPasswordLogin() {
  const { sessions, refresh, logout } = useAuth();
  const [started, setStarted] = useState(false);
  const session = sessions.admin;
  const [params] = useSearchParams();
  const message = callbackMessage(params.get("error"));
  const reauthentication = params.get("reauth") === "1" || (session.status === "authenticated" && Boolean(message));
  if (session.status === "authenticated" && !reauthentication && !message) return <Navigate to="/admin" replace />;
  return <section>
    <h1>{reauthentication ? "Verify your access" : "Team sign-in"}</h1>
    <p>Sign in with your team email and password. Your authenticator app is required each time you sign in.</p>
    <p>Administrator access is invitation only.</p>
    {message && <Alert>{message}</Alert>}
    {session.status === "error" && <Alert><p>{errorMessage(session.error)}</p><button type="button" onClick={() => refresh("admin")}>Check session again</button></Alert>}
    {session.logoutPending && <Alert><p>We couldn’t confirm sign-out. Please retry to end your session.</p><button type="button" onClick={() => logout("admin")}>Retry sign-out</button></Alert>}
    {session.status === "loading" ? <p role="status">Checking your session…</p> : !session.logoutPending && (
      started ? <PasswordForm /> : <div className="actions">
        {/* Start the short-lived MFA transaction only after the user continues. */}
        <button type="button" onClick={() => setStarted(true)}>Continue with password</button>
      </div>
    )}
    <p>Need an invitation or help with your authenticator? Contact the account owner.</p>
  </section>;
}
