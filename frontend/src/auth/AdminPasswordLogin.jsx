import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { useAuth } from "./AuthContext.jsx";
import { ApiError, apiRequest, callbackMessage, errorMessage } from "./api.js";
import "./admin-login.css";

const endpoint = "/admin/password/transaction";
const steps = new Set([
  "password",
  "new_password",
  "totp_enrollment",
  "totp",
  "complete",
]);

function validTransaction(data) {
  return (
    data &&
    steps.has(data.step) &&
    typeof data.csrf_token === "string" &&
    data.csrf_token.length > 0 &&
    Number.isFinite(Date.parse(data.expires_at)) &&
    (data.enrollment_complete == null ||
      typeof data.enrollment_complete === "boolean") &&
    (data.enrollment_secret == null ||
      (data.step === "totp_enrollment" &&
        typeof data.enrollment_secret === "string" &&
        /^[A-Z2-7]{16,256}$/.test(data.enrollment_secret)))
  );
}

function Alert({ children, type = "error" }) {
  return (
    <div className={`notice auth-alert auth-alert--${type}`} role="alert">
      <div className="auth-alert-content">{children}</div>
    </div>
  );
}

function AuthenticatorSetup({ secret, account }) {
  const issuer = "Popsibilities Admin";
  const label = encodeURIComponent(`${issuer}:${account || "Team account"}`);
  const parameters = new URLSearchParams({
    secret,
    issuer,
    algorithm: "SHA1",
    digits: "6",
    period: "30",
  });
  // Encode in the browser; never send an enrollment secret to a QR service.
  const uri = `otpauth://totp/${label}?${parameters}`;
  return (
    <div className="auth-totp-setup">
      <p className="auth-totp-instruction">
        Scan this QR code with your authenticator app, then enter the six-digit
        code.
      </p>
      <div className="auth-qr-frame">
        <QRCodeSVG
          value={uri}
          size={200}
          level="M"
          marginSize={4}
          bgColor="#ffffff"
          fgColor="#000000"
          role="img"
          title="Authenticator setup QR code"
          aria-label="Authenticator setup QR code"
          style={{ display: "block", maxWidth: "100%", height: "auto" }}
        />
      </div>
      <div className="auth-setup-key-block">
        <span className="auth-setup-key-label">
          Can’t scan? Add a time-based account manually using this setup key:
        </span>
        <code className="setup-key">{secret}</code>
      </div>
    </div>
  );
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
  const accountEmail = useRef("");

  async function accept(data, requestVersion) {
    if (!validTransaction(data)) throw new ApiError(502, "invalid_response");
    if (!mounted.current || requestVersion !== version.current) return;
    if (data.step !== "complete" && Date.parse(data.expires_at) <= Date.now())
      throw new ApiError(401, "login_expired");
    if (data.step === "complete") {
      setTransaction(null);
      setNotice("Checking verified administrator access…");
      // Confirm the protected session before displaying the dashboard.
      const session = await refresh("admin", { force: true });
      if (!mounted.current || requestVersion !== version.current) return;
      if (session.status !== "authenticated")
        throw session.error || new ApiError(401, "session_expired");
      navigate(
        session.data.administrator.role === "owner"
          ? "/admin/dashboard"
          : "/admin",
        { replace: true },
      );
      return;
    }
    setTransaction(data);
    setNotice(
      data.enrollment_complete
        ? "Authenticator enrolled. Enter your password again, then use a new authenticator code to sign in."
        : "",
    );
  }

  useEffect(() => {
    mounted.current = true;
    const requestVersion = version.current;
    // Share bootstrap during StrictMode's effect replay so cookies cannot race.
    pending.current ||= apiRequest(endpoint);
    let active = true;
    pending.current
      .then((data) => {
        if (active) return accept(data, requestVersion);
      })
      .catch((cause) => {
        if (active && mounted.current) setError(errorMessage(cause));
      })
      .finally(() => {
        if (active && mounted.current) setBusy(false);
      });
    return () => {
      active = false;
      mounted.current = false;
      accountEmail.current = "";
      form.current?.reset();
    };
  }, []);

  useEffect(() => {
    if (!transaction) return;
    const expire = () => {
      if (Date.parse(transaction.expires_at) <= Date.now()) {
        version.current += 1;
        accountEmail.current = "";
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
    if (transaction.step === "password") {
      payload = {
        email: values.get("email"),
        password: values.get("password"),
      };
      accountEmail.current = payload.email.trim().toLowerCase();
    } else if (transaction.step === "new_password") {
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
    // Hide both the QR code and setup key as soon as confirmation is submitted.
    setTransaction((current) => ({ ...current, enrollment_secret: undefined }));
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = await apiRequest(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(payload),
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
    accountEmail.current = "";
    setNotice("");
    setError("");
    setBusy(true);
    inFlight.current = true;
    try {
      if (csrf)
        await apiRequest(endpoint, {
          method: "DELETE",
          headers: { "X-CSRF-Token": csrf },
        });
      await accept(await apiRequest(endpoint), requestVersion);
    } catch (cause) {
      if (mounted.current && requestVersion === version.current)
        setError(errorMessage(cause));
    } finally {
      inFlight.current = false;
      if (mounted.current && requestVersion === version.current) setBusy(false);
    }
  }

  const step = transaction?.step;
  const submitLabel =
    step === "password"
      ? "Continue with password"
      : step === "new_password"
        ? "Save new password"
        : "Verify authenticator code";
  const missingSetupKey =
    step === "totp_enrollment" && !transaction.enrollment_secret && !busy;
  return (
    <div className="admin-password-login">
      {error && <Alert>{error}</Alert>}
      {notice && (
        <div className="notice auth-alert auth-alert--info" role="status">
          <div className="auth-alert-content">{notice}</div>
        </div>
      )}
      {busy && (
        <div className="auth-loading" role="status">
          <span className="auth-spinner" aria-hidden="true" />
          <span>
            {transaction ? "Verifying sign-in…" : "Preparing secure sign-in…"}
          </span>
        </div>
      )}
      {transaction && (
        <>
          {step === "new_password" && (
            <>
              <h2 className="auth-step-title">Choose a new password</h2>
              <p className="auth-step-desc">
                Replace your temporary password with a password of at least 16
                characters.
              </p>
            </>
          )}
          {step === "totp_enrollment" && (
            <>
              <h2 className="auth-step-title">Set up your authenticator</h2>
              {transaction.enrollment_secret ? (
                <AuthenticatorSetup
                  secret={transaction.enrollment_secret}
                  account={accountEmail.current}
                />
              ) : (
                missingSetupKey && (
                  <p className="auth-step-desc">
                    The private setup key is no longer shown. Start again to set
                    up your authenticator.
                  </p>
                )
              )}
            </>
          )}
          {step === "totp" && (
            <>
              <h2 className="auth-step-title">Verify your authenticator</h2>
              <p className="auth-step-desc">
                Enter a new six-digit code from your authenticator app.
              </p>
            </>
          )}
          {!missingSetupKey && (
            <form key={step} ref={form} onSubmit={submit}>
              {step === "password" && (
                <>
                  <div className="auth-field">
                    <label htmlFor="admin-email" className="auth-label">
                      Team email
                    </label>
                    <input
                      id="admin-email"
                      name="email"
                      type="email"
                      autoComplete="username"
                      maxLength={254}
                      required
                      disabled={busy}
                      className="auth-input"
                      placeholder="team@popssibilities.com"
                    />
                  </div>
                  <div className="auth-field">
                    <label htmlFor="admin-password" className="auth-label">
                      Password
                    </label>
                    <input
                      id="admin-password"
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      maxLength={256}
                      required
                      disabled={busy}
                      className="auth-input"
                      placeholder="••••••••••••"
                    />
                  </div>
                </>
              )}
              {step === "new_password" && (
                <>
                  <div className="auth-field">
                    <label htmlFor="admin-new-password" className="auth-label">
                      New password
                    </label>
                    <input
                      id="admin-new-password"
                      name="new_password"
                      type="password"
                      autoComplete="new-password"
                      minLength={16}
                      maxLength={256}
                      required
                      disabled={busy}
                      className="auth-input"
                    />
                  </div>
                  <div className="auth-field">
                    <label
                      htmlFor="admin-confirm-password"
                      className="auth-label"
                    >
                      Confirm new password
                    </label>
                    <input
                      id="admin-confirm-password"
                      name="confirm_password"
                      type="password"
                      autoComplete="new-password"
                      minLength={16}
                      maxLength={256}
                      required
                      disabled={busy}
                      className="auth-input"
                    />
                  </div>
                </>
              )}
              {["totp", "totp_enrollment"].includes(step) && (
                <div className="auth-field auth-field--totp">
                  <label
                    htmlFor="admin-authenticator-code"
                    className="auth-label"
                  >
                    Six-digit authenticator code
                  </label>
                  <input
                    id="admin-authenticator-code"
                    name="code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    placeholder="000000"
                    required
                    disabled={busy}
                    className="auth-input auth-input--totp"
                    autoFocus
                  />
                </div>
              )}
              <div className="auth-submit-wrap">
                <button
                  type="submit"
                  className="pill red auth-submit-btn"
                  disabled={busy}
                  aria-label={submitLabel}
                  aria-busy={busy}
                >
                  {busy ? (
                    <span className="auth-btn-loading">
                      <span className="auth-btn-spinner" aria-hidden="true" />
                      <span>Verifying…</span>
                    </span>
                  ) : (
                    submitLabel
                  )}
                </button>
              </div>
            </form>
          )}
          <p className="auth-expiry">
            This sign-in expires at{" "}
            <time dateTime={transaction.expires_at}>
              {new Date(transaction.expires_at).toLocaleTimeString([], {
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
              })}
            </time>
            .
          </p>
        </>
      )}
      {!busy &&
        (error || missingSetupKey || (transaction && step !== "password")) && (
          <div className="auth-restart-wrap">
            <button
              type="button"
              className="pill outline auth-restart-btn"
              onClick={restart}
            >
              Start again
            </button>
          </div>
        )}
    </div>
  );
}

export function AdminPasswordLogin() {
  const { sessions, refresh, logout } = useAuth();
  const [started, setStarted] = useState(false);
  const session = sessions.admin;
  const [params] = useSearchParams();
  const message = callbackMessage(params.get("error"));
  const reauthentication =
    params.get("reauth") === "1" ||
    (session.status === "authenticated" && Boolean(message));
  if (session.status === "authenticated" && !reauthentication && !message)
    return (
      <Navigate
        to={
          session.data.administrator.role === "owner"
            ? "/admin/dashboard"
            : "/admin"
        }
        replace
      />
    );
  return (
    <section className="admin-login-view">
      <h1 className="auth-heading">
        {reauthentication ? "Verify your access" : "Team sign-in"}
      </h1>
      <p className="auth-description">
        Sign in with your team email and password. Re-enter your password every
        4 hours. Your authenticator app is required every 24 hours. A new
        browser requires both.
      </p>
      <p className="auth-invitation-note">
        Administrator access is invitation only.
      </p>
      {message && <Alert>{message}</Alert>}
      {session.status === "error" && (
        <Alert>
          <p>{errorMessage(session.error)}</p>
          <button
            type="button"
            className="auth-session-retry"
            onClick={() => refresh("admin")}
          >
            Check session again
          </button>
        </Alert>
      )}
      {session.logoutPending && (
        <Alert>
          <p>We couldn’t confirm sign-out. Please retry to end your session.</p>
          <button
            type="button"
            className="auth-session-retry"
            onClick={() => logout("admin")}
          >
            Retry sign-out
          </button>
        </Alert>
      )}
      {session.status === "loading" ? (
        <div className="auth-loading" role="status">
          <span className="auth-spinner" aria-hidden="true" />
          <span>Checking your session…</span>
        </div>
      ) : (
        !session.logoutPending &&
        (started ? (
          <PasswordForm />
        ) : (
          <div className="actions auth-initial-actions">
            {/* Start the short-lived MFA transaction only after the user continues. */}
            <button
              type="button"
              className="pill red auth-submit-btn"
              onClick={() => setStarted(true)}
            >
              Continue with password
            </button>
          </div>
        ))
      )}
      <p className="auth-help-note">
        Need an invitation or help with your authenticator? Contact the account
        owner.
      </p>
    </section>
  );
}
