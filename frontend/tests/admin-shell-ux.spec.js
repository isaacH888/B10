import { expect, test } from "@playwright/test";
import { dashboardData, savedOrder } from "./order-fixtures.js";

const bookingId = "a".repeat(32);
const booking = {
  id: bookingId,
  reference: "POP-SHELL-TEST",
  revision: 1,
  status: "awaiting_deposit",
  payment_status: "unpaid",
  calendar_status: "pending",
  start: "2027-06-12T19:00:00Z",
  end: "2027-06-12T21:00:00Z",
  timezone: "America/Chicago",
  venue: "Sample venue",
  service_type: "delivery",
  quantity: 50,
  total_minor: 20000,
  deposit_minor: 10000,
  paid_minor: 0,
  remaining_minor: 20000,
  currency: "USD",
};

async function mock(page, options = {}) {
  const calls = [];
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    calls.push({ path, method: request.method() });
    const ok = (data) => route.fulfill({ json: { data } });
    if (path === "/api/v1/admin/session" && !options.signedOut) {
      return ok({
        administrator: {
          id: "shell-test-owner",
          name: "Test owner",
          email: "owner@example.invalid",
          role: options.role || "owner",
          permissions: ["bookings:read", "customers:export"],
        },
        csrf_token: "shell-test-csrf",
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        idle_expires_at: new Date(Date.now() + 900000).toISOString(),
      });
    }
    if (options.signedOut || path === "/api/v1/customer/session") {
      return route.fulfill({
        status: 401,
        json: { error: { code: "unauthenticated" } },
      });
    }
    if (path === "/api/v1/admin/dashboard") return ok(dashboardData());
    if (path === "/api/v1/admin/orders")
      return ok({
        items: [{ order: savedOrder(), booking: null }],
        total: 1,
        page: 1,
        page_size: 25,
        storage: "database",
      });
    if (path === "/api/v1/admin/inventory") return ok({ items: [] });
    if (path.endsWith("/allocations"))
      return ok({ booking_id: bookingId, revision: 1, items: [] });
    if (path === "/api/v1/admin/automation/bookings") return ok([booking]);
    if (path === `/api/v1/admin/automation/bookings/${bookingId}`)
      return ok({ booking, payments: [], jobs: [] });
    if (path === "/api/v1/admin/automation/orders") return ok([]);
    if (path === "/api/v1/admin/automation/google")
      return ok({ status: "disconnected", configured: false });
    return route.fulfill({
      status: 404,
      json: { error: { code: "not_found" } },
    });
  });
  return calls;
}

test("booking list and detail retain the designed admin navigation and hide authentication debug content", async ({
  page,
}, info) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const calls = await mock(page);
  await page.goto("/admin/automation");
  await expect(page.locator(".adm-shell")).toBeVisible();
  await expect(page.locator(".adm-page-header__title")).toHaveText("Bookings");
  await expect(
    page
      .getByRole("navigation", { name: "Admin pages" })
      .getByRole("link", { name: "Bookings", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByText("Popssibilities authentication test", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Session Details" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Catering automation" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "POP-SHELL-TEST", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/bookings/${bookingId}$`));
  await expect(page.locator(".adm-page-header__title")).toHaveText(
    "Bookings / Booking details",
  );
  await expect(
    page
      .getByRole("navigation", { name: "Admin pages" })
      .getByRole("link", { name: "Bookings", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByLabel("Unique provider transaction reference"),
  ).toBeVisible();
  expect(calls.every((call) => call.method === "GET")).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: info.outputPath("booking-workspace-desktop.png"),
    fullPage: true,
  });
});

test("mobile navigation starts compact, supports keyboard dismissal, and closes after navigation", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto("/admin/automation");
  const nav = page.getByRole("navigation", { name: "Admin pages" });
  const toggle = page.getByRole("button", { name: "Open admin navigation" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(nav).toBeHidden();
  expect(
    (
      await page
        .getByRole("complementary", { name: "Admin navigation" })
        .boundingBox()
    ).height,
  ).toBeLessThan(110);
  await toggle.click();
  await expect(nav).toBeVisible();
  await nav.getByRole("link", { name: "Calendar", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(nav).toBeHidden();
  await expect(toggle).toBeFocused();
  await toggle.click();
  await nav.getByRole("link", { name: "Bookings", exact: true }).click();
  await expect(nav).toBeHidden();
  expect(
    await page
      .getByRole("region", { name: "Catering bookings" })
      .evaluate((element) => element.scrollWidth > element.clientWidth),
  ).toBe(true);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("booking-workspace-mobile.png"),
    fullPage: true,
  });
});

test("order rows are visible sooner at laptop dimensions", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await mock(page);
  await page.goto("/admin/orders");
  const row = page.getByRole("row", { name: /^order_example_001 / });
  await expect(row).toBeVisible();
  const bounds = await row.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThan(800);
  await page.screenshot({
    path: info.outputPath("orders-header-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("orders-header-mobile.png"),
    fullPage: true,
  });
});

test("signed-out booking links still require authentication", async ({
  page,
}) => {
  await mock(page, { signedOut: true });
  await page.goto(`/admin/bookings/${bookingId}`);
  await expect(page).toHaveURL(/\/admin\/login$/);
  await expect(page.locator(".adm-shell")).toHaveCount(0);
});

test("Staff cannot load owner booking records or mutation controls", async ({
  page,
}) => {
  const calls = await mock(page, { role: "staff" });
  await page.goto(`/admin/bookings/${bookingId}`);
  await expect(
    page.getByText("Only the owner can operate booking automation.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Record verified payment" }),
  ).toHaveCount(0);
  expect(
    calls.some((call) => call.path.startsWith("/api/v1/admin/automation/")),
  ).toBe(false);
});
