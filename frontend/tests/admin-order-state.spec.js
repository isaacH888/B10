import { expect, test } from "@playwright/test";
import { linkedBooking, savedOrder } from "./order-fixtures.js";

async function ordersWorkspace(page, state = { total: 76 }) {
  const reads = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const ok = (data) => route.fulfill({ json: { data } });
    if (url.pathname === "/api/v1/admin/session") {
      const now = await page.evaluate(() => Date.now());
      return ok({
        administrator: {
          id: "owner-fixture",
          name: "Owner",
          email: "owner@example.invalid",
          role: "owner",
          permissions: ["bookings:read", "customers:export"],
        },
        csrf_token: "fixture-csrf",
        expires_at: new Date(now + 3600000).toISOString(),
        idle_expires_at: new Date(now + 900000).toISOString(),
      });
    }
    const order = savedOrder();
    const record = { order, booking: linkedBooking(order) };
    if (url.pathname === "/api/v1/admin/orders") {
      reads.push(url.searchParams);
      if (url.searchParams.get("q") === "Hold" && state.hold) await state.hold;
      return ok({
        items: [record],
        total: state.total,
        page: Number(url.searchParams.get("page") || 1),
        page_size: 25,
        storage: "database",
      });
    }
    if (url.pathname === `/api/v1/admin/orders/${order.id}`) return ok(record);
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return reads;
}

test("order filters and page survive reload, details, back link, and browser Back", async ({
  page,
}) => {
  const reads = await ordersWorkspace(page);
  const path =
    "/admin/orders?q=Example&status=confirmed&payment_status=partial&service_type=delivery&from=2026-11-01&through=2026-11-30&page=2";
  await page.goto(path);
  for (const [label, value] of [
    ["Search orders", "Example"],
    ["Filter by order status", "confirmed"],
    ["Filter by payment status", "partial"],
    ["Filter by service type", "delivery"],
    ["Event date from", "2026-11-01"],
    ["Event date through", "2026-11-30"],
  ]) {
    await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);
  }
  await expect(page.getByText("Page 2 of 4", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Search orders")).toHaveValue("Example");
  await expect(page.getByText("Page 2 of 4", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "View details ↗", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "← All orders", exact: true }),
  ).toHaveAttribute("href", path);
  await page.getByRole("link", { name: "← All orders", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("q=Example.*page=2$"));
  await expect(page.getByText("Page 2 of 4", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "View details ↗", exact: true }).click();
  await page.goBack();
  await expect(page.getByLabel("Filter by payment status")).toHaveValue(
    "partial",
  );
  await expect(page.getByText("Page 2 of 4", { exact: true })).toBeVisible();
  expect(
    reads.every(
      (query) => query.get("page") === "2" && query.get("q") === "Example",
    ),
  ).toBe(true);
});

test("filter changes reset pagination and an invalid date range remains editable", async ({
  page,
}) => {
  const reads = await ordersWorkspace(page);
  await page.goto("/admin/orders?status=confirmed&page=3");
  await expect(page.getByText("Page 3 of 4", { exact: true })).toBeVisible();
  await page.getByLabel("Filter by payment status").selectOption("partial");
  await expect(page.getByText("Page 1 of 4", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.has("page")).toBe(false);
  await page.getByLabel("Event date from").fill("2026-11-30");
  await page.getByLabel("Event date through").fill("2026-11-01");
  await expect(page.getByRole("alert")).toContainText(
    "The end date must be on or after the start date.",
  );
  await expect(page.getByLabel("Event date through")).toBeVisible();
  await page.getByLabel("Event date through").fill("2026-12-01");
  await expect(
    page.getByRole("cell", { name: "Example Customer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await expect.poll(() => reads.length).toBeGreaterThan(2);
  await expect(page.getByLabel("Filter by payment status")).toHaveValue(
    "partial",
  );
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(page.getByLabel("Filter by order status")).toHaveValue("");
  await expect(page.getByLabel("Event date from")).toHaveValue("");
  expect(new URL(page.url()).search).toBe("");
});

test("malformed bookmark parameters are ignored instead of sent to the API", async ({
  page,
}) => {
  const reads = await ordersWorkspace(page);
  await page.goto(
    "/admin/orders?status=unknown&payment_status=unknown&service_type=unknown&page=-5&from=2026-99-99&through=invalid",
  );
  await expect(page.getByText("Page 1 of 4", { exact: true })).toBeVisible();
  const query = reads.at(-1);
  expect(query.get("page")).toBe("1");
  for (const key of [
    "status",
    "payment_status",
    "service_type",
    "event_from",
    "event_to",
  ])
    expect(query.has(key)).toBe(false);
});

test("refresh moves a stale page to the last valid page without losing filters", async ({
  page,
}) => {
  const state = { total: 26 };
  const reads = await ordersWorkspace(page, state);
  await page.goto("/admin/orders?q=Example&page=2");
  await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible();
  state.total = 1;
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await expect(page.getByText("Page 1 of 1", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Search orders")).toHaveValue("Example");
  expect(new URL(page.url()).searchParams.has("page")).toBe(false);
  expect(reads.at(-1).get("page")).toBe("1");
});

test("new filters hide previous rows and disable export while awaiting matching results", async ({
  page,
}) => {
  let release;
  const state = {
    total: 1,
    hold: new Promise((resolve) => {
      release = resolve;
    }),
  };
  const reads = await ordersWorkspace(page, state);
  await page.goto("/admin/orders");
  const row = page.getByRole("cell", { name: "Example Customer", exact: true });
  await expect(row).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Export filtered orders" }),
  ).toBeEnabled();
  try {
    await page.getByLabel("Search orders").fill("Hold");
    await expect
      .poll(() => reads.some((query) => query.get("q") === "Hold"))
      .toBe(true);
    await expect(row).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Export filtered orders" }),
    ).toBeDisabled();
    await expect(page.getByLabel("Search orders")).toHaveValue("Hold");
  } finally {
    release();
  }
  await expect(row).toBeVisible();
});
