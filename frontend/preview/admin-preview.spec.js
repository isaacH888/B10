import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("sample admin screens work without login, cookies, or real API responses", async ({
  page,
  context,
}) => {
  const apiResponses = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.startsWith("/api/v1/")) {
      apiResponses.push(response);
    }
  });
  await page.goto("/admin/dashboard");
  await expect(
    page.getByRole("complementary", { name: "Sample preview" }),
  ).toContainText("Sample data");
  await expect(
    page.getByRole("region", { name: "New catering requests", exact: true }),
  ).toContainText("7");
  const nav = page.getByRole("navigation", { name: "Admin pages" });
  await nav.getByRole("link", { name: "Orders", exact: true }).click();
  await page
    .getByRole("searchbox", { name: "Search orders" })
    .fill("Elena Cruz");
  const firstOrder = page.getByRole("row", {
    name: /Sample Elena Cruz preview_order_001/,
  });
  await expect(firstOrder).toBeVisible();
  await firstOrder.getByRole("link", { name: "View details ↗" }).click();
  await expect(
    page.getByRole("heading", {
      name: /SAMPLE ELENA CRUZ.*preview_order_001/i,
    }),
  ).toBeVisible();
  await nav.getByRole("link", { name: "Calendar", exact: true }).click();
  const { data: record } = await (
    await page.request.get("/api/v1/admin/orders/preview_order_003")
  ).json();
  const currentMonth = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    month: "2-digit",
  }).format(new Date());
  if (record.order.event.starts_at.slice(5, 7) !== currentMonth)
    await page.getByRole("button", { name: "Next month", exact: true }).click();
  await page
    .getByRole("button", {
      name: "Sample Avery Morgan, Full Service, 250 paletas, confirmed",
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("300 Example Lane");
  await page.getByRole("button", { name: "Close event details" }).click();
  await nav.getByRole("link", { name: "Inventory", exact: true }).click();
  await expect(
    page
      .getByRole("button", { name: "View details for Mango Lime", exact: true })
      .first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "View details for Mango Lime", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Sample freezer restock.",
  );
  await expect(context.cookies()).resolves.toEqual([]);
  expect(errors).toEqual([]);
  expect(apiResponses.length).toBeGreaterThan(5);
  for (const response of apiResponses) {
    expect(response.headers()["x-admin-preview"]).toBe("sample-data");
    expect(response.headers()["set-cookie"]).toBeUndefined();
  }
});

test("populated demo stays consistent across orders, dashboard, bookings and inventory", async ({
  request,
}) => {
  const read = async (path) =>
    (await (await request.get(`/api/v1${path}`)).json()).data;
  const [orders, dashboard, inventory, bookings, intake] = await Promise.all([
    read("/admin/orders?page_size=100"),
    read("/admin/dashboard"),
    read("/admin/inventory"),
    read("/admin/automation/bookings"),
    read("/admin/automation/orders"),
  ]);
  expect(orders.total).toBe(48);
  expect(bookings).toHaveLength(41);
  expect(inventory.items).toHaveLength(18);
  expect(intake).toHaveLength(dashboard.requests);
  for (const name of ["Elena Cruz", "Morgan Davis", "Mia Anderson"]) {
    const approved = orders.items.find(
      ({ order }) => order.customer.name === `Sample ${name}`,
    );
    expect(approved.booking.status).toBe("awaiting_deposit");
    expect(approved.booking.paid_minor).toBe(0);
    expect(approved.booking.customer_message).toContain(
      "availability is approved",
    );
    expect(intake.some((order) => order.id === approved.order.id)).toBe(false);
    const approvedDetail = await read(
      `/admin/automation/bookings/${approved.booking.id}`,
    );
    expect(approvedDetail.jobs[0].kind).toBe("deposit_request");
    expect(approvedDetail.jobs[0].delivery.status).toBe("simulated");
  }
  expect(dashboard.recent_orders).toHaveLength(5);
  const secondPage = await read("/admin/orders?page=2");
  expect(secondPage.items).toHaveLength(23);
  const pending = await read("/admin/orders?status=pending");
  expect(pending.total).toBe(dashboard.requests);
  const balance = bookings
    .filter((booking) => booking.status === "confirmed")
    .reduce((sum, booking) => sum + booking.remaining_minor, 0);
  expect(dashboard.balances[0].remaining_cents).toBe(balance);
  expect(dashboard.low_stock).toBe(
    inventory.items.filter((item) => item.available < item.minimum).length,
  );
  expect(dashboard.reserved_units).toBe(
    inventory.items.reduce((sum, item) => sum + item.reserved, 0),
  );
  for (const event of dashboard.upcoming) {
    expect(event.status).toBe("confirmed");
    expect(Date.parse(event.start)).toBeLessThan(
      Date.parse(dashboard.window_end),
    );
  }
  const booking = bookings.find(
    (item) => item.status === "confirmed" && item.paid_minor > 0,
  );
  const detail = await read(`/admin/automation/bookings/${booking.id}`);
  expect(
    detail.payments.reduce((sum, payment) => sum + payment.amount_minor, 0),
  ).toBe(booking.paid_minor);
  expect(detail.jobs).not.toHaveLength(0);
  const allocation = await read(
    `/admin/inventory/bookings/${booking.id}/allocations`,
  );
  expect(allocation.items.reduce((sum, item) => sum + item.quantity, 0)).toBe(
    booking.quantity,
  );
  const history = await read(
    `/admin/inventory/${inventory.items[0].id}/history`,
  );
  expect(history.history).toHaveLength(2);
  const notifications = await read("/admin/automation/requests");
  expect(notifications.email_mode).toBe("simulated");
});

test("preview blocks mutations and never falls through to real services", async ({
  request,
}) => {
  const before = await request.get("/api/v1/admin/inventory");
  const original = await before.json();
  for (const path of [
    "/admin/inventory",
    "/admin/login",
    "/admin/automation/google/connect",
    "/admin/automation/requests",
    "/admin/automation/orders/preview_order_001/booking",
  ]) {
    const response = await request.post(`/api/v1${path}`, { data: {} });
    expect(response.status()).toBe(403);
    expect((await response.json()).error.code).toBe("preview_read_only");
    expect(response.headers()["x-admin-preview"]).toBe("sample-data");
    expect(response.headers()["set-cookie"]).toBeUndefined();
  }
  const unknown = await request.get("/api/v1/admin/unknown-live-endpoint");
  expect(unknown.status()).toBe(404);
  expect(unknown.headers()["x-admin-preview"]).toBe("sample-data");
  const after = await request.get("/api/v1/admin/inventory");
  expect(await after.json()).toEqual(original);
});

test("preview exports only clearly marked sample records", async ({ page }) => {
  await page.goto("/admin/orders/preview_order_001");
  const response = page.waitForResponse((response) =>
    response.url().includes("/preview_order_001/export"),
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export summary" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("order-summary.csv");
  const exported = await response;
  expect(exported.headers()["x-admin-preview"]).toBe("sample-data");
  expect(await readFile(await file.path(), "utf8")).toContain(
    '"PREVIEW","preview_order_001","Sample Elena Cruz"',
  );
});

for (const width of [390, 1440]) {
  test(`sample dashboard fits a ${width}px viewport`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/admin/dashboard");
    await expect(
      page.getByRole("region", { name: "New catering requests", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`admin-preview-${width}.png`),
      fullPage: true,
    });
  });
}
