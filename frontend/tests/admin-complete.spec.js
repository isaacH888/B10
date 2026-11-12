import { expect, test } from "@playwright/test";
import { calendarEvent, dashboardData, savedOrder } from "./order-fixtures.js";

async function connect(page, options = {}) {
  const calls = [];
  let items = [];
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const body = request.postData() ? request.postDataJSON() : null;
    calls.push({
      path,
      method: request.method(),
      body,
      headers: request.headers(),
    });
    const ok = (data, status = 200) =>
      route.fulfill({ status, json: { data } });
    if (path === "/api/v1/admin/session")
      return ok({
        administrator: {
          id: "test-owner",
          name: "API Tester",
          email: "owner@example.invalid",
          role: "owner",
          permissions: ["bookings:read", "customers:export"],
        },
        csrf_token: "test-owner-csrf",
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        idle_expires_at: new Date(Date.now() + 900000).toISOString(),
      });
    if (
      options.failure &&
      [
        "/api/v1/admin/dashboard",
        "/api/v1/admin/calendar",
        "/api/v1/admin/inventory",
      ].includes(path)
    )
      return route.fulfill({
        status: 503,
        json: { error: { code: "service_unavailable" } },
      });
    if (path.endsWith("/export"))
      return route.fulfill({
        contentType: "text/csv",
        headers: {
          "Content-Disposition": 'attachment; filename="order-summary.csv"',
        },
        body: "order_id,total_cents\r\norder_example_001,20000\r\n",
      });
    if (path === "/api/v1/admin/dashboard") return ok(dashboardData());
    if (path === "/api/v1/admin/orders")
      return ok({
        items: [{ order: savedOrder(), booking: null }],
        total: 1,
        page: 1,
        page_size: 25,
        storage: "database",
      });
    if (path === "/api/v1/admin/orders/order_example_001")
      return ok({ order: savedOrder(), booking: null });
    if (path === "/api/v1/admin/automation/google")
      return ok({ status: "disconnected", configured: false });
    if (path === "/api/v1/admin/calendar")
      return ok({
        events: [
          calendarEvent(),
          calendarEvent({
            id: "0123456789abcdef0123456789abcdef",
            reference: "POP-MANUAL",
            order_id: null,
            booking_id: "0123456789abcdef0123456789abcdef",
            customer: "Manual saved booking",
            status: "confirmed",
            calendar_status: "pending",
          }),
        ],
        timezone: "America/Chicago",
        stats: { confirmed: 1, pending: 1, confirmed_quantity: 50 },
      });
    if (path === "/api/v1/admin/inventory") {
      if (request.method() === "POST") {
        const item = {
          ...body,
          id: "0123456789abcdef0123456789abcdef",
          version: 1,
          reserved: 0,
          available: body.onHand,
          active: true,
        };
        items.push(item);
        return ok({ item }, 201);
      }
      return ok({ items });
    }
    if (path.endsWith("/history"))
      return ok({ history: [], page: 1, page_size: 25, total: 0 });
    if (path.endsWith("/adjust")) {
      const item = items[0];
      item.onHand += body.quantity;
      item.available = item.onHand;
      item.version += 1;
      return ok({ item });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return calls;
}

test("dashboard cards and recent links use the saved API records", async ({
  page,
}) => {
  await connect(page);
  await page.goto("/admin/dashboard");
  await expect(
    page.getByRole("region", { name: "New catering requests", exact: true }),
  ).toContainText("1");
  await expect(page.getByText("Sofia Ramirez")).toHaveCount(0);
  await page
    .getByRole("link", { name: "order_example_001", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /order_example_001.*EXAMPLE CUSTOMER/ }),
  ).toBeVisible();
});

test("Calendar keeps two events on one date and uses real connection and detail links", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-11-11T12:00:00-06:00") });
  await connect(page);
  await page.goto("/admin/calendar");
  const first = page.getByRole("button", {
    name: "Example Customer, Delivery, 50 paletas, pending",
  });
  const second = page.getByRole("button", {
    name: "Manual saved booking, Delivery, 50 paletas, confirmed",
  });
  await expect(first).toBeVisible();
  await expect(second).toBeVisible();
  await expect(page.getByRole("gridcell").filter({ has: first })).toContainText(
    "Manual saved booking",
  );
  await expect(page.locator(".cal-gcal-banner__title")).toHaveText(
    "GOOGLE CALENDAR · DISCONNECTED",
  );
  await first.click();
  await expect(page.getByRole("dialog")).toContainText("100 Example Street");
  await page.getByRole("button", { name: "Open order details" }).click();
  await expect(page).toHaveURL(/\/admin\/orders\/order_example_001$/);
});

test("inventory create and adjustment use session CSRF, versions and replay keys", async ({
  page,
}) => {
  const calls = await connect(page);
  await page.goto("/admin/inventory");
  await page.getByRole("button", { name: "Add item +", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Flavor / product name", exact: true })
    .fill("Working Mango");
  await page
    .getByRole("spinbutton", { name: "Initial on-hand quantity", exact: true })
    .fill("60");
  await page
    .getByRole("spinbutton", { name: "Low-stock threshold", exact: true })
    .fill("20");
  await page.getByRole("button", { name: "Add item", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "View details for Working Mango" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "View details for Working Mango" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Update stock for Working Mango" })
    .click();
  await page
    .getByRole("spinbutton", { name: "Quantity to add", exact: true })
    .fill("10");
  await page
    .getByRole("button", { name: "Save adjustment", exact: true })
    .click();
  await expect(
    page.getByText("Working Mango stock updated.", { exact: true }),
  ).toBeVisible();
  const writes = calls.filter((call) => call.method === "POST");
  expect(writes).toHaveLength(2);
  expect(
    writes.every(
      (call) =>
        call.headers["x-csrf-token"] === "test-owner-csrf" &&
        call.headers["idempotency-key"]?.length >= 16,
    ),
  ).toBe(true);
  expect(writes[1].body.expected_version).toBe(1);
  expect(writes[1].body.quantity).toBe(10);
});

test("order summaries download an actual CSV response", async ({ page }) => {
  await connect(page);
  await page.goto("/admin/orders/order_example_001");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export summary" }).click();
  expect((await download).suggestedFilename()).toBe("order-summary.csv");
});

for (const path of ["dashboard", "calendar", "inventory"]) {
  test(`${path} API failure is visible and never shows sample data`, async ({
    page,
  }) => {
    await connect(page, { failure: true });
    await page.goto(`/admin/${path}`);
    await expect(page.getByRole("alert")).toContainText("Could not load");
    await expect(page.getByText("Sofia Ramirez")).toHaveCount(0);
    await expect(page.getByText("owner@popssibilities.com")).toHaveCount(0);
  });
}
