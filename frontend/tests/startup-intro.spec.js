import { expect, test } from "@playwright/test";

const seenKey = "popssibilities:intro:v1";
const intro = (page) =>
  page.getByRole("dialog", { name: "Welcome to Popssibilities", exact: true });

async function unauthenticated(page) {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    }),
  );
}

async function pauseTime(page) {
  await page.clock.install({ time: new Date("2030-01-01T00:00:00Z") });
  await page.clock.pauseAt(new Date("2030-01-01T00:00:01Z"));
}

async function holdReact(page) {
  let release;
  const held = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/src/main.jsx*", async (route) => {
    await held;
    await route.continue();
  });
  return release;
}

async function expectUnlocked(page) {
  await expect(page.locator("#startup-intro")).toBeHidden();
  await expect(page.locator("#root")).toHaveJSProperty("inert", false);
  expect(
    await page.locator("body").evaluate((body) => body.style.overflow),
  ).not.toBe("hidden");
  expect(
    await page.evaluate(() =>
      Boolean(document.activeElement?.closest("#startup-intro")),
    ),
  ).toBe(false);
}

test("five cumulative bites finish on a bare stick before the intro dismisses", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  await page.goto("/");
  await expect(page.locator("#home-heading")).toHaveText("BIG JOY.ON A STICK.");
  await expect(intro(page)).toBeVisible();
  await expect(page.locator("#root")).toHaveJSProperty("inert", true);
  await expect(page.locator("[data-popsicle-body]")).toBeVisible();
  await expect(page.locator("[data-popsicle-stick]")).toBeVisible();
  await expect(page.locator("#startup-intro-skip")).toBeFocused();

  for (let stage = 1; stage <= 5; stage += 1) {
    await page.clock.runFor(stage === 1 ? 319 : 320);
    if (stage === 1) {
      await expect(page.locator('[data-bite="1"]')).toHaveCSS("opacity", "0");
      await page.clock.runFor(1);
    }
    await expect(page.locator("#startup-intro")).toHaveAttribute(
      "data-stage",
      String(stage),
    );
    for (let bite = 1; bite <= 5; bite += 1) {
      await expect(page.locator(`[data-bite="${bite}"]`)).toHaveCSS(
        "opacity",
        bite <= stage ? "1" : "0",
      );
    }
  }

  await expect(page.locator("[data-popsicle-body]")).toHaveCSS(
    "visibility",
    "hidden",
  );
  await expect(page.locator("[data-popsicle-stick]")).toBeVisible();
  await expect(intro(page)).toBeVisible();
  await page.clock.runFor(199);
  await expect(intro(page)).toBeVisible();
  await page.clock.runFor(201);
  await expectUnlocked(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("a skipped intro stays skipped on reload and internal customer navigation", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  await page.goto("/");
  await expect(intro(page)).toBeVisible();
  await page
    .getByRole("button", { name: "Skip animation", exact: true })
    .press("Enter");
  await expectUnlocked(page);
  await page.clock.resume();
  expect(
    await page.evaluate((key) => sessionStorage.getItem(key), seenKey),
  ).toBe("seen");

  await page.getByRole("link", { name: "Bring pops to your event" }).click();
  await expect(page).toHaveURL(/\/order$/);
  await expectUnlocked(page);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectUnlocked(page);
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await expect(page.getByLabel("Full name")).toBeVisible();
});

test("a fresh tab has its own first public-entry intro", async ({
  page,
  context,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  await page.goto("/");
  await expect(intro(page)).toBeVisible();
  await page.locator("#startup-intro-skip").press("Enter");
  await expectUnlocked(page);

  const otherTab = await context.newPage();
  await otherTab.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(otherTab);
  await pauseTime(otherTab);
  await otherTab.goto("/order");
  await expect(intro(otherTab)).toBeVisible();
  await otherTab.locator("#startup-intro-skip").press("Enter");
  await expectUnlocked(otherTab);
  await otherTab.close();
});

test("account, authentication, confirmation, and anchor entries bypass the intro", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  for (const path of [
    "/login",
    "/account",
    "/order/confirm",
    "/admin/login",
    "/#flavors",
  ]) {
    await page.goto(path);
    await expect(page.locator("#root")).not.toBeEmpty();
    await expectUnlocked(page);
    expect(
      await page.evaluate((key) => sessionStorage.getItem(key), seenKey),
    ).toBe(null);
  }
});

test("blocked session storage does not break startup or skipping", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  await page.addInitScript(() => {
    Object.defineProperty(window, "sessionStorage", {
      get() {
        throw new DOMException("Storage is blocked", "SecurityError");
      },
    });
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(intro(page)).toBeVisible();
  await page.locator("#startup-intro-skip").press("Enter");
  await expectUnlocked(page);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(errors).toEqual([]);
});

test("reduced motion keeps the artwork static and removes the intro as soon as React is ready", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await unauthenticated(page);
  await pauseTime(page);
  const releaseReact = await holdReact(page);
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(intro(page)).toBeVisible();
    await page.clock.runFor(1000);
    await expect(page.locator("#startup-intro")).toHaveAttribute(
      "data-stage",
      "0",
    );
    await expect(page.locator("[data-popsicle-body]")).toBeVisible();
  } finally {
    releaseReact();
  }
  await expect(page.locator("#home-heading")).toHaveText("BIG JOY.ON A STICK.");
  await expectUnlocked(page);
});

for (const dismissal of ["skip", "escape"]) {
  test(`${dismissal} works before the React bundle loads and does not trap focus`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await unauthenticated(page);
    await pauseTime(page);
    const releaseReact = await holdReact(page);
    try {
      await page.goto("/order", { waitUntil: "commit" });
      await expect(intro(page)).toBeVisible();
      await expect(page.locator("#root")).toBeEmpty();
      await expect(page.locator("#startup-intro-skip")).toBeFocused();
      if (dismissal === "skip") {
        await page.keyboard.press("Enter");
      } else {
        await page.keyboard.press("Escape");
      }
      await expectUnlocked(page);
    } finally {
      releaseReact();
    }
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectUnlocked(page);
  });
}

test("slow startup reaches a four-second failsafe and the page recovers when React arrives", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  const releaseReact = await holdReact(page);
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(intro(page)).toBeVisible();
    await page.clock.runFor(3999);
    await expect(intro(page)).toBeVisible();
    await expect(page.locator("#root")).toHaveJSProperty("inert", true);
    await page.clock.runFor(1);
    await expectUnlocked(page);
    await expect(page.locator("#startup-fallback")).toBeVisible();
  } finally {
    releaseReact();
  }
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("#startup-fallback")).toBeHidden();
  await expectUnlocked(page);
});

test("skipping before a failed bundle still leaves a recovery action after four seconds", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await unauthenticated(page);
  await pauseTime(page);
  const releaseReact = await holdReact(page);
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(intro(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expectUnlocked(page);
    await page.clock.runFor(4000);
    await expect(page.locator("#startup-fallback")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Reload page" }),
    ).toBeEnabled();
  } finally {
    releaseReact();
  }
  await expect(page.locator("#home-heading")).toBeVisible();
  await expect(page.locator("#startup-fallback")).toBeHidden();
});

test("switching off reduced motion does not introduce an unexpected startup delay", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await unauthenticated(page);
  await pauseTime(page);
  const releaseReact = await holdReact(page);
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(intro(page)).toBeVisible();
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.clock.runFor(500);
    await expect(page.locator("#startup-intro")).toHaveAttribute(
      "data-stage",
      "0",
    );
  } finally {
    releaseReact();
  }
  await expect(page.locator("#home-heading")).toBeVisible();
  await expectUnlocked(page);
});
