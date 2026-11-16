import { expect, test } from "@playwright/test";
import { savedOrder, linkedBooking } from "./order-fixtures.js";

async function reviewWorkspace(page, options = {}) {
  const order = savedOrder();
  order.event.starts_at = "2099-01-15T15:00:00-06:00";
  order.event.ends_at = "2099-01-15T17:00:00-06:00";
  let booking = options.linked
    ? {
        ...linkedBooking(order),
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
  await expect(page.getByLabel("Order status overview")).toContainText(
    "Cancelled",
  );
  expect(decisions[0].body.decision).toBe("deny");
  await expect(
    page.getByRole("button", { name: "Deny request", exact: true }),
  ).toHaveCount(0);
});

test("confirming an existing conditional booking uses a Central date picker and current revision", async ({
  page,
}) => {
  const { decisions } = await reviewWorkspace(page, { linked: true });
  await page
    .getByRole("textbox", { name: /Customer contract link/ })
    .fill("https://example.invalid/contract");
  const end = page.getByLabel(
    "Event end (Houston/Central time, required to confirm)",
  );
  await expect(end).toHaveAttribute("type", "datetime-local");
  await end.fill("2099-01-16T20:30");
  await page
    .getByRole("button", { name: "Confirm availability", exact: true })
    .click();
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
    await end.fill("");
    await page
      .getByRole("button", { name: "Confirm availability", exact: true })
      .click();
    await expect(page.locator(".od-review").getByRole("alert")).toContainText(
      "Add the event end time",
    );
    expect(decisions).toHaveLength(0);
    await end.fill("2099-01-15T17:00");
    await page
      .getByRole("button", { name: "Confirm availability", exact: true })
      .click();
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
  await expect(page.locator(".od-review").getByRole("alert")).toContainText(
    "Booking changed",
  );
  await expect(
    page.getByText("Decision saved. A customer email has been queued."),
  ).toHaveCount(0);
});

test("owner decision controls fit a narrow screen", async ({ page }, info) => {
  await page.setViewportSize({ width: 375, height: 844 });
  await reviewWorkspace(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("owner-review-mobile.png"),
    fullPage: true,
  });
});
