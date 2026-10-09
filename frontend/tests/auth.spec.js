import { expect, test } from "@playwright/test";

const providerUrl = "https://test.auth.us-east-1.amazoncognito.com/oauth2/authorize";
const logoutUrl = "https://test.auth.us-east-1.amazoncognito.com/logout";
const origin = "http://127.0.0.1:5190";
const csrfToken = "test-memory-only-csrf-token";
const pendingCsrf = "test-memory-only-mfa-csrf";
const setupSecret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";
const approvalCode = "private-approved-google-ownership-proof";

function makeMfa(status, overrides = {}) {
  return {
    status, csrf_token: pendingCsrf,
    expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    ...(["approval_required", "challenge_required"].includes(status) ? { approval_code: approvalCode } : {}),
    ...overrides,
  };
}

function makeSession(area, overrides = {}) {
  const now = Date.now();
  return {
    [area === "admin" ? "administrator" : "customer"]: {
      id: `${area}-123`, email: `${area}@example.com`, name: "Macha",
      ...(area === "admin" ? { role: "staff", permissions: ["bookings:read", "bookings:contacts", "bookings:notes", "bookings:fulfill"] } : {}),
    },
    expires_at: new Date(now + 8 * 60 * 60 * 1000).toISOString(),
    idle_expires_at: new Date(now + 15 * 60 * 1000).toISOString(),
    csrf_token: csrfToken,
    ...overrides,
  };
}

async function mockApi(page, options = {}) {
  const requests = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const area = path.includes("/admin/") ? "admin" : "customer";
    requests.push({ path, method: request.method(), headers: request.headers(), body: request.postData() ? request.postDataJSON() : null });
    let status = 200;
    let body;
    if (path.endsWith("/admin/mfa") && request.method() === "GET") {
      status = typeof options.mfaStatus === "function" ? options.mfaStatus() : options.mfaStatus || (options.mfa ? 200 : 401);
      body = status === 200 ? { data: typeof options.mfa === "function" ? options.mfa() : options.mfa, meta: {} }
        : { error: { code: options.mfaErrorCode || "mfa_challenge_expired" } };
    } else if (path.endsWith("/admin/mfa/enroll")) {
      status = options.enrollStatus || 200;
      body = status === 200 ? { data: options.enrollment || {
        secret: setupSecret,
        otpauth_uri: `otpauth://totp/Popssibilities:admin%40example.com?secret=${setupSecret}&issuer=Popssibilities`,
        expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      }, meta: {} } : { error: { code: options.mfaErrorCode || "forbidden" } };
    } else if (path.endsWith("/admin/mfa/verify")) {
      status = typeof options.verifyStatus === "function" ? options.verifyStatus() : options.verifyStatus || 200;
      if (status === 200 && options.verifyResult !== "enrolled") options.admin = options.admin || makeSession("admin");
      body = status === 200 ? { data: { status: options.verifyResult || "authenticated" }, meta: {} }
        : { error: { code: options.mfaErrorCode || "invalid_mfa_code" } };
    } else if (path.endsWith("/admin/mfa") && request.method() === "DELETE") {
      status = options.cancelStatus || 200;
      body = status === 200 ? { data: { logout_url: options.logoutUrl || logoutUrl }, meta: {} }
        : { error: { code: options.mfaErrorCode || "authentication_unavailable" } };
    } else if (path.endsWith("/session") && request.method() === "GET") {
      const sessionStatus = options[`${area}Status`];
      status = (typeof sessionStatus === "function" ? sessionStatus() : sessionStatus) || (options[area] ? 200 : 401);
      body = status === 200 ? { data: options[area], meta: {} } : { error: { code: status === 403 ? "forbidden" : "authentication_unavailable", message: "Safe error", fields: [], request_id: "request-test" } };
    } else if (path.endsWith("/login")) {
      status = options.loginStatus || 200;
      body = status === 200 ? { data: { authorization_url: options.authorizationUrl || providerUrl }, meta: {} } : { error: { code: "authentication_unavailable", message: "Provider unavailable", fields: [], request_id: "request-test" } };
    } else if (path.endsWith("/session") && request.method() === "DELETE") {
      status = typeof options.logoutStatus === "function" ? options.logoutStatus() : options.logoutStatus || 200;
      body = status === 200 ? { data: { logout_url: logoutUrl }, meta: {} } : { error: { code: "authentication_unavailable", message: "Provider unavailable", fields: [], request_id: "request-test" } };
    } else {
      body = { data: { status: "ok", database: "ok" }, meta: {} };
    }
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("https://test.auth.us-east-1.amazoncognito.com/**", (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><h1>Secure provider screen</h1>" }));
  return requests;
}

test("signed-out customers are redirected to sign-in", async ({ page }) => {
  await mockApi(page);
  await page.goto("/account");
  await expect(page).toHaveURL(`${origin}/login`);
  await expect(page.getByRole("button", { name: "Continue with email" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Session details" })).not.toBeVisible();
});

for (const [provider, name] of [["password", "Continue with email"], ["google", "Continue with Google"]]) {
  test(`customer ${provider} sign-in sends the selected provider and redirects`, async ({ page }) => {
    const requests = await mockApi(page);
    await page.goto("/login");
    await page.getByRole("button", { name }).click();
    await expect(page).toHaveURL(providerUrl);
    const login = requests.find((request) => request.path.endsWith("/customer/login"));
    expect(login.body).toEqual({ provider });
    expect(login.headers.origin).toBe(origin);
  });
}

test("admin sign-in is invitation-only and uses the password/MFA provider flow", async ({ page }) => {
  const requests = await mockApi(page);
  await page.goto("/admin/login");
  await expect(page.getByText("Your authenticator app is required", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Continue with password" }).click();
  await expect(page).toHaveURL(providerUrl);
  expect(requests.find((request) => request.path.endsWith("/admin/login")).body).toEqual({ provider: "password" });
});

test("account reload restores the session without storing tokens", async ({ page }) => {
  const requests = await mockApi(page, { customer: makeSession("customer") });
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Welcome, Macha." })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome, Macha." })).toBeVisible();
  expect(requests.filter((request) => request.path === "/api/v1/customer/session").length).toBeGreaterThanOrEqual(2);
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }))).toEqual({ local: {}, session: {}, cookie: "" });
});

test("staff sees assigned booking permissions and no owner financial access", async ({ page }) => {
  await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Team account" })).toBeVisible();
  await expect(page.getByText("View bookings", { exact: true })).toBeVisible();
  await expect(page.getByText("Mark fulfillment", { exact: true })).toBeVisible();
  await expect(page.getByText("Manage payments", { exact: true })).not.toBeVisible();
  await expect(page.getByText("Export customer data", { exact: true })).not.toBeVisible();
});

test("owner capabilities come from the current server permissions", async ({ page }) => {
  const administrator = { id: "owner-123", email: "owner@example.com", name: "Owner", role: "owner", permissions: ["bookings:read", "payments:manage", "customers:export"] };
  await mockApi(page, { admin: makeSession("admin", { administrator }) });
  await page.goto("/admin");
  await expect(page.getByText("Manage payments", { exact: true })).toBeVisible();
  await expect(page.getByText("Export customer data", { exact: true })).toBeVisible();
  await expect(page.getByText("Confirm bookings", { exact: true })).not.toBeVisible();
});

test("a customer session does not grant admin access", async ({ page }) => {
  await mockApi(page, { customer: makeSession("customer") });
  await page.goto("/admin");
  await expect(page).toHaveURL(`${origin}/admin/login`);
  await expect(page.getByRole("heading", { name: "Team sign-in" })).toBeVisible();
});

test("active owners can verify password and MFA again without replaying an action", async ({ page }) => {
  const administrator = { id: "owner-123", email: "owner@example.com", name: "Owner", role: "owner", permissions: ["payments:manage"] };
  const requests = await mockApi(page, { admin: makeSession("admin", { administrator }) });
  await page.goto("/admin");
  await page.getByRole("link", { name: "Verify again" }).click();
  await expect(page).toHaveURL(`${origin}/admin/login?reauth=1`);
  await expect(page.getByRole("heading", { name: "Verify your access" })).toBeVisible();
  await page.getByRole("button", { name: "Continue with password" }).click();
  await expect(page).toHaveURL(providerUrl);
  const mutations = requests.filter((request) => request.method !== "GET");
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe("/api/v1/admin/login");
  expect(mutations[0].body).toEqual({ provider: "password" });
});

test("failed reauthentication remains visible when the previous session is active", async ({ page }) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin/login?error=authentication_failed");
  await expect(page.getByRole("alert")).toContainText("Sign-in could not be completed");
  await expect(page.getByRole("heading", { name: "Verify your access" })).toBeVisible();
  await expect(page).toHaveURL(`${origin}/admin/login?error=authentication_failed`);
  await page.getByRole("button", { name: "Continue with password" }).click();
  await expect(page).toHaveURL(providerUrl);
  expect(requests.filter((request) => request.method !== "GET")).toHaveLength(1);
});

test("a provider outage clears identity while allowing local logout with memory-only CSRF", async ({ page }) => {
  const now = Date.now();
  let polls = 0;
  await page.clock.install({ time: new Date(now) });
  const requests = await mockApi(page, { admin: makeSession("admin"), adminStatus: () => ++polls === 1 ? 200 : 503 });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Team account" })).toBeVisible();
  await page.clock.fastForward(61000);
  await expect(page.getByRole("heading", { name: "Sign-in unavailable" })).toBeVisible();
  await expect(page.getByText("admin@example.com", { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  expect(requests.find((request) => request.method === "DELETE").headers["x-csrf-token"]).toBe(csrfToken);
});

for (const [status, heading] of [[403, "Access unavailable"], [503, "Sign-in unavailable"]]) {
  test(`admin ${status} responses expose no protected account`, async ({ page }) => {
    await mockApi(page, { adminStatus: status });
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).not.toBeVisible();
  });
}

test("malformed session responses fail closed", async ({ page }) => {
  await mockApi(page, { admin: makeSession("admin", { csrf_token: null }) });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Sign-in unavailable" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

test("idle expiry warns, clears the account, and requires sign-in", async ({ page }) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  await mockApi(page, { admin: makeSession("admin", { idle_expires_at: new Date(now + 3000).toISOString() }) });
  await page.goto("/admin");
  await expect(page.getByRole("alert")).toContainText("Your session expires");
  await page.clock.fastForward(5000);
  await expect(page).toHaveURL(`${origin}/admin/login?error=session_expired`);
  await expect(page.getByRole("alert")).toContainText("Your session has expired");
});

test("session polling keeps the server idle deadline and sends no activity mutation", async ({ page }) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  const session = makeSession("admin", { idle_expires_at: new Date(now + 10 * 60 * 1000).toISOString() });
  const requests = await mockApi(page, { admin: session });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Team account" })).toBeVisible();
  await page.clock.fastForward(61000);
  await expect.poll(() => requests.filter((request) => request.path === "/api/v1/admin/session").length).toBeGreaterThanOrEqual(2);
  expect(requests.every((request) => request.method === "GET")).toBe(true);
  await expect(page.locator("time")).toHaveAttribute("datetime", session.idle_expires_at);
});

test("logout sends the in-memory CSRF token and redirects to provider logout", async ({ page }) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  const logout = requests.find((request) => request.method === "DELETE");
  expect(logout.path).toBe("/api/v1/admin/session");
  expect(logout.headers["x-csrf-token"]).toBe(csrfToken);
  expect(logout.headers.origin).toBe(origin);
});

test("logout failure clears protected content and offers a CSRF-preserving retry", async ({ page }) => {
  let attempts = 0;
  const requests = await mockApi(page, { admin: makeSession("admin"), logoutStatus: () => ++attempts === 1 ? 503 : 200 });
  await page.goto("/admin");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(`${origin}/admin/login`);
  await expect(page.getByRole("alert")).toContainText("We couldn’t confirm sign-out");
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  await page.getByRole("button", { name: "Retry sign-out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  expect(requests.filter((request) => request.method === "DELETE").every((request) => request.headers["x-csrf-token"] === csrfToken)).toBe(true);
});

test("unsafe provider redirects are rejected", async ({ page }) => {
  await mockApi(page, { authorizationUrl: "javascript:document.body.innerHTML='unsafe'" });
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue with email" }).click();
  await expect(page.getByRole("alert")).toContainText("We couldn’t complete that request");
  await expect(page).toHaveURL(`${origin}/login`);
  await expect(page.locator("body")).not.toHaveText("unsafe");
});

test("callback query errors are mapped to safe messages", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin/login?error=mfa_required");
  await expect(page.getByRole("alert")).toContainText("password and authenticator app");
  await page.goto("/login?error=%3Cscript%3Esecret%3C%2Fscript%3E");
  await expect(page.getByRole("alert")).toHaveText("Sign-in could not be completed. Please try again.");
  await expect(page.getByRole("alert")).not.toContainText("secret");
  await page.goto("/login?error=constructor");
  await expect(page.getByRole("alert")).toHaveText("Sign-in could not be completed. Please try again.");
});

test("login provider outages are actionable without exposing the account", async ({ page }) => {
  await mockApi(page, { loginStatus: 503 });
  await page.goto("/admin/login");
  await page.getByRole("button", { name: "Continue with password" }).click();
  await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
  await expect(page.getByRole("button", { name: "Continue with password" })).toBeEnabled();
});

test("administrator Google initiation sends its provider to the admin API", async ({ page }) => {
  const requests = await mockApi(page);
  await page.goto("/admin/login");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(providerUrl);
  const request = requests.find((entry) => entry.path === "/api/v1/admin/login");
  expect(request.body).toEqual({ provider: "google" });
  expect(request.headers.origin).toBe(origin);
  expect(requests.filter((entry) => entry.path === "/api/v1/customer/login")).toHaveLength(0);
});

test("an unapproved Google profile sees only a private approval receipt", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("approval_required") });
  await page.goto("/admin/mfa");
  await expect(page.getByRole("heading", { name: "Administrator approval required" })).toBeVisible();
  await expect(page.getByText(approvalCode, { exact: true })).toBeVisible();
  await expect(page.getByText("This Google sign-in has no administrator access", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create authenticator setup key" })).not.toBeVisible();
  await expect(page.getByLabel("Six-digit authenticator code")).not.toBeVisible();
  expect(requests.every((entry) => entry.method === "GET")).toBe(true);
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }))).toEqual({ local: {}, session: {}, cookie: "" });
  await page.getByRole("link", { name: "Admin session", exact: true }).click();
  await expect(page).toHaveURL(`${origin}/admin/login?error=session_expired`);
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

test("checking separately granted Google approval enables enrollment without access", async ({ page }) => {
  let mode = "approval_required";
  await mockApi(page, { mfa: () => makeMfa(mode) });
  await page.goto("/admin/mfa");
  await expect(page.getByText(approvalCode, { exact: true })).toBeVisible();
  mode = "enrollment_required";
  await page.getByRole("button", { name: "Check approval" }).click();
  await expect(page.getByRole("heading", { name: "Set up your authenticator" })).toBeVisible();
  await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

test("Google enrollment requires CSRF and a fresh login before administrator access", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("enrollment_required"), verifyResult: "enrolled" });
  await page.goto("/admin/mfa");
  await page.getByRole("button", { name: "Create authenticator setup key" }).click();
  await expect(page.getByText(setupSecret, { exact: true })).toBeVisible();
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page.getByRole("status")).toContainText("Authenticator enrolled. Sign in again");
  await expect(page).toHaveURL(`${origin}/admin/mfa`);
  await expect(page.getByText(setupSecret, { exact: true })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  const enrollment = requests.find((entry) => entry.path.endsWith("/mfa/enroll"));
  expect(enrollment.body).toEqual({});
  expect(enrollment.headers["x-csrf-token"]).toBe(pendingCsrf);
  const verification = requests.find((entry) => entry.path.endsWith("/mfa/verify"));
  expect(verification.body).toEqual({ code: "123456" });
  expect(verification.headers["x-csrf-token"]).toBe(pendingCsrf);
  const sessionReads = requests.filter((entry) => entry.path === "/api/v1/admin/session").length;
  await page.waitForTimeout(100);
  expect(requests.filter((entry) => entry.path === "/api/v1/admin/session").length).toBe(sessionReads);
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(providerUrl);
  expect(requests.find((entry) => entry.path === "/api/v1/admin/login").body).toEqual({ provider: "google" });
});

test("Google authenticator challenge grants access only after server verification", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("challenge_required") });
  await page.goto("/admin/mfa");
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Verify authenticator code" })).toBeDisabled();
  await page.getByLabel("Six-digit authenticator code").fill("234567");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page).toHaveURL(`${origin}/admin`);
  await expect(page.getByRole("heading", { name: "Team account" })).toBeVisible();
  expect(requests.find((entry) => entry.path.endsWith("/mfa/verify")).headers["x-csrf-token"]).toBe(pendingCsrf);
  expect(requests.filter((entry) => entry.path === "/api/v1/admin/session").length).toBeGreaterThanOrEqual(2);
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))).toEqual({ local: {}, session: {} });
});

test("existing administrator access never skips a Google authenticator challenge", async ({ page }) => {
  const requests = await mockApi(page, { admin: makeSession("admin"), mfa: makeMfa("challenge_required") });
  await page.goto("/admin/mfa");
  await expect(page.getByLabel("Six-digit authenticator code")).toBeVisible();
  await expect(page).toHaveURL(`${origin}/admin/mfa`);
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  expect(requests.filter((entry) => entry.method !== "GET")).toHaveLength(0);
});

test("invalid or replayed Google authenticator codes grant no access", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("challenge_required"), verifyStatus: 422 });
  await page.goto("/admin/mfa");
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page.getByRole("alert")).toContainText("valid unused authenticator code");
  await expect(page.getByLabel("Six-digit authenticator code")).toHaveValue("");
  await expect(page).toHaveURL(`${origin}/admin/mfa`);
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  expect(requests.filter((entry) => entry.path.endsWith("/mfa/verify"))).toHaveLength(1);
});

test("Google OTP rate limiting remains actionable without exposing access", async ({ page }) => {
  await mockApi(page, { mfa: makeMfa("challenge_required"), verifyStatus: 429, mfaErrorCode: "rate_limited" });
  await page.goto("/admin/mfa");
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page.getByRole("alert")).toContainText("Too many sign-in attempts");
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

for (const mode of ["approval_required", "enrollment_required", "challenge_required"]) {
  test(`expired ${mode} clears the receipt or setup secret`, async ({ page }) => {
    const now = Date.now();
    await page.clock.install({ time: new Date(now) });
    // Freeze the clock before rendering so worker scheduling cannot expire the
    // challenge before the test has observed its receipt or setup secret.
    const frozen = now + 60000;
    await page.clock.pauseAt(new Date(frozen));
    await mockApi(page, { mfa: makeMfa(mode, { expires_at: new Date(frozen + 3000).toISOString() }) });
    await page.goto("/admin/mfa");
    if (mode === "enrollment_required") {
      await page.getByRole("button", { name: "Create authenticator setup key" }).click();
      await expect(page.getByText(setupSecret, { exact: true })).toBeVisible();
    } else {
      if (mode === "challenge_required") await page.getByRole("button", { name: "Recover authenticator" }).click();
      await expect(page.getByText(approvalCode, { exact: true })).toBeVisible();
    }
    await page.clock.fastForward(5000);
    await expect(page.getByRole("alert")).toContainText("verification has expired");
    await expect(page.getByText(setupSecret, { exact: true })).not.toBeVisible();
    await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
    await expect(page.getByLabel("Six-digit authenticator code")).not.toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel sign-in" })).not.toBeVisible();
  });
}

for (const status of [401, 403]) {
  test(`Google challenge ${status} rejects verification and hides enrollment secrets`, async ({ page }) => {
    await mockApi(page, { mfa: makeMfa("enrollment_required"), verifyStatus: status, mfaErrorCode: status === 401 ? "mfa_challenge_expired" : "forbidden" });
    await page.goto("/admin/mfa");
    await page.getByRole("button", { name: "Create authenticator setup key" }).click();
    await page.getByLabel("Six-digit authenticator code").fill("123456");
    await page.getByRole("button", { name: "Verify authenticator code" }).click();
    await expect(page.getByText(setupSecret, { exact: true })).not.toBeVisible();
    await expect(page.getByLabel("Six-digit authenticator code")).not.toBeVisible();
    await expect(page.getByRole("link", { name: "Back to admin sign-in" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  });
}

test("pending Google logout uses its CSRF and redirects after clearing the receipt", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("approval_required") });
  await page.goto("/admin/mfa");
  await page.getByRole("button", { name: "Cancel sign-in" }).click();
  await expect(page).toHaveURL(logoutUrl);
  const cancellation = requests.find((entry) => entry.method === "DELETE");
  expect(cancellation.path).toBe("/api/v1/admin/mfa");
  expect(cancellation.headers["x-csrf-token"]).toBe(pendingCsrf);
  expect(cancellation.headers.origin).toBe(origin);
});

test("Google owner reauthentication preserves the fresh-login flow", async ({ page }) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  await page.getByRole("link", { name: "Verify again" }).click();
  await expect(page.getByRole("heading", { name: "Verify your access" })).toBeVisible();
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL(providerUrl);
  const mutations = requests.filter((entry) => entry.method !== "GET");
  expect(mutations).toHaveLength(1);
  expect(mutations[0].body).toEqual({ provider: "google" });
});

test("disabled Google access fails closed on pending status", async ({ page }) => {
  await mockApi(page, { mfaStatus: 403, mfaErrorCode: "forbidden" });
  await page.goto("/admin/mfa");
  await expect(page.getByRole("alert")).toContainText("does not have access");
  await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
  await expect(page.getByLabel("Six-digit authenticator code")).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

test("malformed pending approval response fails closed", async ({ page }) => {
  await mockApi(page, { mfa: makeMfa("approval_required", { csrf_token: null }) });
  await page.goto("/admin/mfa");
  await expect(page.getByRole("alert")).toContainText("couldn’t complete that request");
  await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Create authenticator setup key" })).not.toBeVisible();
});

test("a Google administrator session displays current role changes from server polling", async ({ page }) => {
  await page.clock.install({ time: new Date(Date.now()) });
  const options = { mfa: makeMfa("challenge_required") };
  await mockApi(page, options);
  await page.goto("/admin/mfa");
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page).toHaveURL(`${origin}/admin`);
  await expect(page.getByText("Staff", { exact: true })).toBeVisible();
  options.admin = makeSession("admin", { administrator: {
    id: "admin-123", name: "Macha", email: "admin@example.com", role: "owner", permissions: ["bookings:read", "payments:manage"],
  } });
  await page.clock.fastForward(61000);
  await expect(page.getByText("Owner", { exact: true })).toBeVisible();
  await expect(page.getByText("Manage payments", { exact: true })).toBeVisible();
  options.admin = makeSession("admin");
  await page.clock.fastForward(61000);
  await expect(page.getByText("Staff", { exact: true })).toBeVisible();
  await expect(page.getByText("Manage payments", { exact: true })).not.toBeVisible();
});

test("disabling a verified Google administrator hides the active account", async ({ page }) => {
  await page.clock.install({ time: new Date(Date.now()) });
  let active = true;
  await mockApi(page, { mfa: makeMfa("challenge_required"), adminStatus: () => active ? 200 : 403 });
  await page.goto("/admin/mfa");
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
  await expect(page).toHaveURL(`${origin}/admin`);
  await expect(page.getByText("admin@example.com", { exact: true })).toBeVisible();
  active = false;
  await page.clock.fastForward(61000);
  await expect(page.getByRole("heading", { name: "Access unavailable" })).toBeVisible();
  await expect(page.getByText("admin@example.com", { exact: true })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
});

test("pending Google administrator verification leaves a customer session available", async ({ page }) => {
  const customer = makeSession("customer");
  const requests = await mockApi(page, { customer, mfa: makeMfa("approval_required") });
  await page.goto("/admin/mfa");
  await expect(page.getByText(approvalCode, { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Customer session", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Welcome, Macha." })).toBeVisible();
  await expect(page.getByText("customer@example.com", { exact: true })).toBeVisible();
  expect(requests.filter((entry) => entry.method !== "GET")).toHaveLength(0);
});

test("Google authenticator recovery reveals a private proof without resetting or granting access", async ({ page }) => {
  const requests = await mockApi(page, { mfa: makeMfa("challenge_required") });
  await page.goto("/admin/mfa");
  await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
  await page.getByRole("button", { name: "Recover authenticator" }).click();
  await expect(page.getByText(approvalCode, { exact: true })).toBeVisible();
  await expect(page.getByText("The operator must verify your identity separately", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create authenticator setup key" })).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "Team account" })).not.toBeVisible();
  expect(requests.every((entry) => entry.method === "GET")).toBe(true);
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))).toEqual({ local: {}, session: {} });
  await page.getByRole("link", { name: "Customer login", exact: true }).click();
  await expect(page.getByText(approvalCode, { exact: true })).not.toBeVisible();
});
