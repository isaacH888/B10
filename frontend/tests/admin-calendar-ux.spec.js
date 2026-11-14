import { expect, test } from "@playwright/test";
import { calendarEvent } from "./order-fixtures.js";

const frozenNow = "2026-11-13T18:00:00Z";

function event(id, customer, start, end, status = "confirmed") {
  return calendarEvent({
    id,
    order_id: id,
    customer,
    start,
    end,
    status,
    calendar_status: status === "confirmed" ? "synced" : "pending",
  });
}

function events() {
  return [
    event(
      "past-fulfilled",
      "Past fulfilled",
      "2026-11-09T17:00:00Z",
      "2026-11-09T19:00:00Z",
      "fulfilled",
    ),
    event(
      "future-later",
      "Later same day",
      "2026-11-18T20:00:00Z",
      "2026-11-18T22:00:00Z",
    ),
    event(
      "past-active",
      "Past active",
      "2026-11-12T17:00:00Z",
      "2026-11-12T19:00:00Z",
    ),
    event(
      "ongoing",
      "Ongoing event",
      "2026-11-13T17:00:00Z",
      "2026-11-13T19:00:00Z",
    ),
    event(
      "future-cancelled",
      "Future cancelled",
      "2026-11-17T17:00:00Z",
      "2026-11-17T19:00:00Z",
      "cancelled",
    ),
    event(
      "future-fulfilled",
      "Future fulfilled",
      "2026-11-17T20:00:00Z",
      "2026-11-17T22:00:00Z",
      "fulfilled",
    ),
    event(
      "future-earlier",
      "Earlier same day",
      "2026-11-18T16:00:00Z",
      "2026-11-18T18:00:00Z",
    ),
    event(
      "future-pending",
      "Planning request",
      "2026-11-20T17:00:00Z",
      "2026-11-20T19:00:00Z",
      "pending",
    ),
  ];
}

async function mockCalendar(page, { denyAfterFirst = false } = {}) {
  let calendarReads = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const ok = (data) => route.fulfill({ json: { data } });
    if (url.pathname === "/api/v1/admin/session") {
      const browserNow = await page.evaluate(() => Date.now());
      const expires = new Date(browserNow + 3600000).toISOString();
      return ok({
        administrator: {
          id: "calendar-owner",
          name: "Calendar Reviewer",
          email: "owner@example.invalid",
          role: "owner",
          permissions: ["bookings:read"],
        },
        csrf_token: "test-calendar-csrf",
        expires_at: expires,
        idle_expires_at: expires,
      });
    }
    if (url.pathname === "/api/v1/admin/calendar") {
      calendarReads += 1;
      if (denyAfterFirst && calendarReads > 1) {
        return route.fulfill({
          status: 403,
          json: { error: { code: "forbidden" } },
        });
      }
      const matching =
        url.searchParams.get("year") === "2026" &&
        url.searchParams.get("month") === "11";
      return ok({
        events: matching ? events() : [],
        timezone: "America/Chicago",
        stats: { confirmed: 4, pending: 1, confirmed_quantity: 200 },
      });
    }
    if (url.pathname === "/api/v1/admin/automation/google")
      return ok({ status: "disconnected", configured: false });
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return { reads: () => calendarReads };
}

test("Upcoming hides past and finished events, keeps ongoing work, and sorts by start time", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(frozenNow) });
  await mockCalendar(page);
  await page.goto("/admin/calendar");
  await expect(
    page.getByRole("button", { name: /^Past fulfilled,/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Upcoming", exact: true }).click();
  const table = page.getByRole("region", { name: "Upcoming events table" });
  await expect(table.locator("tbody tr")).toHaveText([
    /Ongoing event/,
    /Earlier same day/,
    /Later same day/,
    /Planning request/,
  ]);
  await expect(table).not.toContainText("Past active");
  await expect(table).not.toContainText("Past fulfilled");
  await expect(table).not.toContainText("Future cancelled");
  await expect(table).not.toContainText("Future fulfilled");
  await expect(page.locator(".cal-upcoming-banner")).toContainText(
    "150 paletas",
  );
  await expect(
    page.getByRole("heading", { name: "Upcoming events for November 2026" }),
  ).toBeAttached();
});

test("Today returns to the business month in Central time, including a UTC month boundary", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-12-01T02:00:00Z") });
  await mockCalendar(page);
  await page.goto("/admin/calendar");
  await expect(
    page.getByRole("heading", { name: "NOVEMBER 2026", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("30, today", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Next month" }).click();
  await expect(
    page.getByRole("heading", { name: "DECEMBER 2026", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "NOVEMBER 2026", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("30, today", { exact: true })).toBeVisible();
});

test("calendar dialog traps keyboard focus, isolates the background, and restores its trigger", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(frozenNow) });
  await mockCalendar(page);
  await page.goto("/admin/calendar");
  const trigger = page.getByRole("button", { name: /^Ongoing event,/ });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  const close = dialog.getByRole("button", { name: "Close event details" });
  const last = dialog.getByRole("button", { name: "Back to calendar" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(last).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await expect(page.locator("body")).toHaveCSS("overflow", "hidden");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
});

test("background calendar refresh keeps the current event drawer open", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(frozenNow) });
  const calendar = await mockCalendar(page);
  await page.goto("/admin/calendar");
  await page.getByRole("button", { name: /^Ongoing event,/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect.poll(calendar.reads).toBe(1);
  await page.clock.fastForward(60001);
  await expect.poll(calendar.reads).toBe(2);
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("ONGOING EVENT");
});

test("an explicit access denial clears calendar events and any open drawer", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(frozenNow) });
  await mockCalendar(page, { denyAfterFirst: true });
  await page.goto("/admin/calendar");
  await page.getByRole("button", { name: /^Ongoing event,/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.clock.fastForward(60001);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText(
    "Could not load calendar events",
  );
  await expect(
    page.getByRole("button", { name: /^Ongoing event,/ }),
  ).toHaveCount(0);
});
