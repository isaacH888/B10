import { expect, test } from "@playwright/test";

async function sessions(page, { signedIn = false, unavailable = false } = {}) {
  const now = Date.now();
  await page.route("**/api/v1/**", (route) => {
    const customer =
      new URL(route.request().url()).pathname === "/api/v1/customer/session";
    if (customer && signedIn) {
      return route.fulfill({
        json: {
          data: {
            customer: {
              id: "customer-public-test",
              name: "Reviewer",
              email: "reviewer@example.invalid",
            },
            csrf_token: "synthetic-public-test-csrf",
            expires_at: new Date(now + 3600000).toISOString(),
            idle_expires_at: new Date(now + 900000).toISOString(),
          },
        },
      });
    }
    return route.fulfill({
      status: unavailable ? 503 : 401,
      json: {
        error: {
          code: unavailable ? "authentication_unavailable" : "unauthenticated",
        },
      },
    });
  });
}

test("the public homepage loads the uploaded images and opens the existing catering form", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await sessions(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "BIG JOY.ON A STICK.",
  );
  for (const image of await page.locator("img").all()) {
    await image.scrollIntoViewIfNeeded();
    await expect
      .poll(() =>
        image.evaluate(
          (element) => element.complete && element.naturalWidth > 0,
        ),
      )
      .toBe(true);
  }
  await page.getByRole("link", { name: "Bring pops to your event" }).click();
  await expect(page).toHaveURL(/\/order$/);
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await expect(page.getByLabel("Full name")).toBeVisible();
  expect(errors).toEqual([]);
});

test("the approved sample flavors are discoverable from navigation and lead to catering", async ({
  page,
}) => {
  await sessions(page);
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Flavors", exact: true })
    .click();
  await expect(page).toHaveURL(/#flavors$/);
  const menu = page.getByRole("region", { name: /MEET A FEW\s*FAVORITES\./ });
  await expect(menu).toBeInViewport();
  const flavors = page.getByRole("list", { name: "Sample flavors" });
  await expect(flavors.getByRole("listitem")).toHaveCount(5);
  await expect(flavors).toContainText("Mango Dragonfruit");
  await expect(flavors).toContainText("Watermelon Strawberry and Kiwi");
  await page.getByRole("link", { name: "Build your catering mix" }).click();
  await expect(page).toHaveURL(/\/order$/);
});

test("homepage sign-in opens the branded screen and retains provider authentication", async ({
  page,
}) => {
  await sessions(page);
  const logins = [];
  await page.route("**/api/v1/customer/login", (route) => {
    logins.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        data: {
          authorization_url:
            "https://test.auth.us-east-1.amazoncognito.com/oauth2/authorize",
        },
      },
    });
  });
  await page.route(
    "https://test.auth.us-east-1.amazoncognito.com/**",
    (route) =>
      route.fulfill({
        contentType: "text/html",
        body: "<h1>Secure sign-in</h1>",
      }),
  );
  await page.goto("/");
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("BIENVENIDO!", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Continue with email and password" })
    .click();
  await expect(page).toHaveURL(
    "https://test.auth.us-east-1.amazoncognito.com/oauth2/authorize",
  );
  expect(logins).toEqual([{ provider: "password" }]);
});

test("a restored customer session is accessible from the public navigation", async ({
  page,
}) => {
  await sessions(page, { signedIn: true });
  await page.goto("/");
  await page.getByRole("link", { name: "My account", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(
    page.getByRole("heading", { name: "Welcome, Reviewer." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Popssibilities home" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "BIG JOY.ON A STICK.",
  );
});

test("public content stays available during an authentication outage", async ({
  page,
}) => {
  await sessions(page, { unavailable: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Sign-in is temporarily unavailable.",
  );
});

test("section links keep their anchor while navigation to catering starts at the top", async ({
  page,
}) => {
  await sessions(page);
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Our story", exact: true })
    .click();
  await expect(page).toHaveURL(/#our-story$/);
  await expect(page.locator("#story-heading")).toBeInViewport();
  await page.getByRole("link", { name: "Plan a little joy" }).click();
  await expect(page).toHaveURL(/\/order$/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.getByRole("heading", { level: 1 })).toBeInViewport();
  await page.goBack();
  await expect(page).toHaveURL(/#our-story$/);
  await expect(page.locator("#story-heading")).toBeInViewport();
});

test("Audrey's gallery rotates in view and supports pausing and choosing photos", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.clock.install();
  await sessions(page);
  await page.goto("/#our-story");
  const gallery = page.getByRole("region", { name: "Moments with Audrey" });
  const photo = (number) =>
    gallery.getByRole("button", { name: `Show photo ${number}` });
  await expect(gallery).toBeInViewport();
  await page.mouse.move(0, 0);
  await expect(photo(1)).toHaveAttribute("aria-current", "true");

  await page.clock.fastForward(5600);
  await expect(photo(2)).toHaveAttribute("aria-current", "true");
  await gallery.hover();
  await page.clock.fastForward(11000);
  await expect(photo(2)).toHaveAttribute("aria-current", "true");
  await page.mouse.move(0, 0);
  await page.clock.fastForward(5600);
  await expect(photo(3)).toHaveAttribute("aria-current", "true");

  await gallery.getByRole("button", { name: "Pause slideshow" }).click();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(11000);
  await expect(photo(3)).toHaveAttribute("aria-current", "true");
  await gallery.getByRole("button", { name: "Next photo" }).click();
  await expect(photo(4)).toHaveAttribute("aria-current", "true");
  await gallery.getByRole("button", { name: "Next photo" }).click();
  await expect(photo(1)).toHaveAttribute("aria-current", "true");
  await gallery.getByRole("button", { name: "Previous photo" }).click();
  await expect(photo(4)).toHaveAttribute("aria-current", "true");
  await photo(2).click();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(11000);
  await expect(photo(2)).toHaveAttribute("aria-current", "true");

  await gallery.getByRole("button", { name: "Play slideshow" }).click();
  await page.mouse.move(0, 0);
  await page.clock.fastForward(5600);
  await expect(photo(3)).toHaveAttribute("aria-current", "true");
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(gallery).not.toBeInViewport();
  await page.clock.fastForward(11000);
  await expect(photo(3)).toHaveAttribute("aria-current", "true");
});

test("Audrey's gallery respects reduced motion and works with keyboard controls", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install();
  await sessions(page);
  await page.goto("/#our-story");
  const gallery = page.getByRole("region", { name: "Moments with Audrey" });
  await expect(
    gallery.getByRole("button", { name: "Play slideshow" }),
  ).toBeVisible();
  await page.clock.fastForward(11000);
  await expect(
    gallery.getByRole("button", { name: "Show photo 1" }),
  ).toHaveAttribute("aria-current", "true");

  await gallery.getByRole("button", { name: "Next photo" }).focus();
  await page.keyboard.press("Enter");
  await expect(
    gallery.getByRole("button", { name: "Show photo 2" }),
  ).toHaveAttribute("aria-current", "true");
  await expect(
    gallery.getByRole("group", { name: "Photo 2 of 4", exact: true }),
  ).toHaveCSS("transition-duration", "0s");
  await expect(gallery.getByRole("img")).toHaveCount(1);
});

for (const width of [320, 375, 768, 1440]) {
  test(`public pages fit a ${width}px viewport and keep catering and sign-in reachable`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await sessions(page);
    for (const path of ["/", "/login", "/order"]) {
      await page.goto(path);
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      if (path === "/login") {
        await expect(
          page.getByRole("button", {
            name: "Continue with email and password",
          }),
        ).toBeVisible();
      } else {
        await expect(
          page
            .getByRole("navigation", { name: "Main navigation" })
            .getByRole("link", { name: "Catering order" }),
        ).toBeVisible();
      }
    }
  });
}
