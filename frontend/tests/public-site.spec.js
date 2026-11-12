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
