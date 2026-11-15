import { expect, test } from "@playwright/test";

const prefix = "/api/v1/admin/automation";

async function workspace(page, { connected = true, failure = false } = {}) {
  const writes = [];
  let notifications = {
    enabled: failure,
    recipient: "owner@example.invalid",
    calendar_id: connected ? "company-calendar" : null,
    email_mode: "simulated",
    requests: failure
      ? [
          {
            order_id: "order_" + "a".repeat(32),
            email_status: "failed",
            email_error: "Email delivery needs retry.",
            email_job: "request_email:" + "a".repeat(32),
            calendar_status: "repair_required",
            calendar_error: "The event was removed; repair is required.",
          },
        ]
      : [],
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = decodeURIComponent(new URL(request.url()).pathname);
    if (path === "/api/v1/admin/session")
      return route.fulfill({
        json: {
          data: {
            administrator: {
              id: "owner",
              role: "owner",
              email: "owner@example.invalid",
              name: "Owner",
              permissions: ["bookings:read"],
            },
            csrf_token: "synthetic-csrf",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(Date.now() + 900000).toISOString(),
          },
        },
      });
    if (request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe("synthetic-csrf");
      const body = request.postDataJSON();
      writes.push({ path, body });
      if (path === prefix + "/requests")
        notifications = { ...notifications, ...body };
      return route.fulfill({ json: { data: notifications } });
    }
    if (path === prefix + "/requests")
      return route.fulfill({ json: { data: notifications } });
    if (path === prefix + "/google")
      return route.fulfill({
        json: {
          data: {
            status: connected ? "connected" : "disconnected",
            configured: true,
            calendar_id: connected ? "company-calendar" : null,
          },
        },
      });
    if ([prefix + "/bookings", prefix + "/orders"].includes(path))
      return route.fulfill({ json: { data: [] } });
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return writes;
}

test("owner enables the chosen inbox only after Calendar is connected", async ({
  page,
}) => {
  const writes = await workspace(page);
  await page.goto("/admin/automation");
  await expect(
    page.getByText("Email delivery is simulated in this local preview."),
  ).toBeVisible();
  await page
    .getByLabel("Notification email", { exact: true })
    .fill("another-owner@example.invalid");
  await page
    .getByRole("button", { name: "Use this calendar for incoming requests" })
    .click();
  await expect(
    page.getByText("Enabled for another-owner@example.invalid", {
      exact: true,
    }),
  ).toBeVisible();
  expect(writes).toEqual([
    {
      path: prefix + "/requests",
      body: { recipient: "another-owner@example.invalid", enabled: true },
    },
  ]);
  await page
    .getByRole("button", { name: "Stop new request notifications" })
    .click();
  await expect(
    page.getByText("Request notifications are not enabled."),
  ).toBeVisible();
  expect(writes[1].body).toEqual({ enabled: false });
});

test("disconnected Calendar prevents enabling request projections", async ({
  page,
}) => {
  const writes = await workspace(page, { connected: false });
  await page.goto("/admin/automation");
  await expect(
    page.getByRole("button", {
      name: "Use this calendar for incoming requests",
    }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Connect Google Calendar", exact: true }),
  ).toBeEnabled();
  expect(writes).toEqual([]);
});

test("email retry, ordinary Calendar retry and explicit repair remain separate", async ({
  page,
}) => {
  const writes = await workspace(page, { failure: true });
  await page.goto("/admin/automation");
  await page
    .getByRole("button", { name: "Retry request email", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Retry request calendar", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Repair request calendar event", exact: true })
    .click();
  expect(writes.map((write) => write.body)).toEqual([{}, {}, { repair: true }]);
  expect(writes[0].path).toContain("/jobs/request_email:");
  expect(writes[1].path).toContain("/requests/order_");
});

for (const width of [320, 375, 768, 1440]) {
  test(`request notification controls fit ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await workspace(page, { failure: true });
    await page.goto("/admin/automation");
    await expect(
      page.getByLabel("Notification email", { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
