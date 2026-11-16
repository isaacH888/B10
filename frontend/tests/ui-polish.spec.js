import { expect, test } from "@playwright/test";

function session(role) {
  return {
    administrator: {
      id: "ui-polish-reviewer",
      name: "Synthetic Reviewer",
      email: "reviewer@example.invalid",
      role,
      permissions: ["bookings:read"],
    },
    csrf_token: "synthetic-ui-polish-csrf",
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    idle_expires_at: new Date(Date.now() + 900000).toISOString(),
  };
}

async function mockApi(page, options = {}) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/admin/session" && options.role)
      return route.fulfill({ json: { data: session(options.role) } });
    if (path.endsWith("/session")) {
      const status = path.includes("/admin/")
        ? options.adminStatus || 401
        : 401;
      return route.fulfill({
        status,
        json: {
          error: {
            code:
              status === 403
                ? "forbidden"
                : status === 503
                  ? "authentication_unavailable"
                  : "unauthenticated",
          },
        },
      });
    }
    if (/\/automation\/(bookings|orders)$/.test(path))
      return route.fulfill({ json: { data: [] } });
    if (path.endsWith("/automation/google"))
      return route.fulfill({
        json: { data: { status: "disconnected", configured: false } },
      });
    if (path.endsWith("/automation/requests"))
      return route.fulfill({
        json: { data: { enabled: false, email_mode: "disabled" } },
      });
    return route.fulfill({
      status: 404,
      json: { error: { code: "not_found" } },
    });
  });
}

async function expectReadableAction(action) {
  const colors = await action.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.color, style.backgroundColor].map((color) =>
      color.match(/[\d.]+/g).map(Number),
    );
  });
  const luminance = (color) =>
    color.slice(0, 3).reduce((total, channel, index) => {
      const value = channel / 255;
      const linear =
        value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      return total + linear * [0.2126, 0.7152, 0.0722][index];
    }, 0);
  expect(colors[1][3] ?? 1).toBe(1);
  const light = colors.map(luminance).sort((a, b) => b - a);
  expect((light[0] + 0.05) / (light[1] + 0.05)).toBeGreaterThanOrEqual(4.5);
  await action.focus();
  await expect(action).toBeFocused();
}

for (const status of [403, 503]) {
  test(`the real admin ${status} screen has a readable, working retry action`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 900 });
    const options = { adminStatus: status };
    await mockApi(page, options);
    await page.goto("/admin/dashboard");
    const retry = page.getByRole("button", { name: "Try again", exact: true });
    await expect(retry).toBeVisible();
    await expectReadableAction(retry);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(375);
    expect(
      (await page.locator(".session-error-view").boundingBox()).height,
    ).toBeGreaterThanOrEqual(900);
    options.adminStatus = 401;
    await retry.press("Enter");
    await expect(page).toHaveURL(/\/admin\/login$/);
  });
}

test("staff can see and use the owner sign-in recovery link", async ({
  page,
}) => {
  await mockApi(page, { role: "staff" });
  await page.goto("/admin/dashboard");
  const signIn = page.getByRole("link", { name: "Back to owner sign-in" });
  await expect(signIn).toBeVisible();
  await expectReadableAction(signIn);
  await signIn.press("Enter");
  await expect(page).toHaveURL(/\/admin\/login\?reauth=1$/);
  await expect(
    page.getByRole("heading", { name: "Verify your access", exact: true }),
  ).toBeVisible();
});

test("catering styles preserve visible booking workspace section titles", async ({
  page,
}) => {
  await mockApi(page, { role: "owner" });
  await page.goto("/admin/automation");
  await page.getByText("Add a catering booking", { exact: true }).click();
  for (const title of [
    "Google Calendar connection",
    "Incoming request notifications",
    "Agreed order",
  ]) {
    const legend = page.getByText(title, { exact: true });
    await legend.scrollIntoViewIfNeeded();
    await expect(legend).toBeVisible();
    const box = await legend.boundingBox();
    expect(box.width).toBeGreaterThan(50);
    expect(box.height).toBeGreaterThanOrEqual(20);
  }
});

function slide(hero, number) {
  return hero.getByRole("button", {
    name: new RegExp(`^Go to slide ${number}:`),
  });
}

test("reduced motion keeps catering photos still while keyboard controls work", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  await mockApi(page);
  await page.goto("/order");
  const hero = page.getByRole("region", { name: /Bring the Chill/ });
  await expect(
    hero.getByRole("button", { name: "Play slideshow" }),
  ).toBeVisible();
  await page.clock.fastForward(10000);
  await expect(slide(hero, 1)).toHaveAttribute("aria-current", "true");
  await hero.getByRole("button", { name: "Next slide" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
  await page.clock.fastForward(10000);
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
});

test("catering rotation pauses for hover, offscreen content, focus and motion changes", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.clock.install();
  await mockApi(page);
  // An anchor entry bypasses the separate startup intro.
  await page.goto("/order#cat-hero-heading");
  const hero = page.getByRole("region", { name: /Bring the Chill/ });
  await expect(hero).toBeInViewport();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(4600);
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
  await hero.hover();
  await page.clock.fastForward(10000);
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
  await page.mouse.move(0, 0);
  await page.clock.fastForward(4600);
  await expect(slide(hero, 3)).toHaveAttribute("aria-current", "true");
  await page.evaluate(() =>
    window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }),
  );
  await expect(hero).not.toBeInViewport();
  await page.clock.fastForward(10000);
  await expect(slide(hero, 3)).toHaveAttribute("aria-current", "true");
  await hero.scrollIntoViewIfNeeded();
  await expect(hero).toBeInViewport();
  await page.clock.fastForward(4600);
  await expect(slide(hero, 4)).toHaveAttribute("aria-current", "true");
  await hero.getByRole("button", { name: "Next slide" }).focus();
  await page.clock.fastForward(10000);
  await expect(slide(hero, 4)).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("ArrowRight");
  await expect(slide(hero, 1)).toHaveAttribute("aria-current", "true");
  await page.mouse.move(0, 0);
  await page.clock.fastForward(10000);
  await expect(slide(hero, 1)).toHaveAttribute("aria-current", "true");
  await hero.getByRole("button", { name: "Play slideshow" }).click();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(4600);
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(
    hero.getByRole("button", { name: "Play slideshow" }),
  ).toBeVisible();
  await page.clock.fastForward(10000);
  await expect(slide(hero, 2)).toHaveAttribute("aria-current", "true");
});
