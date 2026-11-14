import { expect, test } from "@playwright/test";
import { dashboardData, savedOrder } from "./order-fixtures.js";

const now = new Date("2026-11-14T18:00:00Z");

async function ownerSession(route, page) {
  const current = await page.evaluate(() => Date.now());
  return route.fulfill({
    json: {
      data: {
        administrator: {
          id: "refresh-owner",
          name: "Owner",
          email: "owner@example.invalid",
          role: "owner",
          permissions: ["bookings:read"],
        },
        csrf_token: "fixture-csrf",
        expires_at: new Date(current + 3600000).toISOString(),
        idle_expires_at: new Date(current + 900000).toISOString(),
      },
    },
  });
}

test("dashboard refresh marks only successful reads fresh and clears data on access denial", async ({
  page,
}) => {
  await page.clock.install({ time: now });
  let phase = "initial";
  let reads = 0;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/admin/session") return ownerSession(route, page);
    if (path === "/api/v1/admin/dashboard") {
      reads += 1;
      if (phase === "transient" || phase === "denied")
        return route.fulfill({
          status: phase === "denied" ? 403 : 503,
          json: {
            error: {
              code: phase === "denied" ? "forbidden" : "service_unavailable",
            },
          },
        });
      return route.fulfill({
        json: {
          data: { ...dashboardData(), requests: phase === "changed" ? 3 : 1 },
        },
      });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  await page.goto("/admin/dashboard");
  const card = page.getByRole("region", {
    name: "New catering requests",
    exact: true,
  });
  await expect(card).toContainText("1");
  const stamp = page.locator(".adm-refresh time");
  const initialStamp = await stamp.getAttribute("datetime");
  phase = "transient";
  await page.clock.runFor(61000);
  await expect(page.locator(".adm-refresh__status")).toContainText(
    "Refresh failed.",
  );
  await expect(card).toContainText("1");
  await expect(stamp).toHaveAttribute("datetime", initialStamp);
  phase = "changed";
  await page.getByRole("button", { name: "Refresh data", exact: true }).click();
  await expect(card).toContainText("3");
  expect(await stamp.getAttribute("datetime")).not.toBe(initialStamp);
  phase = "denied";
  await page.clock.runFor(61000);
  await expect(card).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText(
    "Could not load dashboard",
  );
  expect(reads).toBe(4);
});

test("order-detail refresh preserves a transient failure but removes an unauthorized record", async ({
  page,
}) => {
  await page.clock.install({ time: now });
  let failureStatus = null;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/admin/session") return ownerSession(route, page);
    if (path === "/api/v1/admin/orders/order_example_001") {
      if (failureStatus)
        return route.fulfill({
          status: failureStatus,
          json: {
            error: {
              code: failureStatus === 403 ? "forbidden" : "service_unavailable",
            },
          },
        });
      return route.fulfill({
        json: { data: { order: savedOrder(), booking: null } },
      });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  await page.goto("/admin/orders/order_example_001");
  const heading = page.getByRole("heading", {
    name: /order_example_001.*EXAMPLE CUSTOMER/,
  });
  await expect(heading).toBeVisible();
  failureStatus = 503;
  await page.clock.runFor(61000);
  await expect(page.locator(".adm-refresh__status")).toContainText(
    "Refresh failed.",
  );
  await expect(heading).toBeVisible();
  failureStatus = 403;
  await page.clock.runFor(61000);
  await expect(heading).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("Could not load order");
});
