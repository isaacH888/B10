import { expect, test } from "@playwright/test";
import { customerSession } from "./customer-session.js";
import { savedOrder } from "./order-fixtures.js";

async function ordersApi(page, { empty = false, fail = false } = {}) {
  let status = "pending_review";
  const requests = [];
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/customer/session")
      return route.fulfill({ json: { data: customerSession() } });
    if (url.pathname === "/api/v1/customer/orders") {
      requests.push(url.search);
      if (fail)
        return route.fulfill({
          status: 503,
          json: { error: { code: "service_unavailable" } },
        });
      const order = { ...savedOrder(), status };
      return route.fulfill({
        json: {
          data: {
            items: empty ? [] : [order],
            total: empty ? 0 : 11,
            page: Number(url.searchParams.get("page")),
            page_size: 10,
          },
        },
      });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return {
    requests,
    update: (next) => {
      status = next;
      fail = false;
    },
  };
}

test("My Orders shows status and deposit, supports paging and refreshes owner updates", async ({
  page,
}) => {
  const calls = await ordersApi(page);
  await page.goto("/account");
  await page.getByRole("link", { name: "My Orders" }).click();
  const orders = page.getByRole("region", { name: "Your orders" });
  await expect(orders.getByText("Under review", { exact: true })).toBeVisible();
  await expect(orders).toContainText("Awaiting verification");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  expect(calls.requests.at(-1)).toBe("?page=2&page_size=10");
  calls.update("confirmed");
  await page.getByRole("button", { name: "Refresh orders" }).click();
  await expect(orders.getByText("Confirmed", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByText("Page 1 of 2")).toBeVisible();
});

test("My Orders shows an empty state and recovers from a failed read", async ({
  page,
}) => {
  const calls = await ordersApi(page, { fail: true, empty: true });
  await page.goto("/account?view=orders");
  await expect(page.getByRole("alert")).toContainText(
    "couldn’t load your latest order status",
  );
  calls.update("pending_review");
  await page.getByRole("button", { name: "Refresh orders" }).click();
  await expect(
    page.getByRole("heading", { name: "No orders yet" }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: "Your orders" })
      .getByRole("link", { name: "Request a catering quote" }),
  ).toBeVisible();
});

test("account order cards fit a narrow phone screen", async ({ page }) => {
  await ordersApi(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/account?view=orders");
  await expect(page.getByText("Under review", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
