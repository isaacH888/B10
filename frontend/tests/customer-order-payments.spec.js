import { expect, test } from "@playwright/test";
import { customerCsrf, customerSession } from "./customer-session.js";
import { savedOrder } from "./order-fixtures.js";

async function account(
  page,
  {
    initial = "awaiting_approval",
    failure = null,
    url = "https://sandbox.square.link/u/customer-deposit",
    environment = "sandbox",
  } = {},
) {
  const order = savedOrder();
  order.pricing.total_cents = 29500;
  order.deposit.amount_due_cents = 14750;
  order.payment = {
    status: initial,
    can_pay: initial === "deposit_due",
    amount_due_cents: 14750,
    currency: "USD",
    environment: "sandbox",
    revision: 3,
  };
  const writes = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/customer/session")
      return route.fulfill({ json: { data: customerSession() } });
    if (path === "/api/v1/customer/orders")
      return route.fulfill({
        json: { data: { items: [order], total: 1, page: 1, page_size: 10 } },
      });
    if (path === `/api/v1/customer/orders/${order.id}/checkout`) {
      expect(request.method()).toBe("POST");
      expect(request.headers()["x-csrf-token"]).toBe(customerCsrf);
      writes.push(request.postDataJSON());
      if (failure)
        return route.fulfill({
          status: failure,
          json: {
            error: {
              code:
                failure === 409 ? "revision_conflict" : "square_unavailable",
            },
          },
        });
      return route.fulfill({ json: { data: { url, environment } } });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  await page.route("https://sandbox.square.link/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>Square secure checkout</h1>",
    }),
  );
  await page.goto("/account?view=orders");
  await expect(page.getByRole("region", { name: "Your orders" })).toBeVisible();
  return {
    order,
    writes,
    approve() {
      order.payment = {
        ...order.payment,
        status: "deposit_due",
        can_pay: true,
      };
    },
    recover() {
      failure = null;
    },
  };
}

test("approval makes Pay deposit available in My Orders and opens Square with the server amount", async ({
  page,
}) => {
  const state = await account(page);
  await expect(
    page.getByText("Payment becomes available after your request is approved."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Pay deposit/ })).toHaveCount(
    0,
  );
  state.approve();
  await page
    .getByRole("button", { name: "Refresh orders", exact: true })
    .click();
  await expect(
    page.getByText("Approved · deposit due", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Square Sandbox — no real payments."),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Pay deposit ($147.50)", exact: true })
    .click();
  await expect(page).toHaveURL(
    "https://sandbox.square.link/u/customer-deposit",
  );
  expect(state.writes).toEqual([{ expected_revision: 3 }]);
});

for (const status of [
  "awaiting_approval",
  "paid",
  "cancelled",
  "expired",
  "unavailable",
]) {
  test(`${status} never offers a deposit payment button`, async ({ page }) => {
    const state = await account(page, { initial: status });
    await expect(page.getByRole("article")).toBeVisible();
    await expect(page.getByRole("button", { name: /Pay deposit/ })).toHaveCount(
      0,
    );
    expect(state.writes).toHaveLength(0);
  });
}

test("a stale approval asks for refreshed order details and never redirects", async ({
  page,
}) => {
  const state = await account(page, { initial: "deposit_due", failure: 409 });
  await page.getByRole("button", { name: /Pay deposit/ }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Refresh your orders before trying again",
  );
  await expect(page).toHaveURL(/\/account\?view=orders$/);
  state.order.payment.can_pay = false;
  state.order.payment.status = "cancelled";
  await page
    .getByRole("alert")
    .getByRole("button", { name: "Refresh orders" })
    .click();
  await expect(page.getByRole("button", { name: /Pay deposit/ })).toHaveCount(
    0,
  );
});

test("a Square outage allows a deliberate retry without inventing payment success", async ({
  page,
}) => {
  const state = await account(page, { initial: "deposit_due", failure: 503 });
  await page.getByRole("button", { name: /Pay deposit/ }).click();
  await expect(page.getByRole("alert")).toContainText(
    "payment has not been confirmed",
  );
  state.recover();
  await page.getByRole("button", { name: /Pay deposit/ }).click();
  await expect(page).toHaveURL(
    "https://sandbox.square.link/u/customer-deposit",
  );
  expect(state.writes).toEqual([
    { expected_revision: 3 },
    { expected_revision: 3 },
  ]);
});

for (const [url, environment] of [
  ["https://other.example.invalid/checkout", "sandbox"],
  ["https://square.link/u/production-checkout", "production"],
]) {
  test(`an unexpected checkout destination is rejected: ${url}`, async ({
    page,
  }) => {
    await account(page, { initial: "deposit_due", url, environment });
    await page.getByRole("button", { name: /Pay deposit/ }).click();
    await expect(page.getByRole("alert")).toContainText(
      "couldn’t open Square Checkout",
    );
    await expect(page).toHaveURL(/\/account\?view=orders$/);
  });
}

test("the approved deposit action fits a narrow phone screen", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 812 });
  await account(page, { initial: "deposit_due" });
  await expect(page.getByRole("button", { name: /Pay deposit/ })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
