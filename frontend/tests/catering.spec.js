import { expect, test } from "@playwright/test";

async function orderDetails(
  page,
  { start = "2099-01-15T15:00", end = "" } = {},
) {
  await page.goto("/order");
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await page.locator("#cf-name").fill("Synthetic Reviewer");
  await page.locator("#cf-email").fill("reviewer@example.invalid");
  await page.locator("#cf-phone").fill("+1-202-555-0100");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.locator("#cf-line1").fill("100 Example Street");
  await page.locator("#cf-city").fill("Houston");
  await page.locator("#cf-region").fill("TX");
  await page.locator("#cf-postal").fill("77000");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.locator("#cf-event-type").fill("Synthetic celebration");
  await page.locator("#cf-starts-at").fill(start);
  if (end) await page.locator("#cf-ends-at").fill(end);
  await page.getByRole("button", { name: "Next", exact: true }).click();
}

async function api(
  page,
  {
    quoteFailure = false,
    orderFailures = 0,
    expired = false,
    review = false,
  } = {},
) {
  const quotes = [],
    orders = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (path === "/api/v1/quotes") {
      const body = request.postDataJSON();
      quotes.push(body);
      if (quoteFailure)
        return route.fulfill({
          status: 503,
          json: { error: { code: "service_unavailable" } },
        });
      return route.fulfill({
        json: {
          data: {
            id: `quote_server_${quotes.length}`,
            status: review ? "requires_review" : "priced",
            expires_at: new Date(
              Date.now() + (expired ? -1000 : 900000),
            ).toISOString(),
            ...body,
            pricing: {
              currency: "USD",
              total_cents: 34765,
              deposit_due_cents: 17383,
              line_items: [
                {
                  code: "popsicles",
                  description: "Server calculated price",
                  amount_cents: 34765,
                },
              ],
            },
          },
        },
      });
    }
    if (path === "/api/v1/orders") {
      const body = request.postDataJSON();
      orders.push({ body, key: request.headers()["idempotency-key"] });
      if (orders.length <= orderFailures)
        return route.fulfill({
          status: 503,
          json: { error: { code: "service_unavailable" } },
        });
      return route.fulfill({
        status: 201,
        json: {
          data: {
            ...body,
            id: "order_from_server_123",
            status: "pending_review",
            pricing: {
              currency: "USD",
              total_cents: 34765,
              deposit_due_cents: 17383,
            },
          },
        },
      });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return { quotes, orders };
}

async function quote(page) {
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toBeVisible();
}

test("checkout sends real API requests and shows the server's price and identifier", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await expect(page.locator("#cf-shape").getByRole("option")).toHaveText([
    "Regular — $4.50 each",
    "Heart-shaped — $3.00 each",
  ]);
  await quote(page);
  await expect(page.getByText("Total: $347.65", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Catering Request Received",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("order_from_server_123", { exact: true }),
  ).toBeVisible();
  expect(calls.quotes).toHaveLength(1);
  expect(calls.orders).toHaveLength(1);
  expect(calls.orders[0].body).toEqual({
    ...calls.quotes[0],
    quote_id: "quote_server_1",
    customer: {
      name: "Synthetic Reviewer",
      email: "reviewer@example.invalid",
      phone: "+1-202-555-0100",
    },
  });
  expect(calls.orders[0].key).toMatch(/^[a-f0-9-]{36}$/);
});

test("an even five-flavor mix is included in the quote, order, review and confirmation", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  const flavors = [
    "Mango Lime",
    "Strawberry Lime",
    "Mango Dragonfruit",
    "Strawberries and Cream",
    "Watermelon Strawberry and Kiwi",
  ];
  for (let index = 0; index < flavors.length; index++) {
    await expect(
      page.getByLabel(`Flavor ${index + 1}`, { exact: true }),
    ).toHaveValue(flavors[index]);
    await expect(
      page.getByLabel(`Qty ${index + 1}`, { exact: true }),
    ).toHaveValue("10");
  }
  await expect(page.getByRole("status")).toContainText(
    "50 of 50 paletas assigned",
  );
  await page
    .locator("#cf-flavors")
    .fill("Please confirm ingredients for our guests.");
  await quote(page);
  const mix = flavors.map((flavor) => ({ flavor, quantity: 10 }));
  expect(calls.quotes[0].catering_request.flavor_allocations).toEqual(mix);
  const summary = page.getByRole("list", { name: "Flavor quantities" });
  await expect(summary.getByRole("listitem")).toHaveCount(5);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(page).toHaveURL(/\/order\/confirm$/);
  expect(calls.orders[0].body.catering_request.flavor_allocations).toEqual(mix);
  expect(calls.orders[0].body.catering_request.flavor_requests).toBe(
    "Please confirm ingredients for our guests.",
  );
  await expect(
    page.getByRole("list", { name: "Flavor quantities" }),
  ).toContainText("Watermelon Strawberry and Kiwi");
});

test("custom dropdown quantities support fewer flavors and prevent duplicate choices", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await page
    .getByRole("button", { name: "+ Add a flavor", exact: true })
    .click();
  await page.getByLabel("Qty 1", { exact: true }).fill("30");
  await page
    .getByRole("button", { name: "+ Add a flavor", exact: true })
    .click();
  await page
    .getByLabel("Flavor 2", { exact: true })
    .selectOption("Mango Dragonfruit");
  await expect(page.getByLabel("Qty 2", { exact: true })).toHaveValue("20");
  await expect(
    page
      .getByLabel("Flavor 2", { exact: true })
      .locator('option[value="Mango Lime"]'),
  ).toBeDisabled();
  await quote(page);
  expect(calls.quotes[0].catering_request.flavor_allocations).toEqual([
    { flavor: "Mango Lime", quantity: 30 },
    { flavor: "Mango Dragonfruit", quantity: 20 },
  ]);
});

test("flavor totals must match and uneven totals split into whole quantities", async ({
  page,
}) => {
  await api(page);
  await orderDetails(page);
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  await page.getByLabel("Qty 1", { exact: true }).fill("9");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("You have 49 selected");
  await expect(page.getByLabel("Qty 1", { exact: true })).toBeFocused();
  await page.getByLabel("Qty 1", { exact: true }).fill("11");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("You have 51 selected");
  await page.locator("#cf-quantity").fill("52");
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  for (let index = 0; index < 5; index++) {
    await expect(
      page.getByLabel(`Qty ${index + 1}`, { exact: true }),
    ).toHaveValue(index < 2 ? "11" : "10");
  }
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Get quote", exact: true }),
  ).toBeVisible();
});

for (const value of ["0", "1.5", ""]) {
  test(`rejects a selected flavor quantity ${JSON.stringify(value)}`, async ({
    page,
  }) => {
    await api(page);
    await orderDetails(page);
    await page
      .getByRole("button", { name: "Split evenly across all 5" })
      .click();
    await page.getByLabel("Qty 1", { exact: true }).fill(value);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(
      "whole number of at least 1",
    );
    await expect(page.getByLabel("Qty 1", { exact: true })).toBeFocused();
  });
}

test("flavor quantities survive reload and can be cleared for Audrey to choose", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  await page.getByLabel("Qty 1", { exact: true }).fill("20");
  await page.getByLabel("Qty 2", { exact: true }).fill("5");
  await page.getByLabel("Qty 3", { exact: true }).fill("5");
  await page.reload();
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await expect(page.getByLabel("Qty 1", { exact: true })).toHaveValue("20");
  await expect(page.getByLabel("Qty 3", { exact: true })).toHaveValue("5");
  await page
    .getByRole("button", { name: "Let Audrey choose", exact: true })
    .click();
  await quote(page);
  expect(calls.quotes[0].catering_request).not.toHaveProperty(
    "flavor_allocations",
  );
});

test("older drafts without a flavor mix still restore the customer's details", async ({
  page,
}) => {
  await api(page);
  await orderDetails(page);
  await page.evaluate(() => {
    const key = "popssibilities.catering-draft.v1";
    const saved = JSON.parse(sessionStorage.getItem(key));
    delete saved.form.flavor_allocations;
    sessionStorage.setItem(key, JSON.stringify(saved));
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await expect(page.locator("#cf-quantity")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Contact details" }),
  ).toContainText("Synthetic Reviewer");
});

test("changing a flavor mix invalidates an earlier quote and retry key", async ({
  page,
}) => {
  const calls = await api(page, { orderFailures: 1 });
  await orderDetails(page);
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  await quote(page);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await page.getByRole("button", { name: "Edit paletas and extras" }).click();
  await page.getByLabel("Qty 1", { exact: true }).fill("11");
  await page.getByLabel("Qty 2", { exact: true }).fill("9");
  await quote(page);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  expect(calls.orders[1].key).not.toBe(calls.orders[0].key);
  expect(
    calls.orders[1].body.catering_request.flavor_allocations[0].quantity,
  ).toBe(11);
});

test("an unavailable quote API cannot produce an order confirmation", async ({
  page,
}) => {
  const calls = await api(page, { quoteFailure: true });
  await orderDetails(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "We could not retrieve a quote",
  );
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).not.toBeVisible();
  await expect(page).toHaveURL(/\/order$/);
  expect(calls.quotes).toHaveLength(1);
  expect(calls.orders).toHaveLength(0);
});

test("failed order submission stays on the form and retries the same payload and key", async ({
  page,
}) => {
  const calls = await api(page, { orderFailures: 1 });
  await orderDetails(page);
  await quote(page);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Your catering request could not be submitted",
  );
  await expect(page).toHaveURL(/\/order$/);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(page).toHaveURL(/\/order\/confirm$/);
  expect(calls.orders).toHaveLength(2);
  expect(calls.orders[1]).toEqual(calls.orders[0]);
});

test("Back/edit/Next requires a fresh quote and a new key for changed order details", async ({
  page,
}) => {
  const calls = await api(page, { orderFailures: 1 });
  await orderDetails(page);
  await quote(page);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Your catering request could not be submitted",
  );
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await page.locator("#cf-quantity").fill("100");
  await quote(page);
  expect(calls.quotes[1].catering_request.quantity).toBe(100);
  await page
    .getByRole("button", { name: "Submit catering request", exact: true })
    .click();
  await expect(page).toHaveURL(/\/order\/confirm$/);
  expect(calls.orders[1].key).not.toBe(calls.orders[0].key);
  expect(calls.orders[1].body.quote_id).toBe("quote_server_2");
  expect(calls.orders[1].body.catering_request.quantity).toBe(100);
});

for (const [value, message] of [
  ["50.5", "whole number"],
  ["49", "Minimum order"],
  ["100001", "Maximum order"],
]) {
  test(`rejects invalid popsicle quantity ${value}`, async ({ page }) => {
    await api(page);
    await orderDetails(page);
    await page.locator("#cf-quantity").fill(value);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.locator("#cf-quantity")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(message);
  });
}

for (const value of ["0.5", "-1", "1001"]) {
  test(`rejects invalid dry ice count ${value}`, async ({ page }) => {
    await api(page);
    await orderDetails(page);
    await page.locator("#cf-dry-ice").fill(value);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.locator("#cf-dry-ice")).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      "whole number of dry ice blocks from 0 to 1,000",
    );
  });
}

for (const [quantity, blocks] of [
  ["50", "0"],
  ["100000", "1000"],
]) {
  test(`accepts whole-number boundary quantities ${quantity} and ${blocks}`, async ({
    page,
  }) => {
    const calls = await api(page);
    await orderDetails(page);
    await page.locator("#cf-quantity").fill(quantity);
    await page.locator("#cf-dry-ice").fill(blocks);
    await quote(page);
    expect(calls.quotes[0].catering_request).toMatchObject({
      quantity: Number(quantity),
      dry_ice_blocks: Number(blocks),
    });
  });
}

test("an expired quote requires recalculation before any order request", async ({
  page,
}) => {
  const calls = await api(page, { expired: true });
  await orderDetails(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Your quote expired. Recalculate to continue.",
  );
  await expect(
    page.getByRole("button", { name: "Recalculate quote", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toHaveCount(0);
  expect(calls.orders).toHaveLength(0);
});

test("manual-review quotes do not claim that an order was submitted", async ({
  page,
}) => {
  const calls = await api(page, { review: true });
  await orderDetails(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(
    "Your order has not been submitted",
  );
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).not.toBeVisible();
  expect(calls.orders).toHaveLength(0);
  await expect(
    page.getByRole("link", { name: "Email our team" }),
  ).toHaveAttribute("href", "mailto:info@popssibilities.com");
});

test.describe("Houston event schedule", () => {
  test.use({ timezoneId: "Asia/Tokyo" });

  for (const [month, offset, abbreviation] of [
    ["01", "-06:00", "CST"],
    ["07", "-05:00", "CDT"],
  ]) {
    test(`uses Central time for month ${month} even on a device in Tokyo`, async ({
      page,
    }) => {
      const calls = await api(page);
      await orderDetails(page, {
        start: `2099-${month}-15T15:00`,
        end: `2099-${month}-15T17:00`,
      });
      await quote(page);
      const schedule = page.getByRole("region", { name: "Event schedule" });
      await expect(schedule).toContainText(`3:00 PM ${abbreviation}`);
      await expect(schedule).toContainText(`5:00 PM ${abbreviation}`);
      expect(calls.quotes[0].event).toMatchObject({
        starts_at: `2099-${month}-15T15:00:00${offset}`,
        ends_at: `2099-${month}-15T17:00:00${offset}`,
        timezone: "America/Chicago",
      });
      await page
        .getByRole("button", { name: "Submit catering request", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "Catering Request Received" }),
      ).toBeVisible();
      await expect(
        page.getByText(`3:00 PM ${abbreviation}`, { exact: false }),
      ).toBeVisible();
      await expect(
        page.getByText(`5:00 PM ${abbreviation}`, { exact: false }),
      ).toBeVisible();
      await expect(
        page.getByText("100 Example Street, Houston, TX, 77000", {
          exact: true,
        }),
      ).toBeVisible();
      expect(calls.orders[0].body.event).toEqual(calls.quotes[0].event);
      expect(
        await page.evaluate(() =>
          sessionStorage.getItem("popssibilities.catering-draft.v1"),
        ),
      ).toBeNull();
    });
  }

  for (const [date, message] of [
    ["2099-03-08T02:30", "skipped when daylight saving time begins"],
    ["2099-11-01T01:30", "occurs twice when daylight saving time ends"],
  ]) {
    test(`explains an ambiguous or nonexistent Central time: ${date}`, async ({
      page,
    }) => {
      const calls = await api(page);
      await orderDetails(page, { start: date });
      await expect(page.getByRole("alert")).toContainText(message);
      await expect(page.locator("#cf-starts-at")).toBeFocused();
      expect(calls.quotes).toHaveLength(0);
    });
  }

  test("rejects an end before the start and focuses the end field", async ({
    page,
  }) => {
    await api(page);
    await orderDetails(page, {
      start: "2099-01-15T15:00",
      end: "2099-01-15T14:00",
    });
    await expect(page.locator("#cf-ends-at")).toBeFocused();
    await expect(page.locator("#cf-ends-at")).toHaveAccessibleDescription(
      /All event times are in Houston\/Central time.*Event end must be after/,
    );
  });
});

test("a draft survives closing and reloading, and start over confirms before clearing it", async ({
  page,
}) => {
  await api(page);
  await orderDetails(page);
  await page.getByRole("button", { name: "Close catering form" }).click();
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await expect(page.locator("#cf-quantity")).toBeVisible();
  await page.reload();
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Edit contact", exact: true }).click();
  await expect(page.locator("#cf-name")).toHaveValue("Synthetic Reviewer");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Start over", exact: true }).click();
  await expect(page.locator("#cf-name")).toHaveValue("Synthetic Reviewer");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Start over", exact: true }).click();
  await expect(page.locator("#cf-name")).toHaveValue("");
  await expect
    .poll(() =>
      page.evaluate(() =>
        sessionStorage.getItem("popssibilities.catering-draft.v1"),
      ),
    )
    .toBeNull();
});

test("review edits require a new quote when the schedule changes", async ({
  page,
}) => {
  const calls = await api(page);
  await orderDetails(page);
  await quote(page);
  await page
    .getByRole("button", { name: "Edit event schedule", exact: true })
    .click();
  await page
    .getByLabel("Event end date and time (optional)")
    .fill("2099-01-15T17:30");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toBeVisible();
  expect(calls.quotes[1].event.ends_at).toBe("2099-01-15T17:30:00-06:00");
});

test("validation focuses the first invalid input without moving focus as the user types", async ({
  page,
}) => {
  await api(page);
  await page.goto("/order");
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByLabel("Full name")).toBeFocused();
  await expect(page.getByLabel("Full name")).toHaveAccessibleDescription(
    "Full name is required.",
  );
  await page.getByLabel("Full name").fill("Synthetic Reviewer");
  await expect(page.getByLabel("Full name")).toBeFocused();
});

for (const width of [320, 375, 768]) {
  test(`booking controls stay within a ${width}px viewport`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 700 });
    await api(page);
    await orderDetails(page);
    await page.getByRole("button", { name: "Back", exact: true }).click();
    await expect(page.getByLabel("Event start date and time")).toBeVisible();
    for (const control of [
      page.getByRole("button", { name: "Close catering form" }),
      page.getByRole("button", { name: "Next", exact: true }),
    ]) {
      await expect(control).toBeInViewport();
      const box = await control.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
