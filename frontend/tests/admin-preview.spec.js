import { expect, test } from "@playwright/test";

const previewPaths = [
  "/admin/dashboard",
  "/admin/orders",
  "/admin/orders/%231048",
  "/admin/calendar",
  "/admin/inventory",
];

async function mockSessions(page, options = {}) {
  const requests = [];
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({
      path,
      method: request.method(),
      headers: request.headers(),
    });
    if (path === "/api/v1/admin/session" && request.method() === "DELETE") {
      return route.fulfill({
        status: 401,
        json: { error: { code: "unauthenticated" } },
      });
    }
    if (path === "/api/v1/admin/session" && options.authenticated) {
      return route.fulfill({
        json: {
          data: {
            administrator: {
              id: "preview-owner",
              name: "Reviewer",
              email: "reviewer@example.invalid",
              role: options.role || "owner",
              permissions: options.permissions || ["bookings:read"],
            },
            csrf_token: "preview-test-csrf",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(
              Date.now() + (options.lifetime || 900000),
            ).toISOString(),
          },
        },
      });
    }
    return route.fulfill({
      status: options.unavailable ? 503 : 401,
      json: {
        error: {
          code: options.unavailable
            ? "authentication_unavailable"
            : "unauthenticated",
        },
      },
    });
  });
  return requests;
}

for (const path of previewPaths) {
  test(`signed-out visitors cannot open ${path}`, async ({ page }) => {
    await mockSessions(page);
    await page.goto(path);
    await expect(page).toHaveURL(/\/admin\/login$/);
    await expect(page.locator(".adm-shell")).toHaveCount(0);
  });

  test(`owners can open the labeled preview at ${path}`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const requests = await mockSessions(page, { authenticated: true });
    await page.goto(path);
    await expect(page.locator(".adm-shell")).toBeVisible();
    await expect(page.getByLabel("Design preview notice")).toContainText(
      "fictional sample data",
    );
    await expect(
      page.getByRole("link", { name: "Manage live bookings and Calendar" }),
    ).toHaveAttribute("href", "/admin/automation");
    await expect(
      page.getByRole("link", { name: "Owner account", exact: true }),
    ).toHaveAttribute("href", "/admin");
    await expect(
      page.getByRole("navigation", { name: "Admin pages" }),
    ).toBeVisible();
    expect(requests.every((request) => request.method === "GET")).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const options of [{ role: "staff" }, { permissions: [] }]) {
  test(`preview requires owner role and booking permission: ${JSON.stringify(options)}`, async ({
    page,
  }) => {
    await mockSessions(page, { authenticated: true, ...options });
    await page.goto("/admin/orders");
    await expect(
      page.getByRole("heading", { name: "Owner access required" }),
    ).toBeVisible();
    await expect(page.locator(".adm-shell")).toHaveCount(0);
  });
}

test("an authentication outage does not expose preview data", async ({
  page,
}) => {
  await mockSessions(page, { unavailable: true });
  await page.goto("/admin/inventory");
  await expect(
    page.getByRole("heading", { name: "Sign-in unavailable" }),
  ).toBeVisible();
  await expect(page.locator(".adm-shell")).toHaveCount(0);
});

test("the preview expires with the existing administrator session", async ({
  page,
}) => {
  await page.clock.install();
  await mockSessions(page, { authenticated: true, lifetime: 5000 });
  await page.goto("/admin/dashboard");
  await expect(page.locator(".adm-shell")).toBeVisible();
  await page.clock.fastForward(6000);
  await expect(page).toHaveURL(/\/admin\/login\?error=session_expired$/);
  await expect(page.locator(".adm-shell")).toHaveCount(0);
});

test("preview sign-out uses the real session endpoint and CSRF protection", async ({
  page,
}) => {
  const requests = await mockSessions(page, { authenticated: true });
  await page.goto("/admin/dashboard");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/login$/);
  const logout = requests.find((request) => request.method === "DELETE");
  expect(logout.path).toBe("/api/v1/admin/session");
  expect(logout.headers["x-csrf-token"]).toBe("preview-test-csrf");
});

for (const width of [375, 768, 1440]) {
  test(`admin previews fit a ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockSessions(page, { authenticated: true });
    for (const path of previewPaths) {
      await page.goto(path);
      await expect(page.locator(".adm-shell")).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        path,
      ).toBe(true);
    }
  });
}

test("calendar previews retain Central calendar dates and filter the selected year and month", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-11-10T12:00:00-06:00") });
  await mockSessions(page, { authenticated: true });
  await page.goto("/admin/calendar");
  const sofia = page.getByRole("button", {
    name: "Sofia Ramirez, Delivery, 200 paletas, pending",
  });
  await expect(sofia).toBeVisible();
  await expect(
    page
      .getByRole("gridcell")
      .filter({ has: sofia })
      .locator(".cal-cell__date"),
  ).toHaveText("21");
  await page.getByRole("button", { name: "Upcoming", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Upcoming events table" }),
  ).toContainText("Sofia Ramirez");
  await page.getByRole("button", { name: "Next month" }).click();
  await expect(page.locator(".adm-hero-row__sub")).toContainText(
    "December 2026 · 0 confirmed bookings · 0 pending requests · 0 paletas reserved",
  );
  await expect(
    page.getByRole("region", { name: "Upcoming events table" }),
  ).not.toContainText("Sofia Ramirez");
  for (let index = 0; index < 11; index++) {
    await page.getByRole("button", { name: "Next month" }).click();
  }
  await expect(page.locator(".adm-hero-row__sub")).toContainText(
    "November 2027 · 0 confirmed bookings · 0 pending requests · 0 paletas reserved",
  );
});
