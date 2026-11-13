import { expect, test } from "@playwright/test";
import { linkedBooking, savedOrder } from "./order-fixtures.js";

async function workspace(page, options = {}) {
  const requests = [];
  const order = savedOrder();
  if (options.flavorMix)
    order.catering_request.flavor_allocations = options.flavorMix;
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({
      path: url.pathname,
      query: url.searchParams,
      method: request.method(),
    });
    if (url.pathname === "/api/v1/admin/session") {
      return route.fulfill({
        json: {
          data: {
            administrator: {
              id: "synthetic-owner",
              role: "owner",
              name: "Reviewer",
              email: "owner@example.invalid",
              permissions: ["bookings:read"],
            },
            csrf_token: "synthetic-csrf",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(Date.now() + 900000).toISOString(),
          },
        },
      });
    }
    if (url.pathname.startsWith("/api/v1/admin/orders")) {
      if (options.error)
        return route.fulfill({
          status: options.error,
          json: {
            error: {
              code: options.error === 404 ? "not_found" : "service_unavailable",
            },
          },
        });
      const record = {
        order,
        booking: options.booking ? linkedBooking(order) : null,
      };
      if (url.pathname === "/api/v1/admin/orders") {
        const empty = options.empty || url.searchParams.get("q") === "Nobody";
        return route.fulfill({
          json: {
            data: {
              items: empty ? [] : [record],
              total: empty ? 0 : options.total || 1,
              page: Number(url.searchParams.get("page") || 1),
              page_size: 25,
              storage: "database",
            },
          },
        });
      }
      return route.fulfill({ json: { data: record } });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return requests;
}

test("order list and detail render saved API data without fictional samples", async ({
  page,
}) => {
  const requests = await workspace(page);
  await page.goto("/admin/orders");
  await expect(
    page.getByRole("cell", { name: "Example Customer", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Sofia Ramirez")).toHaveCount(0);
  await expect(page.getByText("$1,860")).toHaveCount(0);
  await page.getByRole("link", { name: "View details" }).click();
  await expect(
    page.getByRole("heading", { name: /order_example_001.*EXAMPLE CUSTOMER/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "Review customer order intake",
      exact: true,
    }),
  ).toHaveAttribute("href", "/admin/automation");
  await expect(
    page.getByRole("button", { name: "Approve availability", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Record external payment", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Export summary/ }),
  ).toBeDisabled();
  expect(requests.every((r) => r.method === "GET")).toBe(true);
});

test("owner order details show the saved requested flavor quantities", async ({
  page,
}) => {
  await workspace(page, {
    flavorMix: [
      { flavor: "Mango Lime", quantity: 30 },
      { flavor: "Mango Dragonfruit", quantity: 20 },
    ],
  });
  await page.goto("/admin/orders/order_example_001");
  await expect(
    page
      .locator(".od-section__two-col")
      .filter({ hasText: "FLAVOR REQUESTS" })
      .getByText("Mango Lime: 30 · Mango Dragonfruit: 20", { exact: true }),
  ).toBeVisible();
});

test("linked order displays current booking dates, payment totals and management link", async ({
  page,
}) => {
  await workspace(page, { booking: true });
  await page.goto("/admin/orders/order_example_001");
  await expect(page.getByText("Jan 16, 2099", { exact: true })).toBeVisible();
  await expect(
    page.getByText("200 Updated Example Street, Houston, TX", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Part paid", { exact: true })).toBeVisible();
  await expect(page.getByText("Synced", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Manage linked booking", exact: true }),
  ).toHaveAttribute("href", "/admin/bookings/0123456789abcdef0123456789abcdef");
  await expect(page.getByText("No verified payments yet.")).toHaveCount(0);
});

test("search, status, payment, service and pagination request server filters", async ({
  page,
}) => {
  const requests = await workspace(page, { total: 26 });
  await page.goto("/admin/orders");
  await expect(
    page.getByRole("cell", { name: "Example Customer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible();
  await page.getByLabel("Search orders").fill("Nobody");
  await expect(
    page.getByText("No customer orders match these filters."),
  ).toBeVisible();
  await page.getByLabel("Filter by order status").selectOption("confirmed");
  await page.getByLabel("Filter by payment status").selectOption("partial");
  await page.getByLabel("Filter by service type").selectOption("full_service");
  await expect
    .poll(() =>
      requests.some(
        (r) =>
          r.query.get("q") === "Nobody" &&
          r.query.get("page") === "1" &&
          r.query.get("status") === "confirmed" &&
          r.query.get("payment_status") === "partial" &&
          r.query.get("service_type") === "full_service",
      ),
    )
    .toBe(true);
  await page.getByLabel("Event date from").fill("2026-11-01");
  await page.getByLabel("Event date through").fill("2026-11-30");
  await expect
    .poll(() =>
      requests.some(
        (r) => r.query.has("event_from") && r.query.has("event_to"),
      ),
    )
    .toBe(true);
});

for (const path of ["/admin/orders", "/admin/orders/order_example_001"]) {
  test(`API failure never substitutes sample data at ${path}`, async ({
    page,
  }) => {
    await workspace(page, { error: 503 });
    await page.goto(path);
    await expect(
      page.getByRole("alert").filter({ hasText: "Could not load" }),
    ).toBeVisible();
    await expect(page.getByText("Sofia Ramirez")).toHaveCount(0);
    await expect(
      page.getByText("Example Customer", { exact: true }),
    ).toHaveCount(0);
  });
}

test("a missing saved order has a real not-found state", async ({ page }) => {
  await workspace(page, { error: 404 });
  await page.goto("/admin/orders/order_missing");
  await expect(
    page.getByText("Order not found.", { exact: true }),
  ).toBeVisible();
});
