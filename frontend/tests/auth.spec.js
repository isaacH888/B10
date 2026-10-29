import { expect, test } from "@playwright/test";
import jsQR from "jsqr";

const providerUrl =
  "https://test.auth.us-east-1.amazoncognito.com/oauth2/authorize";
const logoutUrl = "https://test.auth.us-east-1.amazoncognito.com/logout";
const origin = "http://127.0.0.1:5190";
const csrfToken = "test-memory-only-csrf-token";
const nativeCsrf = "test-memory-only-native-csrf";
const setupSecret = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";

function nativeTransaction(step = "password", overrides = {}) {
  return {
    step,
    csrf_token: nativeCsrf,
    expires_at: new Date(Date.now() + 300000).toISOString(),
    ...overrides,
  };
}

async function readAuthenticatorQr(page) {
  const pixels = await page
    .getByRole("img", { name: "Authenticator setup QR code" })
    .evaluate(async (svg) => {
      const source = URL.createObjectURL(
        new Blob([new XMLSerializer().serializeToString(svg)], {
          type: "image/svg+xml",
        }),
      );
      try {
        const image = new Image();
        image.src = source;
        await image.decode();
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 480;
        const context = canvas.getContext("2d");
        context.drawImage(image, 0, 0, 480, 480);
        return Array.from(context.getImageData(0, 0, 480, 480).data);
      } finally {
        URL.revokeObjectURL(source);
      }
    });
  const decoded = jsQR(new Uint8ClampedArray(pixels), 480, 480);
  expect(decoded).not.toBeNull();
  return new URL(decoded.data);
}

async function submitPassword(page) {
  if (!(await page.locator(".admin-password-login").count()))
    await openAdminSignIn(page);
  await page.getByLabel("Team email").fill("admin@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-private-password");
  await page.getByRole("button", { name: "Continue with password" }).click();
}

async function submitCode(page) {
  if (!(await page.locator(".admin-password-login").count()))
    await openAdminSignIn(page);
  await page.getByLabel("Six-digit authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator code" }).click();
}

async function openAdminSignIn(page) {
  await page
    .locator(".actions")
    .getByRole("button", { name: "Continue with password" })
    .click();
}

function makeSession(area, overrides = {}) {
  const now = Date.now();
  return {
    [area === "admin" ? "administrator" : "customer"]: {
      id: `${area}-123`,
      email: `${area}@example.com`,
      name: "Macha",
      ...(area === "admin"
        ? {
            role: "staff",
            permissions: [
              "bookings:read",
              "bookings:contacts",
              "bookings:notes",
              "bookings:fulfill",
            ],
          }
        : {}),
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
    requests.push({
      path,
      method: request.method(),
      headers: request.headers(),
      body: request.postData() ? request.postDataJSON() : null,
    });
    let status = 200;
    let body;
    if (path === "/api/v1/live" && options.liveUnavailable) {
      await route.abort("connectionrefused");
      return;
    } else if (path === "/api/v1/health") {
      status = options.healthStatus || 200;
      body = {
        data: options.health || {
          status: "ok",
          database: "ok",
          authentication: "ready",
        },
        meta: {},
      };
    } else if (path === "/api/v1/admin/password/transaction") {
      if (request.method() === "GET") {
        status = options.transactionStatus || 200;
        body =
          status === 200
            ? { data: options.transaction || nativeTransaction(), meta: {} }
            : {
                error: {
                  code: options.nativeError || "authentication_unavailable",
                },
              };
      } else if (request.method() === "DELETE") {
        options.transaction = nativeTransaction();
        body = { data: { step: "cancelled" }, meta: {} };
      } else {
        const next = options.nativeResponses?.shift() || {
          data: nativeTransaction("totp"),
        };
        if (next.delay)
          await new Promise((resolve) => setTimeout(resolve, next.delay));
        status = next.status || 200;
        if (status === 200) {
          options.transaction = next.data;
          if (next.data.step === "complete" && !options.completeWithoutSession)
            options.admin ||= makeSession("admin");
          body = { data: next.data, meta: {} };
        } else {
          options.transaction = null;
          body = {
            error: {
              code: next.code || "authentication_failed",
              message: "private-provider-details",
            },
          };
        }
      }
    } else if (path.endsWith("/session") && request.method() === "GET") {
      const sessionStatus = options[`${area}Status`];
      status =
        (typeof sessionStatus === "function"
          ? sessionStatus()
          : sessionStatus) || (options[area] ? 200 : 401);
      body =
        status === 200
          ? { data: options[area], meta: {} }
          : {
              error: {
                code:
                  status === 403 ? "forbidden" : "authentication_unavailable",
                message: "Safe error",
                fields: [],
                request_id: "request-test",
              },
            };
    } else if (path.endsWith("/login")) {
      status = options.loginStatus || 200;
      body =
        status === 200
          ? {
              data: {
                authorization_url: options.authorizationUrl || providerUrl,
              },
              meta: {},
            }
          : {
              error: {
                code: "authentication_unavailable",
                message: "Provider unavailable",
                fields: [],
                request_id: "request-test",
              },
            };
    } else if (path.endsWith("/session") && request.method() === "DELETE") {
      status =
        typeof options.logoutStatus === "function"
          ? options.logoutStatus()
          : options.logoutStatus || 200;
      body =
        status === 200
          ? { data: { logout_url: logoutUrl }, meta: {} }
          : {
              error: {
                code: "authentication_unavailable",
                message: "Provider unavailable",
                fields: [],
                request_id: "request-test",
              },
            };
    } else {
      body = { data: { status: "ok", database: "ok" }, meta: {} };
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.route(
    "https://test.auth.us-east-1.amazoncognito.com/**",
    (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<!doctype html><h1>Secure provider screen</h1>",
      }),
  );
  return requests;
}

test("signed-out customers are redirected to sign-in", async ({ page }) => {
  await mockApi(page);
  await page.goto("/account");
  await expect(page).toHaveURL(`${origin}/login`);
  await expect(
    page.getByRole("button", { name: "Continue with email and password" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Session details" }),
  ).not.toBeVisible();
});

for (const [provider, name] of [
  ["password", "Continue with email and password"],
  ["google", "Continue with Google"],
]) {
  test(`customer ${provider} sign-in sends the selected provider and redirects`, async ({
    page,
  }) => {
    const requests = await mockApi(page);
    await page.goto("/login");
    await page.getByRole("button", { name }).click();
    await expect(page).toHaveURL(providerUrl);
    const login = requests.find((request) =>
      request.path.endsWith("/customer/login"),
    );
    expect(login.body).toEqual({ provider });
    expect(login.headers.origin).toBe(origin);
  });
}

test("admin sign-in is invitation-only and submits password with its bound CSRF", async ({
  page,
}) => {
  const requests = await mockApi(page);
  await page.goto("/admin/login");
  await expect(
    page.getByText("Your authenticator app is required", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Team email")).not.toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).not.toBeVisible();
  expect(
    requests.filter(
      (request) => request.path === "/api/v1/admin/password/transaction",
    ),
  ).toHaveLength(0);
  await submitPassword(page);
  await expect(
    page.getByRole("heading", { name: "Verify your authenticator" }),
  ).toBeVisible();
  const request = requests.find((request) => request.method === "POST");
  expect(request.path).toBe("/api/v1/admin/password/transaction");
  expect(request.body).toEqual({
    email: "admin@example.com",
    password: "synthetic-private-password",
  });
  expect(request.headers["x-csrf-token"]).toBe(nativeCsrf);
  expect(request.headers.origin).toBe(origin);
  expect(
    requests.filter((request) => request.path.endsWith("/admin/login")),
  ).toHaveLength(0);
});

test("account reload restores the session without storing tokens", async ({
  page,
}) => {
  const requests = await mockApi(page, { customer: makeSession("customer") });
  await page.goto("/account");
  await expect(
    page.getByRole("heading", { name: "Welcome, Macha." }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome, Macha." }),
  ).toBeVisible();
  expect(
    requests.filter((request) => request.path === "/api/v1/customer/session")
      .length,
  ).toBeGreaterThanOrEqual(2);
  expect(
    await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
      cookie: document.cookie,
    })),
  ).toEqual({ local: {}, session: {}, cookie: "" });
});

test("staff sees assigned booking permissions and no owner financial access", async ({
  page,
}) => {
  await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).toBeVisible();
  await expect(page.getByText("View bookings", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Mark fulfillment", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Manage payments", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByText("Export customer data", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Booking workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Management workspace" }),
  ).not.toBeVisible();
});

test("owner capabilities come from the current server permissions", async ({
  page,
}) => {
  const administrator = {
    id: "owner-123",
    email: "owner@example.com",
    name: "Owner",
    role: "owner",
    permissions: ["bookings:read", "payments:manage", "customers:export"],
  };
  await mockApi(page, { admin: makeSession("admin", { administrator }) });
  await page.goto("/admin");
  await expect(
    page.getByText("Manage payments", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Export customer data", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Confirm bookings", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByText("Payment management preview", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Customer export preview", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Booking management preview", { exact: true }),
  ).not.toBeVisible();
});

test("a customer session does not grant admin access", async ({ page }) => {
  await mockApi(page, { customer: makeSession("customer") });
  await page.goto("/admin");
  await expect(page).toHaveURL(`${origin}/admin/login`);
  await expect(
    page.getByRole("heading", { name: "Team sign-in" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
});

test("active owners verify password and native MFA again without replaying an action", async ({
  page,
}) => {
  const administrator = {
    id: "owner-123",
    email: "owner@example.com",
    name: "Owner",
    role: "owner",
    permissions: ["payments:manage"],
  };
  const requests = await mockApi(page, {
    admin: makeSession("admin", { administrator }),
  });
  await page.goto("/admin");
  await page.getByRole("link", { name: "Verify again" }).click();
  await expect(page).toHaveURL(`${origin}/admin/login?reauth=1`);
  await expect(
    page.getByRole("heading", { name: "Verify your access" }),
  ).toBeVisible();
  await submitPassword(page);
  await expect(
    page.getByRole("heading", { name: "Verify your authenticator" }),
  ).toBeVisible();
  const mutations = requests.filter((request) => request.method !== "GET");
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe("/api/v1/admin/password/transaction");
});

test("failed reauthentication remains visible when the previous session is active", async ({
  page,
}) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin/login?error=authentication_failed");
  await expect(page.getByRole("alert")).toContainText(
    "Sign-in could not be completed",
  );
  await expect(
    page.getByRole("heading", { name: "Verify your access" }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    `${origin}/admin/login?error=authentication_failed`,
  );
  await submitPassword(page);
  await expect(
    page.getByRole("heading", { name: "Verify your authenticator" }),
  ).toBeVisible();
  expect(requests.filter((request) => request.method !== "GET")).toHaveLength(
    1,
  );
});

test("a provider outage clears identity while allowing local logout with memory-only CSRF", async ({
  page,
}) => {
  const now = Date.now();
  let polls = 0;
  await page.clock.install({ time: new Date(now) });
  const requests = await mockApi(page, {
    admin: makeSession("admin"),
    adminStatus: () => (++polls === 1 ? 200 : 503),
  });
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).toBeVisible();
  await page.clock.fastForward(61000);
  await expect(
    page.getByRole("heading", { name: "Sign-in unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByText("admin@example.com", { exact: true }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  expect(
    requests.find((request) => request.method === "DELETE").headers[
      "x-csrf-token"
    ],
  ).toBe(csrfToken);
});

for (const [status, heading] of [
  [403, "Access unavailable"],
  [503, "Sign-in unavailable"],
]) {
  test(`admin ${status} responses expose no protected account`, async ({
    page,
  }) => {
    await mockApi(page, { adminStatus: status });
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Admin dashboard" }),
    ).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sign out" }),
    ).not.toBeVisible();
  });
}

test("malformed session responses fail closed", async ({ page }) => {
  await mockApi(page, { admin: makeSession("admin", { csrf_token: null }) });
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Sign-in unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
});

test("idle expiry warns, clears the account, and requires sign-in", async ({
  page,
}) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  await mockApi(page, {
    admin: makeSession("admin", {
      idle_expires_at: new Date(now + 3000).toISOString(),
    }),
  });
  await page.goto("/admin");
  await expect(page.getByRole("alert")).toContainText("Your session expires");
  await page.clock.fastForward(5000);
  await expect(page).toHaveURL(`${origin}/admin/login?error=session_expired`);
  await expect(page.getByRole("alert")).toContainText(
    "Your session has expired",
  );
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
});

test("session polling keeps the server idle deadline and sends no activity mutation", async ({
  page,
}) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  const session = makeSession("admin", {
    idle_expires_at: new Date(now + 10 * 60 * 1000).toISOString(),
  });
  const requests = await mockApi(page, { admin: session });
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).toBeVisible();
  await page.clock.fastForward(61000);
  await expect
    .poll(
      () =>
        requests.filter((request) => request.path === "/api/v1/admin/session")
          .length,
    )
    .toBeGreaterThanOrEqual(2);
  expect(requests.every((request) => request.method === "GET")).toBe(true);
  await expect(page.locator("time")).toHaveAttribute(
    "datetime",
    session.idle_expires_at,
  );
});

test("logout sends the in-memory CSRF token and redirects to provider logout", async ({
  page,
}) => {
  const requests = await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  const logout = requests.find((request) => request.method === "DELETE");
  expect(logout.path).toBe("/api/v1/admin/session");
  expect(logout.headers["x-csrf-token"]).toBe(csrfToken);
  expect(logout.headers.origin).toBe(origin);
});

test("logout failure clears protected content and offers a CSRF-preserving retry", async ({
  page,
}) => {
  let attempts = 0;
  const requests = await mockApi(page, {
    admin: makeSession("admin"),
    logoutStatus: () => (++attempts === 1 ? 503 : 200),
  });
  await page.goto("/admin");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(`${origin}/admin/login`);
  await expect(page.getByRole("alert")).toContainText(
    "We couldn’t confirm sign-out",
  );
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await page.getByRole("button", { name: "Retry sign-out" }).click();
  await expect(page).toHaveURL(logoutUrl);
  expect(
    requests
      .filter((request) => request.method === "DELETE")
      .every((request) => request.headers["x-csrf-token"] === csrfToken),
  ).toBe(true);
});

test("unsafe provider redirects are rejected", async ({ page }) => {
  await mockApi(page, {
    authorizationUrl: "javascript:document.body.innerHTML='unsafe'",
  });
  await page.goto("/login");
  await page
    .getByRole("button", { name: "Continue with email and password" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "We couldn’t complete that request",
  );
  await expect(page).toHaveURL(`${origin}/login`);
  await expect(page.locator("body")).not.toHaveText("unsafe");
});

test("callback query errors are mapped to safe messages", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin/login?error=mfa_required");
  await expect(page.getByRole("alert")).toContainText(
    "password and authenticator verification",
  );
  await page.goto("/login?error=%3Cscript%3Esecret%3C%2Fscript%3E");
  await expect(page.getByRole("alert")).toHaveText(
    "Sign-in could not be completed. Please try again.",
  );
  await expect(page.getByRole("alert")).not.toContainText("secret");
  await page.goto("/login?error=constructor");
  await expect(page.getByRole("alert")).toHaveText(
    "Sign-in could not be completed. Please try again.",
  );
});

test("native admin sign-in outages are actionable without exposing the account", async ({
  page,
}) => {
  await mockApi(page, { transactionStatus: 503 });
  await page.goto("/admin/login");
  await openAdminSignIn(page);
  await expect(page.getByRole("alert")).toContainText(
    "temporarily unavailable",
  );
  await expect(page.getByRole("button", { name: "Start again" })).toBeEnabled();
  await expect(page.getByLabel("Password", { exact: true })).not.toBeVisible();
});

test("a verified native password and TOTP login opens the protected sample dashboard", async ({
  page,
}) => {
  const requests = await mockApi(page, {
    nativeResponses: [
      { data: nativeTransaction("totp") },
      { data: nativeTransaction("complete") },
    ],
  });
  await page.goto("/admin/login");
  await submitPassword(page);
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
  await submitCode(page);
  await expect(page).toHaveURL(`${origin}/admin`);
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Sample data", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("These fictional bookings", { exact: false }),
  ).toBeVisible();
  const bookings = page.getByRole("table", { name: "Sample bookings" });
  await expect(bookings.getByRole("row")).toHaveCount(4);
  await expect(
    bookings.getByRole("rowheader", { name: "SAMPLE-001" }),
  ).toBeVisible();
  expect(
    requests
      .filter((entry) => entry.method === "POST")
      .map((entry) => entry.body),
  ).toEqual([
    { email: "admin@example.com", password: "synthetic-private-password" },
    { code: "123456" },
  ]);
  expect(
    requests
      .filter((entry) => entry.method === "POST")
      .every(
        (entry) =>
          entry.headers["x-csrf-token"] === nativeCsrf &&
          entry.headers.origin === origin,
      ),
  ).toBe(true);
  expect(
    await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
      cookie: document.cookie,
    })),
  ).toEqual({ local: {}, session: {}, cookie: "" });
});

for (const provider of ["password", "google"]) {
  test(`a successful customer ${provider} return opens the customer account`, async ({
    page,
  }) => {
    const options = {};
    const requests = await mockApi(page, options);
    await page.goto("/login");
    await page
      .getByRole("button", {
        name:
          provider === "google"
            ? "Continue with Google"
            : "Continue with email and password",
      })
      .click();
    await expect(page).toHaveURL(providerUrl);
    options.customer = makeSession("customer");
    await page.goto("/login");
    await expect(page).toHaveURL(`${origin}/account`);
    await expect(
      page.getByRole("heading", { name: "Welcome, Macha." }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Admin dashboard" }),
    ).not.toBeVisible();
    expect(
      requests.filter((entry) => entry.path === "/api/v1/admin/login"),
    ).toHaveLength(0);
  });
}

test("the former admin Google verification page returns to password sign-in", async ({
  page,
}) => {
  const requests = await mockApi(page);
  await page.goto("/admin/mfa");
  await expect(page).toHaveURL(`${origin}/admin/login?reauth=1`);
  await expect(
    page.getByRole("button", { name: "Continue with password" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toHaveCount(0);
  expect(requests.filter((entry) => entry.path.includes("/mfa"))).toHaveLength(
    0,
  );
});

test("booking previews require the server-assigned booking permission", async ({
  page,
}) => {
  const administrator = {
    id: "owner-123",
    email: "owner@example.com",
    name: "Owner",
    role: "owner",
    permissions: ["payments:manage"],
  };
  await mockApi(page, { admin: makeSession("admin", { administrator }) });
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).toBeVisible();
  await expect(
    page.getByText("Booking access is not assigned to this account."),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Total bookings" }),
  ).not.toBeVisible();
  await expect(
    page.getByText("Payment management preview", { exact: true }),
  ).toBeVisible();
});

test("the sample dashboard follows live role and permission changes", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(Date.now()) });
  const options = { admin: makeSession("admin") };
  await mockApi(page, options);
  await page.goto("/admin");
  await expect(page.getByText("Staff", { exact: true })).toBeVisible();
  options.admin = makeSession("admin", {
    administrator: {
      id: "admin-123",
      name: "Macha",
      email: "admin@example.com",
      role: "owner",
      permissions: ["bookings:read", "payments:manage"],
    },
  });
  await page.clock.fastForward(61000);
  await expect(page.getByText("Owner", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Payment management preview", { exact: true }),
  ).toBeVisible();
  options.admin = makeSession("admin");
  await page.clock.fastForward(61000);
  await expect(page.getByText("Staff", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Payment management preview", { exact: true }),
  ).not.toBeVisible();
});

test("disabled administrator access clears the sample dashboard", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(Date.now()) });
  let active = true;
  await mockApi(page, {
    admin: makeSession("admin"),
    adminStatus: () => (active ? 200 : 403),
  });
  await page.goto("/admin");
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).toBeVisible();
  active = false;
  await page.clock.fastForward(61000);
  await expect(
    page.getByRole("heading", { name: "Access unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByText("admin@example.com", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
});

test("the basic dashboard fits a narrow viewport with readable sample bookings", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await mockApi(page, { admin: makeSession("admin") });
  await page.goto("/admin");
  const table = page.getByRole("region", { name: "Sample bookings" });
  await expect(table).toBeVisible();
  await table.focus();
  await expect(table).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

for (const scenario of [
  {
    label: "database unavailable",
    status: 503,
    health: {
      status: "degraded",
      database: "unavailable",
      authentication: "unavailable",
    },
    message:
      "Backend reachable. Database unavailable or not configured. Authentication storage is unavailable.",
  },
  {
    label: "authentication schema unavailable",
    status: 503,
    health: {
      status: "degraded",
      database: "ok",
      authentication: "unavailable",
    },
    message:
      "Backend reachable. Database connectivity verified. Authentication storage is unavailable.",
  },
  {
    label: "authentication disabled",
    status: 200,
    health: { status: "ok", database: "ok", authentication: "disabled" },
    message:
      "Backend reachable. Database connectivity verified. Sign-in is disabled.",
  },
  {
    label: "database unavailable and authentication disabled",
    status: 503,
    health: {
      status: "degraded",
      database: "unavailable",
      authentication: "disabled",
    },
    message:
      "Backend reachable. Database unavailable or not configured. Sign-in is disabled.",
  },
  {
    label: "local readiness verified",
    status: 200,
    health: { status: "ok", database: "ok", authentication: "ready" },
    message:
      "Backend reachable. Database connectivity verified. Authentication configuration and storage are ready.",
  },
]) {
  test(`connection diagnostics distinguish ${scenario.label}`, async ({
    page,
  }) => {
    const requests = await mockApi(page, {
      healthStatus: scenario.status,
      health: scenario.health,
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Check backend connection" })
      .click();
    await expect(page.getByRole("status")).toHaveText(scenario.message);
    await expect(
      page.getByRole("button", { name: "Check backend connection" }),
    ).toBeEnabled();
    expect(
      requests
        .filter((request) =>
          ["/api/v1/live", "/api/v1/health"].includes(request.path),
        )
        .map((request) => request.path),
    ).toEqual(["/api/v1/live", "/api/v1/health"]);
  });
}

test("an unreachable backend is distinct from failed readiness", async ({
  page,
}) => {
  const requests = await mockApi(page, { liveUnavailable: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Check backend connection" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "The backend connection could not be verified. Check that the backend is running.",
  );
  expect(
    requests.filter((request) => request.path === "/api/v1/health"),
  ).toHaveLength(0);
});

test("malformed readiness data is not accepted as verified configuration", async ({
  page,
}) => {
  await mockApi(page, {
    healthStatus: 503,
    health: {
      status: "degraded",
      database: "ok",
      authentication: "ready",
      detail: "private-driver-details",
    },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Check backend connection" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Backend reachable. Readiness could not be checked. Please try again.",
  );
  await expect(page.locator("body")).not.toContainText(
    "private-driver-details",
  );
});

test("the readiness exception never accepts a failed administrator session", async ({
  page,
}) => {
  await mockApi(page);
  await page.route("**/api/v1/admin/session", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        data: {
          ...makeSession("admin"),
          status: "degraded",
          database: "unavailable",
          authentication: "unavailable",
        },
      }),
    }),
  );
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Sign-in unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
});

test("a failed admin authenticator callback gives setup and configuration guidance without dashboard access", async ({
  page,
}) => {
  const requests = await mockApi(page);
  await page.goto("/admin/login?error=mfa_required");
  await expect(page.getByRole("alert")).toHaveText(
    "Secure sign-in did not confirm the required password and authenticator verification. If you just set up your authenticator, choose Continue with password again and enter a new code. If you already entered a code, contact the account owner to check the sign-in configuration.",
  );
  await expect(
    page.getByRole("button", { name: "Continue with password" }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("table", { name: "Sample bookings" }),
  ).not.toBeVisible();
  await page
    .getByRole("link", { name: "Admin dashboard", exact: true })
    .click();
  await expect(page).toHaveURL(`${origin}/admin/login`);
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await submitPassword(page);
  await expect(
    page.getByRole("heading", { name: "Verify your authenticator" }),
  ).toBeVisible();
  const mutations = requests.filter((request) => request.method !== "GET");
  expect(mutations).toHaveLength(1);
  expect(mutations[0].path).toBe("/api/v1/admin/password/transaction");
});

test("an invited administrator replaces the password and enrolls before a separate MFA login", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 740 });
  const requests = await mockApi(page, {
    nativeResponses: [
      { data: nativeTransaction("new_password") },
      {
        data: nativeTransaction("totp_enrollment", {
          enrollment_secret: setupSecret,
        }),
      },
      { data: nativeTransaction("password", { enrollment_complete: true }) },
      { data: nativeTransaction("totp") },
      { data: nativeTransaction("complete") },
    ],
  });
  await page.goto("/admin/login");
  await submitPassword(page);
  await expect(
    page.getByRole("heading", { name: "Choose a new password" }),
  ).toBeVisible();
  await page
    .getByLabel("New password", { exact: true })
    .fill("synthetic-new-password");
  await page.getByLabel("Confirm new password").fill("synthetic-new-password");
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(
    page.getByRole("heading", { name: "Set up your authenticator" }),
  ).toBeVisible();
  await expect(page.getByText(setupSecret, { exact: true })).toBeVisible();
  const qr = page.getByRole("img", { name: "Authenticator setup QR code" });
  await expect(qr).toBeVisible();
  const uri = await readAuthenticatorQr(page);
  expect(uri.protocol).toBe("otpauth:");
  expect(uri.hostname).toBe("totp");
  expect(decodeURIComponent(uri.pathname)).toBe(
    "/Popsibilities Admin:admin@example.com",
  );
  expect(Object.fromEntries(uri.searchParams)).toEqual({
    secret: setupSecret,
    issuer: "Popsibilities Admin",
    algorithm: "SHA1",
    digits: "6",
    period: "30",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await submitCode(page);
  await expect(qr).toHaveCount(0);
  await expect(
    page.getByText("Authenticator enrolled.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await expect(page.getByText(setupSecret, { exact: true })).not.toBeVisible();
  await submitPassword(page);
  await submitCode(page);
  await expect(page).toHaveURL(`${origin}/admin`);
  expect(
    requests
      .filter((entry) => entry.method === "POST")
      .map((entry) => Object.keys(entry.body)),
  ).toEqual([
    ["email", "password"],
    ["new_password"],
    ["code"],
    ["email", "password"],
    ["code"],
  ]);
  expect(
    await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    })),
  ).toEqual({ local: {}, session: {} });
  expect(JSON.stringify(requests)).not.toContain(setupSecret);
  expect(JSON.stringify(requests)).not.toContain("otpauth:");
});

for (const [code, status, message] of [
  ["authentication_failed", 401, "Check your credentials"],
  ["admin_not_invited", 403, "does not have access"],
  ["rate_limited", 429, "Too many sign-in attempts"],
  ["authentication_unavailable", 503, "temporarily unavailable"],
]) {
  test(`a native ${code} failure clears the form and cannot open the dashboard`, async ({
    page,
  }) => {
    await mockApi(page, {
      nativeResponses: [{ data: nativeTransaction("totp") }, { status, code }],
    });
    await page.goto("/admin/login");
    await submitPassword(page);
    await submitCode(page);
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByRole("alert")).not.toContainText(
      "private-provider-details",
    );
    await expect(
      page.getByRole("heading", { name: "Admin dashboard" }),
    ).not.toBeVisible();
    await expect(
      page.getByLabel("Six-digit authenticator code"),
    ).not.toBeVisible();
    await page.getByRole("button", { name: "Start again" }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  });
}

test("a claimed native completion still requires a valid protected session", async ({
  page,
}) => {
  await mockApi(page, {
    completeWithoutSession: true,
    nativeResponses: [
      { data: nativeTransaction("totp") },
      { data: nativeTransaction("complete") },
    ],
  });
  await page.goto("/admin/login");
  await submitPassword(page);
  await submitCode(page);
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(`${origin}/admin/login`);
});

test("native cancellation uses bound CSRF and starts a new password flow", async ({
  page,
}) => {
  const requests = await mockApi(page, {
    transaction: nativeTransaction("totp_enrollment", {
      enrollment_secret: setupSecret,
    }),
  });
  await page.goto("/admin/login");
  await openAdminSignIn(page);
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start again" }).click();
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  const cancellation = requests.find((r) => r.method === "DELETE");
  expect(cancellation.path).toBe("/api/v1/admin/password/transaction");
  expect(cancellation.headers["x-csrf-token"]).toBe(nativeCsrf);
  expect(cancellation.headers.origin).toBe(origin);
});

test("expired native transactions discard setup keys and require restarting", async ({
  page,
}) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  await mockApi(page, {
    transaction: nativeTransaction("totp_enrollment", {
      enrollment_secret: setupSecret,
      expires_at: new Date(now + 10000).toISOString(),
    }),
  });
  await page.goto("/admin/login");
  await openAdminSignIn(page);
  await expect(page.getByText(setupSecret, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toBeVisible();
  await page.clock.fastForward(11000);
  await expect(page.getByRole("alert")).toContainText("expired");
  await expect(page.getByText(setupSecret, { exact: true })).not.toBeVisible();
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Admin dashboard" }),
  ).not.toBeVisible();
});

test("authenticator QR is removed before enrollment verification finishes", async ({
  page,
}) => {
  await mockApi(page, {
    transaction: nativeTransaction("totp_enrollment", {
      enrollment_secret: setupSecret,
    }),
    nativeResponses: [
      {
        data: nativeTransaction("password", { enrollment_complete: true }),
        delay: 800,
      },
    ],
  });
  await page.goto("/admin/login");
  await openAdminSignIn(page);
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toBeVisible();
  const uri = await readAuthenticatorQr(page);
  expect(decodeURIComponent(uri.pathname)).toBe(
    "/Popsibilities Admin:Team account",
  );
  await submitCode(page);
  await expect(
    page.getByRole("button", { name: "Verify authenticator code" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toHaveCount(0);
  await expect(page.getByText(setupSecret, { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("Authenticator enrolled.", { exact: false }),
  ).toBeVisible();
});

test("an enrollment without a setup key offers restart without a QR code", async ({
  page,
}) => {
  await mockApi(page, { transaction: nativeTransaction("totp_enrollment") });
  await page.goto("/admin/login");
  await openAdminSignIn(page);
  await expect(
    page.getByText("The private setup key is no longer shown.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Authenticator setup QR code" }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start again" })).toBeEnabled();
});

test("duplicate TOTP submission is disabled while verification is pending", async ({
  page,
}) => {
  const requests = await mockApi(page, {
    transaction: nativeTransaction("totp"),
    nativeResponses: [{ data: nativeTransaction("complete"), delay: 500 }],
  });
  await page.goto("/admin/login");
  await submitCode(page);
  await expect(
    page.getByRole("button", { name: "Verify authenticator code" }),
  ).toBeDisabled();
  await expect(page).toHaveURL(`${origin}/admin`);
  expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
});
