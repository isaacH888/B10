import { expect, test } from "@playwright/test";

async function orderDetails(page) {
  await page.goto("/order");
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .click();
  await page.locator("#cf-name").fill("Synthetic Reviewer");
  await page.locator("#cf-email").fill("reviewer@example.invalid");
  await page.locator("#cf-phone").fill("+1-202-555-0100");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.locator("#cf-line1").fill("100 Example Street");
  await page.locator("#cf-city").fill("Houston");
  await page.locator("#cf-region").fill("TX");
  await page.locator("#cf-postal").fill("77000");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.locator("#cf-event-type").fill("Synthetic celebration");
  await page.locator("#cf-starts-at").fill("2099-01-15T15:00");
  await page.getByRole("button", { name: "Next", exact: true }).click();
}

async function api(
  page,
  {
    quoteFailure = false,
    orderFailures = 0,
    expired = false,
    review = false,
  } = {},
) {
  const quotes = [],
    orders = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (path === "/api/v1/quotes") {
      const body = request.postDataJSON();
      quotes.push(body);
      if (quoteFailure)
        return route.fulfill({
          status: 503,
          json: { error: { code: "service_unavailable" } },
        });
      return route.fulfill({
        json: {
          data: {
            id: `quote_server_${quotes.length}`,
            status: review ? "requires_review" : "priced",
            expires_at: new Date(
              Date.now() + (expired ? -1000 : 900000),
            ).toISOString(),
            ...body,
            pricing: {
              currency: "USD",
              total_cents: 34765,
              deposit_due_cents: 17383,
              line_items: [
                {
                  code: "popsicles",
                  description: "Server calculated price",
                  amount_cents: 34765,
                },
              ],
            },
          },
        },
      });
    }
    if (path === "/api/v1/orders") {
      const body = request.postDataJSON();
      orders.push({ body, key: request.headers()["idempotency-key"] });
      if (orders.length <= orderFailures)
        return route.fulfill({
          status: 503,
          json: { error: { code: "service_unavailable" } },
        });
      return route.fulfill({
        status: 201,
        json: {
          data: {
            ...body,
            id: "order_from_server_123",
            status: "pending_review",
            pricing: {
              currency: "USD",
              total_cents: 34765,
              deposit_due_cents: 17383,
            },
          },
        },
      });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return { quotes, orders };
}

async function quote(page) {
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Place order", exact: true }),
  ).toBeVisible();
}

test("checkout sends real API requests and shows the server's price and identifier", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await quote(page);
  await expect(page.getByText("Total: $347.65", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Order received", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("order_from_server_123", { exact: true }),
  ).toBeVisible();
  expect(calls.quotes).toHaveLength(1);
  expect(calls.orders).toHaveLength(1);
  expect(calls.orders[0].body).toEqual({
    ...calls.quotes[0],
    quote_id: "quote_server_1",
    customer: {
      name: "Synthetic Reviewer",
      email: "reviewer@example.invalid",
      phone: "+1-202-555-0100",
    },
  });
  expect(calls.orders[0].key).toMatch(/^[a-f0-9-]{36}$/);
});

test("an unavailable quote API cannot produce an order confirmation", async ({
  page,
}) => {
  const calls = await api(page, { quoteFailure: true });
  await orderDetails(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "We could not retrieve a quote",
  );
  await expect(
    page.getByRole("button", { name: "Place order", exact: true }),
  ).not.toBeVisible();
  await expect(page).toHaveURL(/\/order$/);
  expect(calls.quotes).toHaveLength(1);
  expect(calls.orders).toHaveLength(0);
});

test("failed order submission stays on the form and retries the same payload and key", async ({
  page,
}) => {
  const calls = await api(page, { orderFailures: 1 });
  await orderDetails(page);
  await quote(page);
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your order could not be placed",
  );
  await expect(page).toHaveURL(/\/order$/);
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(page).toHaveURL(/\/order\/confirm$/);
  expect(calls.orders).toHaveLength(2);
  expect(calls.orders[1]).toEqual(calls.orders[0]);
});

test("Back/edit/Next requires a fresh quote and a new key for changed order details", async ({
  page,
}) => {
  const calls = await api(page, { orderFailures: 1 });
  await orderDetails(page);
  await quote(page);
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your order could not be placed",
  );
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.locator("#cf-quantity").fill("100");
  await quote(page);
  expect(calls.quotes[1].catering_request.quantity).toBe(100);
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(page).toHaveURL(/\/order\/confirm$/);
  expect(calls.orders[1].key).not.toBe(calls.orders[0].key);
  expect(calls.orders[1].body.quote_id).toBe("quote_server_2");
  expect(calls.orders[1].body.catering_request.quantity).toBe(100);
});

for (const [value, message] of [
  ["50.5", "whole number"],
  ["49", "Minimum order"],
  ["100001", "Maximum order"],
]) {
  test(`rejects invalid popsicle quantity ${value}`, async ({ page }) => {
    await api(page);
    await orderDetails(page);
    await page.locator("#cf-quantity").fill(value);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.locator("#cf-quantity")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(message);
  });
}

for (const value of ["0.5", "-1", "1001"]) {
  test(`rejects invalid dry ice count ${value}`, async ({ page }) => {
    await api(page);
    await orderDetails(page);
    await page.locator("#cf-dry-ice").fill(value);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.locator("#cf-dry-ice")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      "whole number of dry ice blocks from 0 to 1,000",
    );
  });
}

for (const [quantity, blocks] of [
  ["50", "0"],
  ["100000", "1000"],
]) {
  test(`accepts whole-number boundary quantities ${quantity} and ${blocks}`, async ({
    page,
  }) => {
    const calls = await api(page);
    await orderDetails(page);
    await page.locator("#cf-quantity").fill(quantity);
    await page.locator("#cf-dry-ice").fill(blocks);
    await quote(page);
    expect(calls.quotes[0].catering_request).toMatchObject({
      quantity: Number(quantity),
      dry_ice_blocks: Number(blocks),
    });
  });
}

test("an expired quote requires recalculation before any order request", async ({
  page,
}) => {
  const calls = await api(page, { expired: true });
  await orderDetails(page);
  await quote(page);
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Try again", exact: true }),
  ).toBeVisible();
  expect(calls.orders).toHaveLength(0);
});

test("manual-review quotes do not claim that an order was submitted", async ({
  page,
}) => {
  const calls = await api(page, { review: true });
  await orderDetails(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Your order has not been submitted",
  );
  await expect(
    page.getByRole("button", { name: "Place order", exact: true }),
  ).not.toBeVisible();
  expect(calls.orders).toHaveLength(0);
});
