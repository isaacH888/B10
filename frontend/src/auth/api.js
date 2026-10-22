const configuredBase = import.meta.env.VITE_API_BASE_URL || "/api/v1";
if (configuredBase !== "/api/v1") {
  throw new Error("Authentication requires the same-origin /api/v1 API.");
}

export class ApiError extends Error {
  constructor(status, code) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

function validHealth(data, status) {
  if (!data || !["ok", "unavailable"].includes(data.database)
    || !["ready", "disabled", "unavailable"].includes(data.authentication)) return false;
  const ready = data.database === "ok" && data.authentication !== "unavailable";
  return data.status === (ready ? "ok" : "degraded") && status === (ready ? 200 : 503);
}

export async function apiRequest(path, options = {}) {
  const controller = new AbortController();
  const timeout = path === "/admin/password/transaction" && options.method === "POST" ? 45000
    : path === "/customer/test-email" && options.method === "POST" ? 20000 : 10000;
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${configuredBase}${path}`, {
      ...options,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json", ...options.headers },
    });
    const body = await response.json().catch(() => null);
    // Only the readiness endpoint uses a validated data envelope on HTTP 503.
    if (path === "/health" && [200, 503].includes(response.status)) {
      if (!validHealth(body?.data, response.status)) throw new ApiError(502, "invalid_response");
      return body.data;
    }
    if (!response.ok) {
      throw new ApiError(response.status, body?.error?.code || "request_failed");
    }
    if (!body || !Object.hasOwn(body, "data")) throw new ApiError(502, "invalid_response");
    return body.data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(503, "authentication_unavailable");
  } finally {
    clearTimeout(timer);
  }
}

// Redirects come only from the trusted API; never accept them from a query string.
export function navigateToProvider(value) {
  let url;
  try { url = new URL(value); } catch { throw new ApiError(502, "invalid_response"); }
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new ApiError(502, "invalid_response");
  }
  window.location.assign(url.href);
}

export function errorMessage(error) {
  if (error?.code === "authentication_failed") return "Sign-in could not be completed. Check your credentials and authenticator code, then start again.";
  if (error?.code === "login_expired") return "This sign-in has expired. Start again to continue.";
  if (error?.code === "password_reset_required") return "Contact the account owner to reset your administrator password.";
  if (error?.code === "email_verification_required") return "Verify your email address before signing in. Contact the account owner for help.";
  if (error?.code === "validation_error") return "Check the sign-in fields and password requirements, then start again.";
  if (error?.code === "reauthentication_required") return "Sign in with your authenticator again before continuing with this action.";
  if (error?.status === 403) return "This account does not have access. Contact the owner if you need team access.";
  if (error?.status === 429) return "Too many sign-in attempts. Please wait a few minutes and try again.";
  if (error?.status === 503) return "Sign-in is temporarily unavailable. Please try again later.";
  return "We couldn’t complete that request. Please try again.";
}

const callbackMessages = {
  mfa_required: "Secure sign-in did not confirm the required password and authenticator verification. If you just set up your authenticator, choose Continue with password again and enter a new code. If you already entered a code, contact the account owner to check the sign-in configuration.",
  reauthentication_required: "Sign in with your authenticator again before continuing with this action.",
  email_verification_required: "Verify your email address on the sign-in screen before continuing.",
  rate_limited: "Too many sign-in attempts. Please wait a few minutes and try again.",
  access_denied: "Access was denied. Please sign in with an authorized account.",
  forbidden: "This account does not have access. Contact the owner for team access.",
  admin_not_invited: "Team access is invitation only. Contact the owner for an invitation.",
  session_expired: "Your session has expired. Please sign in again.",
  login_expired: "That sign-in link has expired. Please start again.",
  authentication_failed: "Sign-in could not be completed. Please try again.",
  authentication_unavailable: "Sign-in is temporarily unavailable. Please try again later.",
};

export function callbackMessage(code) {
  return code ? (Object.hasOwn(callbackMessages, code) ? callbackMessages[code] : callbackMessages.authentication_failed) : "";
}
