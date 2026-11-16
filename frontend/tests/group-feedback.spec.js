import { expect, test } from "@playwright/test";
import { savedOrder, linkedBooking } from "./order-fixtures.js";

async function reviewWorkspace(page, options = {}) {
  const order = savedOrder();
  order.event.starts_at = "2099-01-15T15:00:00-06:00";
  order.event.ends_at = "2099-01-15T17:00:00-06:00";
  Object.assign(order.event, options.event);
  if (options.missingEnd) order.event.ends_at = null;
  let booking = options.linked
    ? {
        ...linkedBooking(order),
        start: order.event.starts_at,
        end:
          order.event.ends_at ||
          new Date(Date.parse(order.event.starts_at) + 3600000).toISOString(),
        end_unspecified: !order.event.ends_at,
        status: "conditionally_confirmed",
        revision: 4,
        paid_minor: 0,
        contract_url: "",
      }
    : null;
  const decisions = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
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
            csrf_token: "feedback-csrf",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(Date.now() + 900000).toISOString(),
          },
        },
      });
    if (request.method() === "POST" && path.endsWith("/decision")) {
      expect(request.headers()["x-csrf-token"]).toBe("feedback-csrf");
      const body = request.postDataJSON();
      decisions.push({ path, body });
      if (options.fail)
        return route.fulfill({
          status: 409,
          json: {
            error: {
              code: "revision_conflict",
              message: "Booking changed; reload before applying this action",
            },
          },
        });
      booking = {
        ...linkedBooking(order),
        start: order.event.starts_at,
        end: body.end || order.event.ends_at,
        status: {
          confirm: "awaiting_deposit",
          conditionally_confirm: "conditionally_confirmed",
          deny: "cancelled",
        }[body.decision],
        customer_message: body.message,
        contract_url: body.contract_url || "",
        revision: 5,
        paid_minor: 0,
      };
      return route.fulfill({ json: { data: booking } });
    }
    if (path.startsWith("/api/v1/admin/orders/"))
      return route.fulfill({ json: { data: { order, booking } } });
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  await page.goto(`/admin/orders/${order.id}`);
  return { order, decisions };
}

async function confirmDecision(page, name) {
  await page.getByRole("dialog").getByRole("button", { name }).click();
}

test("conditional confirmation requires an explanation and updates the saved order status", async ({
  page,
}) => {
  const { order, decisions } = await reviewWorkspace(page);
  await page
    .getByRole("button", { name: "Conditionally confirm", exact: true })
    .click();
  await expect(page.locator(".od-review").getByRole("alert")).toContainText(
    "Explain the conditions",
  );
  expect(decisions).toHaveLength(0);
  await page
    .getByRole("textbox", { name: /Message to customer/ })
    .fill("The date works. Please discuss mango instead of lavender.");
  await page
    .getByRole("button", { name: "Conditionally confirm", exact: true })
    .click();
  await confirmDecision(page, "Yes, send conditions");
  await expect(page.locator(".od-review").getByRole("status")).toContainText(
    "customer email has been queued",
  );
  await expect(page.getByLabel("Order status overview")).toContainText(
    "Conditionally confirmed",
  );
  expect(decisions).toEqual([
    {
      path: `/api/v1/admin/automation/orders/${order.id}/decision`,
      body: {
        decision: "conditionally_confirm",
        message: "The date works. Please discuss mango instead of lavender.",
        expected_version: 1,
      },
    },
  ]);
});

test("owner can deny an unlinked request without preparing a contract", async ({
  page,
}) => {
  const { decisions } = await reviewWorkspace(page);
  await page.getByRole("button", { name: "Deny request", exact: true }).click();
  expect(decisions).toHaveLength(0);
  await expect(page.getByRole("dialog")).toContainText(
    "Are you sure you want to deny this request?",
  );
  await confirmDecision(page, "Yes, deny request");
  await expect(page.getByLabel("Order status overview")).toContainText(
    "Cancelled",
  );
  expect(decisions[0].body.decision).toBe("deny");
  await expect(
    page.getByRole("button", { name: "Deny request", exact: true }),
  ).toHaveCount(0);
});

test("confirming an existing conditional booking retains a custom Central end and current revision", async ({
  page,
}) => {
  const { decisions } = await reviewWorkspace(page, { linked: true });
  await page
    .getByRole("textbox", { name: /Customer contract link/ })
    .fill("https://example.invalid/contract");
  const end = page.getByLabel(
    "Event end (Houston/Central time, required to confirm)",
  );
  await end.selectOption("custom");
  await page
    .getByLabel("Custom event end (Houston/Central time)")
    .fill("2099-01-16T20:30");
  await page
    .getByRole("button", { name: "Confirm availability", exact: true })
    .click();
  expect(decisions).toHaveLength(0);
  await confirmDecision(page, "Yes, confirm availability");
  await expect(page.locator(".od-review").getByRole("status")).toContainText(
    "customer email has been queued",
  );
  expect(decisions[0].path).toContain("/bookings/");
  expect(decisions[0].body).toMatchObject({
    expected_revision: 4,
    decision: "confirm",
    contract_url: "https://example.invalid/contract",
    end: "2099-01-17T02:30:00.000Z",
  });
  await expect(page.getByLabel("Order status overview")).toContainText(
    "Awaiting deposit",
  );
});

for (const linked of [false, true]) {
  test(`owner can confirm availability without a contract for ${linked ? "a linked booking" : "an unlinked order"}`, async ({
    page,
  }) => {
    const { decisions } = await reviewWorkspace(page, { linked });
    await expect(
      page.getByLabel("Customer contract link (optional, HTTPS)"),
    ).toBeEmpty();
    const end = page.getByLabel(
      "Event end (Houston/Central time, required to confirm)",
    );
    const suppliedEnd = await end.inputValue();
    await end.selectOption("");
    await page
      .getByRole("button", { name: "Confirm availability", exact: true })
      .click();
    await expect(page.locator(".od-review").getByRole("alert")).toContainText(
      "Add the event end time",
    );
    expect(decisions).toHaveLength(0);
    await end.selectOption(suppliedEnd);
    await page
      .getByRole("button", { name: "Confirm availability", exact: true })
      .click();
    await confirmDecision(page, "Yes, confirm availability");
    await expect(page.getByLabel("Order status overview")).toContainText(
      "Awaiting deposit",
    );
    expect(decisions).toHaveLength(1);
    expect(decisions[0].body).not.toHaveProperty("contract_url");
    expect(decisions[0].body).toMatchObject({
      decision: "confirm",
      [linked ? "expected_revision" : "expected_version"]: linked ? 4 : 1,
    });
  });
}

test("failed decisions explain the conflict without claiming an email was queued", async ({
  page,
}) => {
  await reviewWorkspace(page, { fail: true });
  await page.getByRole("button", { name: "Deny request", exact: true }).click();
  await confirmDecision(page, "Yes, deny request");
  await expect(page.locator(".od-review").getByRole("alert")).toContainText(
    "Booking changed",
  );
  await expect(
    page.getByText("Decision saved. A customer email has been queued."),
  ).toHaveCount(0);
});

test("acceptance uses the customer's supplied end and waits for confirmation", async ({
  page,
}) => {
  const { order, decisions } = await reviewWorkspace(page);
  const end = page.getByRole("combobox", { name: /^Event end/ });
  await expect(end).toHaveValue("2099-01-15T23:00:00.000Z");
  await expect(end.locator("option:checked")).toHaveText(
    "5:00 PM CST (2 hours)",
  );
  await page
    .getByRole("button", { name: "Confirm availability", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Confirm availability?" });
  await expect(dialog).toContainText(order.customer.name);
  await expect(dialog).toContainText("Ends Jan 15, 2099, 5:00 PM CST");
  expect(decisions).toHaveLength(0);
  await dialog.getByRole("button", { name: "Go back" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Confirm availability", exact: true }),
  ).toBeFocused();
  expect(decisions).toHaveLength(0);
  await page
    .getByRole("button", { name: "Confirm availability", exact: true })
    .click();
  await confirmDecision(page, "Yes, confirm availability");
  await expect.poll(() => decisions.length).toBe(1);
  expect(decisions[0].body.end).toBe("2099-01-15T23:00:00.000Z");
});

for (const linked of [false, true]) {
  test(`missing end uses a dropdown from the actual start for ${linked ? "a booking" : "an order"}`, async ({
    page,
  }) => {
    const { decisions } = await reviewWorkspace(page, {
      linked,
      missingEnd: true,
    });
    const end = page.getByRole("combobox", { name: /^Event end/ });
    await expect(end).toHaveValue("");
    await expect(
      page.getByLabel("Custom event end (Houston/Central time)"),
    ).toHaveCount(0);
    await end.selectOption({ label: "6:00 PM CST (3 hours)" });
    await page
      .getByRole("button", { name: "Confirm availability", exact: true })
      .click();
    await confirmDecision(page, "Yes, confirm availability");
    await expect.poll(() => decisions.length).toBe(1);
    expect(decisions[0].body.end).toBe("2099-01-16T00:00:00.000Z");
  });
}

test("denial can be cancelled with Escape and traps keyboard focus", async ({
  page,
}) => {
  const { decisions } = await reviewWorkspace(page, { missingEnd: true });
  const deny = page.getByRole("button", { name: "Deny request", exact: true });
  await deny.click();
  const dialog = page.getByRole("dialog", { name: "Deny this request?" });
  const back = dialog.getByRole("button", { name: "Go back" });
  const confirm = dialog.getByRole("button", { name: "Yes, deny request" });
  await expect(back).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(back).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(deny).toBeFocused();
  expect(decisions).toHaveLength(0);
  await deny.click();
  await confirm.evaluate((button) => {
    button.click();
    button.click();
  });
  await expect.poll(() => decisions.length).toBe(1);
  expect(decisions[0].body).not.toHaveProperty("end");
});

test("custom ends before the start cannot open an acceptance prompt", async ({
  page,
}) => {
  const { decisions } = await reviewWorkspace(page);
  await page
    .getByRole("combobox", { name: /^Event end/ })
    .selectOption("custom");
  await page
    .getByLabel("Custom event end (Houston/Central time)")
    .fill("2099-01-15T14:00");
  await expect(
    page.locator(".event-end-select").getByRole("alert"),
  ).toContainText("Event end must be after");
  await page
    .getByRole("button", { name: "Confirm availability", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(decisions).toHaveLength(0);
});

test.describe("event end choices use Central time independently of the owner's browser", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  for (const example of [
    {
      name: "an event ending the following day",
      start: "2027-06-12T23:15:00-05:00",
      label: "Jun 13, 2027, 12:15 AM CDT (1 hour)",
      end: "2027-06-13T05:15:00.000Z",
    },
    {
      name: "a daylight saving transition",
      start: "2027-03-14T01:30:00-06:00",
      label: "3:30 AM CDT (1 hour)",
      end: "2027-03-14T08:30:00.000Z",
    },
  ]) {
    test(example.name, async ({ page }) => {
      const { decisions } = await reviewWorkspace(page, {
        missingEnd: true,
        event: { starts_at: example.start },
      });
      await page
        .getByRole("combobox", { name: /^Event end/ })
        .selectOption({ label: example.label });
      await page
        .getByRole("button", { name: "Confirm availability", exact: true })
        .click();
      await confirmDecision(page, "Yes, confirm availability");
      await expect.poll(() => decisions.length).toBe(1);
      expect(decisions[0].body.end).toBe(example.end);
    });
  }
});

for (const width of [320, 375, 768, 1440]) {
  test(`owner decision controls fit at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await reviewWorkspace(page);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: info.outputPath("owner-review-mobile.png"),
      fullPage: true,
    });
    const layout = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      overflow: [...document.querySelectorAll("body *")]
        .filter(
          (element) => element.getBoundingClientRect().right > innerWidth + 1,
        )
        .slice(0, 12)
        .map((element) => ({
          tag: element.tagName,
          className: element.className,
        })),
    }));
    expect(layout.width, JSON.stringify(layout.overflow)).toBeLessThanOrEqual(
      width,
    );
    await page
      .getByRole("button", { name: "Deny request", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Go back" })).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Yes, deny request" }),
    ).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: info.outputPath("owner-denial-mobile.png"),
    });
  });
}
