import { expect, test } from "@playwright/test";

const providerUrl = "https://test.auth.us-east-1.amazoncognito.com/oauth2/authorize";
const logoutUrl = "https://test.auth.us-east-1.amazoncognito.com/logout";
const origin = "http://127.0.0.1:5190";
const csrfToken = "test-memory-only-csrf-token";

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
    if (path.endsWith("/session") && request.method() === "GET") {
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
  await expect(page.getByRole("button", { name: "Continue with Google" })).not.toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Continue to team sign-in" }).click();
  await expect(page).toHaveURL(providerUrl);
  expect(requests.find((request) => request.path.endsWith("/admin/login")).body).toEqual({});
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
  await page.getByRole("button", { name: "Continue to team sign-in" }).click();
  await expect(page).toHaveURL(providerUrl);
  const mutations = requests.filter((request) => request.method !== "GET");
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe("/api/v1/admin/login");
  expect(mutations[0].body).toEqual({});
});

test("failed reauthentication remains visible when the previous session is active", async ({ page }) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin/login?error=authentication_failed");
  await expect(page.getByRole("alert")).toContainText("Sign-in could not be completed");
  await expect(page.getByRole("heading", { name: "Verify your access" })).toBeVisible();
  await expect(page).toHaveURL(`${origin}/admin/login?error=authentication_failed`);
  await page.getByRole("button", { name: "Continue to team sign-in" }).click();
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
  await page.getByRole("button", { name: "Continue to team sign-in" }).click();
  await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
  await expect(page.getByRole("button", { name: "Continue to team sign-in" })).toBeEnabled();
});
