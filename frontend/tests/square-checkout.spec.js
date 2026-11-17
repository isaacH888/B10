import { expect, test } from "@playwright/test";

const id = "a".repeat(32);
const prefix = "/api/v1/admin/automation";
const booking = {
  id,
  reference: "POP-SQUARE",
  status: "awaiting_deposit",
  revision: 2,
  payment_status: "unpaid",
  calendar_status: "pending",
  schedule_revision: 0,
  start: "2027-06-12T19:00:00+00:00",
  end: "2027-06-12T21:00:00+00:00",
  timezone: "America/Chicago",
  venue: "Houston",
  service_type: "delivery",
  quantity: 50,
  customer_email: "customer@example.invalid",
  contract_url: "https://example.invalid/contract",
  total_minor: 10001,
  deposit_minor: 5001,
  paid_minor: 0,
  remaining_minor: 10001,
  currency: "USD",
};

async function owner(page, overrides = {}, enabled = true) {
  const current = { ...booking, ...overrides },
    requests = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (path === "/api/v1/admin/session")
      return route.fulfill({
        json: {
          data: {
            administrator: {
              id: "owner",
              name: "Owner",
              email: "owner@example.invalid",
              role: "owner",
              permissions: ["bookings:read", "payments:manage"],
            },
            csrf_token: "owner-square-csrf",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(Date.now() + 900000).toISOString(),
          },
        },
      });
    if (path.endsWith("/checkout")) {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe("owner-square-csrf");
      const body = request.postDataJSON();
      requests.push(body);
      return route.fulfill({
        json: {
          data: {
            id,
            ...body,
            amount_minor: body.purpose === "deposit" ? 5001 : 5000,
            currency: "USD",
            status: "open",
            url: "http://127.0.0.1:5190/payment/pay?checkout=" + id,
            expires_at: 1900000000,
          },
        },
      });
    }
    if (path === prefix + "/square")
      return route.fulfill({
        json: { data: { enabled, environment: "sandbox" } },
      });
    if (path === prefix + "/bookings")
      return route.fulfill({ json: { data: [current] } });
    if (path === prefix + "/bookings/" + id)
      return route.fulfill({
        json: { data: { booking: current, payments: [], jobs: [] } },
      });
    if (path === prefix + "/google")
      return route.fulfill({ json: { data: { status: "disconnected" } } });
    if (path === prefix + "/orders")
      return route.fulfill({ json: { data: [] } });
    return route.fulfill({
      status: 404,
      json: { error: { code: "not_found" } },
    });
  });
  await page.goto("/admin/bookings/" + id);
  return requests;
}

test("owner creates and emails server-priced deposit with CSRF", async ({
  page,
}) => {
  const requests = await owner(page);
  const section = page.getByRole("region", { name: "Square Checkout" });
  await expect(
    section.getByText("Square Sandbox — no real payments."),
  ).toBeVisible();
  await section
    .getByRole("button", { name: "Create and email deposit link ($50.01)" })
    .click();
  await expect(section.getByRole("status")).toContainText(
    "Payment email queued",
  );
  await expect(section.getByRole("link")).toHaveAttribute(
    "href",
    "http://127.0.0.1:5190/payment/pay?checkout=" + id,
  );
  expect(requests).toEqual([{ purpose: "deposit", expected_revision: 2 }]);
});

test("confirmed booking offers remaining balance", async ({ page }) => {
  const requests = await owner(page, {
    status: "confirmed",
    paid_minor: 5001,
    remaining_minor: 5000,
  });
  await page
    .getByRole("button", { name: "Create and email balance link ($50.00)" })
    .click();
  await expect(page.getByRole("status")).toContainText("Payment email queued");
  expect(requests[0]).toEqual({ purpose: "balance", expected_revision: 2 });
});

test("conditional approval never offers Checkout", async ({ page }) => {
  await owner(page, { status: "conditionally_confirmed" });
  const section = page.getByRole("region", { name: "Square Checkout" });
  await expect(
    section.getByText("Confirm availability before requesting payment."),
  ).toBeVisible();
  await expect(section.getByRole("button")).toHaveCount(0);
});

test("disabled payments explain setup without blocking booking management", async ({
  page,
}) => {
  await owner(page, {}, false);
  await expect(
    page.getByText("Square payments are awaiting setup.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Verify an external payment" }),
  ).toBeVisible();
});

async function paymentStatus(page, status = "pending") {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/payments/square/" + id)
      return route.fulfill({
        json: {
          data: {
            status,
            can_pay: status === "pending",
            purpose: "deposit",
            amount_minor: 5001,
            currency: "USD",
            environment: "sandbox",
          },
        },
      });
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
}

test("return URL cannot declare payment success", async ({ page }) => {
  await paymentStatus(page);
  await page.goto(
    `/payment/return?checkout=${id}&paid=true&payment_status=paid`,
  );
  await expect(
    page.getByText("We’re waiting for Square", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Deposit paid" }),
  ).toHaveCount(0);
});

test("verified payment return is public and displays amount", async ({
  page,
}) => {
  await paymentStatus(page, "paid");
  await page.goto(`/payment/return?checkout=${id}`);
  await expect(
    page.getByRole("heading", { name: "Deposit paid" }),
  ).toBeVisible();
  await expect(
    page.getByText("Your deposit payment of $50.01 has been verified.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Test payment — no real money was charged."),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("square-return-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
  await page.screenshot({
    path: test.info().outputPath("square-return-mobile.png"),
    fullPage: true,
  });
});

test("cancelled Checkout and expired links never display success", async ({
  page,
}) => {
  await paymentStatus(page);
  await page.goto(`/payment/return?checkout=${id}&cancelled=1`);
  await expect(
    page.getByRole("heading", { name: "Checkout cancelled" }),
  ).toBeVisible();
  await expect(
    page.getByText("Your payment has not been verified.", { exact: false }),
  ).toBeVisible();
  await paymentStatus(page, "expired");
  await page.goto(`/payment/return?checkout=${id}`);
  await expect(
    page.getByText("This payment link has expired.", { exact: false }),
  ).toBeVisible();
});

test("invalid return link has helpful error and no payment request", async ({
  page,
}) => {
  const requests = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/payments/"))
      requests.push(request.url());
  });
  await paymentStatus(page);
  await page.goto("/payment/return?checkout=invalid");
  await expect(page.getByRole("alert")).toContainText(
    "This payment link is invalid",
  );
  expect(requests).toEqual([]);
});

test("customer payment page checks the amount before handing off to Square", async ({
  page,
}) => {
  await paymentStatus(page);
  let payload;
  await page.route(`**/api/v1/payments/square/${id}/start`, async (route) => {
    payload = route.request().postDataJSON();
    await route.fulfill({
      json: { data: { url: "https://sandbox.square.link/u/sample-checkout" } },
    });
  });
  await page.route("https://sandbox.square.link/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>Square Sandbox redirect target</h1>",
    }),
  );
  await page.goto(`/payment/pay?checkout=${id}&amount=1`);
  await expect(page.getByText("Deposit:", { exact: false })).toContainText(
    "$50.01",
  );
  await expect(
    page.getByText("Square Sandbox — no real payments."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pay securely with Square" }).click();
  await expect(page).toHaveURL("https://sandbox.square.link/u/sample-checkout");
  expect(payload).toEqual({});
});

test("Square handoff rejects an unexpected external destination", async ({
  page,
}) => {
  await paymentStatus(page);
  await page.route(`**/api/v1/payments/square/${id}/start`, (route) =>
    route.fulfill({
      json: { data: { url: "https://attacker.invalid/payment" } },
    }),
  );
  await page.goto(`/payment/pay?checkout=${id}`);
  await page.getByRole("button", { name: "Pay securely with Square" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "We could not open Square Checkout",
  );
  await expect(page).toHaveURL(new RegExp(`/payment/pay\\?checkout=${id}$`));
});

test("paid and expired payment pages do not offer another charge", async ({
  page,
}) => {
  await paymentStatus(page, "paid");
  await page.goto(`/payment/pay?checkout=${id}`);
  await expect(
    page.getByRole("link", { name: "View payment confirmation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Pay securely with Square" }),
  ).toHaveCount(0);
  await paymentStatus(page, "expired");
  await page.goto(`/payment/pay?checkout=${id}`);
  await expect(
    page.getByText("This payment link is no longer available.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Pay securely with Square" }),
  ).toHaveCount(0);
});

test("customer Square payment page fits a mobile screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await paymentStatus(page);
  await page.goto(`/payment/pay?checkout=${id}`);
  await expect(
    page.getByRole("button", { name: "Pay securely with Square" }),
  ).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
  await page.screenshot({
    path: test.info().outputPath("square-payment-mobile.png"),
    fullPage: true,
  });
});
