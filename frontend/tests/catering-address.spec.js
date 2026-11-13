import { expect, test } from "@playwright/test";

const location = {
  line1: "100 Example Street",
  city: "Houston",
  region: "TX",
  postal_code: "77000",
  country_code: "US",
};
const area = (outside = false) => ({
  enabled: true,
  radius_miles: 30,
  origin_name: "Stafford, TX 77477",
  origin_postal_code: "77477",
  distance_method: "zip_centroid_radius",
  service_area_enabled: true,
  status: outside ? "outside_area" : "within_area",
  distance_miles: outside ? 100 : 12.5,
  message: outside
    ? "This address is outside our 30-mile catering area. Please contact our team about a custom event."
    : "This address is within our 30-mile catering area.",
});

async function addressApi(
  page,
  {
    enabled = true,
    serviceAreaEnabled = true,
    resolve,
    check,
    suggestionsFail = false,
  } = {},
) {
  const searches = [],
    selections = [],
    checks = [];
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    }),
  );
  await page.route("**/api/v1/catering/address/**", async (route) => {
    const path = new URL(route.request().url()).pathname.split("/").at(-1);
    if (path === "config")
      return route.fulfill({
        json: {
          data: {
            enabled,
            service_area_enabled: serviceAreaEnabled,
            radius_miles: 30,
            origin_name: "Stafford, TX 77477",
            origin_postal_code: "77477",
            distance_method: "zip_centroid_radius",
          },
        },
      });
    const body = route.request().postDataJSON();
    if (path === "suggestions") {
      searches.push(body);
      if (suggestionsFail)
        return route.fulfill({
          status: 503,
          json: { error: { code: "address_unavailable" } },
        });
      return route.fulfill({
        json: {
          data: {
            suggestions: [
              {
                place_id: "synthetic.first.signature",
                label: "100 Example Street, Houston, TX, USA",
                attributions: [
                  {
                    name: "Synthetic address source",
                    url: "https://example.invalid/source",
                  },
                ],
              },
              {
                place_id: "synthetic.second.signature",
                label: "200 Example Avenue, Houston, TX, USA",
              },
            ],
          },
        },
      });
    }
    if (path === "resolve") {
      selections.push(body);
      if (resolve) return resolve(route, body);
      return route.fulfill({
        json: {
          data: {
            location: {
              ...location,
              line1:
                body.place_id === "synthetic.second.signature"
                  ? "200 Example Avenue"
                  : location.line1,
            },
            ...(body.check_service_area === false
              ? {}
              : { service_area: area() }),
            attributions: [
              {
                name: "Synthetic address source",
                url: "https://example.invalid/source",
              },
            ],
          },
        },
      });
    }
    checks.push(body);
    if (check) return check(route, body);
    return route.fulfill({
      json: {
        data: area(
          ["79900", "77550", "34698"].includes(
            body.location.postal_code.slice(0, 5),
          ),
        ),
      },
    });
  });
  return { searches, selections, checks };
}

async function stepTwo(page) {
  await page.goto("/order");
  await page
    .getByRole("button", { name: "Request a quote", exact: true })
    .first()
    .click();
  await page.locator("#cf-name").fill("Synthetic Reviewer");
  await page.locator("#cf-email").fill("reviewer@example.invalid");
  await page.locator("#cf-phone").fill("+1-202-555-0100");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Service & Location", exact: true }),
  ).toBeVisible();
}

async function manualAddress(page, postal = "77000") {
  for (const [id, value] of [
    ["line1", location.line1],
    ["city", location.city],
    ["region", location.region],
    ["postal", postal],
  ]) {
    await page.locator("#cf-" + id).fill(value);
  }
}

test("suggested addresses fill city, state and ZIP using a bound address selection", async ({
  page,
}) => {
  const calls = await addressApi(page);
  await stepTwo(page);
  const address = page.getByRole("combobox", { name: "Event address" });
  await address.fill("100 Exam");
  await expect(
    page.getByRole("link", { name: "Synthetic address source" }),
  ).toHaveAttribute("href", "https://example.invalid/source");
  await page
    .getByRole("option", { name: "100 Example Street, Houston, TX, USA" })
    .click();
  await expect(page.locator("#cf-line1")).toHaveValue(location.line1);
  await expect(page.locator("#cf-city")).toHaveValue("Houston");
  await expect(page.locator("#cf-region")).toHaveValue("TX");
  await expect(page.locator("#cf-postal")).toHaveValue("77000");
  await expect(
    page.getByRole("link", { name: "Synthetic address source" }),
  ).toBeVisible();
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".address-search")
      .getByRole("link", { name: "Geoapify", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Google Maps", { exact: true })).toHaveCount(0);
  expect(calls.searches).toHaveLength(1);
  expect(calls.selections[0].session_token).toBe(
    calls.searches[0].session_token,
  );
  expect(calls.selections[0].session_token).toMatch(/^[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Event Schedule", exact: true }),
  ).toBeVisible();
  expect(calls.selections[0].check_service_area).toBe(false);
  expect(calls.checks).toHaveLength(1);
  await expect(page.getByText(/driving miles from/)).toHaveCount(0);
});

test("address suggestions support arrows and Escape without closing the form", async ({
  page,
}) => {
  await addressApi(page);
  await stepTwo(page);
  const address = page.getByRole("combobox", { name: "Event address" });
  await address.fill("100 Exam");
  await expect(
    page.getByRole("listbox", { name: "Address suggestions" }),
  ).toBeVisible();
  await address.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toBeVisible();
  await address.fill("200 Exam");
  await expect(page.getByRole("listbox")).toBeVisible();
  await address.press("ArrowUp");
  await expect(
    page.getByRole("option", { name: "200 Example Avenue, Houston, TX, USA" }),
  ).toHaveAttribute("aria-selected", "true");
  await address.press("Enter");
  await expect(address).toHaveValue("200 Example Avenue");
});

test("selecting another address in the same ZIP preserves its area status", async ({
  page,
}) => {
  const calls = await addressApi(page);
  await stepTwo(page);
  const address = page.getByRole("combobox", { name: "Event address" });
  await address.fill("100 Exam");
  await page.getByRole("option").first().click();
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  await address.fill("200 Exam");
  await page.getByRole("option").nth(1).click();
  await expect(address).toHaveValue("200 Example Avenue");
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  expect(calls.checks).toHaveLength(1);
});

test("outside-area customers can continue to a quote estimate for owner review", async ({
  page,
}) => {
  const calls = await addressApi(page);
  const orders = [];
  let reviewRequest;
  await page.route("**/api/v1/orders", async (route) => {
    orders.push(route.request().postDataJSON());
    await route.abort();
  });
  await page.route("**/api/v1/quotes", async (route) => {
    const body = route.request().postDataJSON();
    reviewRequest = body;
    return route.fulfill({
      json: {
        data: {
          ...body,
          id: "quote_owner_review",
          status: "requires_review",
          pricing: null,
          estimate: {
            currency: "USD",
            subtotal_cents: 22500,
            line_items: [
              {
                code: "popsicles",
                description: "50 regular paletas at $4.50 each",
                amount_cents: 22500,
              },
            ],
          },
          next_action: {
            type: "contact_inquiry",
            reason_code: "outside_delivery_radius",
            inquiry_url: null,
            message:
              "Contact the owner to confirm availability and travel fees.",
          },
        },
      },
    });
  });
  await stepTwo(page);
  await manualAddress(page, "79900");
  await page
    .getByRole("button", { name: "Check service area", exact: true })
    .click();
  await expect(
    page.getByText("Owner review needed", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Ask about a custom event" }),
  ).toBeVisible();
  await expect(page.getByText(/driving miles from/)).toHaveCount(0);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Event Schedule", exact: true }),
  ).toBeVisible();
  expect(calls.checks[0].location.postal_code).toBe("79900");
  await page.locator("#cf-event-type").fill("Synthetic event");
  await page.locator("#cf-starts-at").fill("2099-01-15T15:00");
  await page.locator("#cf-ends-at").fill("2099-01-15T17:00");
  await page
    .locator("#cf-event-notes")
    .fill("Please use the service entrance.");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Split evenly across all 5" }).click();
  await page
    .locator("#cf-flavors")
    .fill("Nut allergy; please confirm coconut-free options.");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Quote estimate" }),
  ).toContainText("Paletas & extras: $225.00");
  await expect(
    page.getByText(
      "Service and travel fees are not included. The owner will confirm availability and the final total.",
    ),
  ).toBeVisible();
  const email = page.getByRole("link", {
    name: "Email the owner about this quote",
  });
  const emailBody = new URL(await email.getAttribute("href")).searchParams.get(
    "body",
  );
  for (const detail of [
    "quote_owner_review",
    "Synthetic Reviewer",
    "reviewer@example.invalid",
    "+1-202-555-0100",
    "Synthetic event",
    "America/Chicago",
    reviewRequest.event.starts_at,
    reviewRequest.event.ends_at,
    "Mango Lime: 10",
    "Watermelon Strawberry and Kiwi: 10",
    "Nut allergy; please confirm coconut-free options.",
    "Please use the service entrance.",
  ])
    expect(emailBody).toContain(detail);
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toHaveCount(0);
  expect(orders).toEqual([]);
});

test("autofill completes while the service-area check is still pending", async ({
  page,
}) => {
  let release;
  const wait = new Promise((resolve) => {
    release = resolve;
  });
  await addressApi(page, {
    check: async (route) => {
      await wait;
      return route.fulfill({ json: { data: area() } });
    },
  });
  await stepTwo(page);
  await page.locator("#cf-line1").fill("100 Exam");
  await page.getByRole("option").first().click();
  await expect(page.locator("#cf-city")).toHaveValue("Houston");
  await expect(page.locator("#cf-postal")).toHaveValue("77000");
  await expect(
    page.getByText("Checking service area…", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Event Schedule", exact: true }),
  ).toBeVisible();
  release();
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
});

test("editing an autofilled ZIP invalidates the earlier eligible result", async ({
  page,
}) => {
  const calls = await addressApi(page);
  await stepTwo(page);
  await page.locator("#cf-line1").fill("100 Exam");
  await page.getByRole("option").first().click();
  await expect(page.locator("#cf-postal")).toHaveValue("77000");
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  await page.locator("#cf-postal").fill("79900");
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Check service area", exact: true })
    .click();
  await expect(
    page.getByText("Owner review needed", { exact: true }),
  ).toBeVisible();
  expect(calls.checks).toHaveLength(2);
});

test("a delayed selection cannot overwrite fields the customer edits", async ({
  page,
}) => {
  let release;
  const wait = new Promise((resolve) => {
    release = resolve;
  });
  await addressApi(page, {
    resolve: async (route) => {
      await wait;
      return route.fulfill({
        json: { data: { location, service_area: area() } },
      });
    },
  });
  await stepTwo(page);
  await page.locator("#cf-line1").fill("100 Exam");
  await page.getByRole("option").first().click();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  await page.locator("#cf-city").fill("Manual City");
  release();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeEnabled();
  await expect(page.locator("#cf-city")).toHaveValue("Manual City");
  await expect(page.locator("#cf-postal")).toHaveValue("");
});

test("Geoapify unavailable keeps manual entry and has working contact links for review", async ({
  page,
}) => {
  await addressApi(page, { enabled: false });
  await page.route("**/api/v1/quotes", (route) =>
    route.fulfill({
      json: {
        data: {
          status: "requires_review",
          pricing: null,
          next_action: {
            type: "contact_inquiry",
            reason_code: "address_verification_unavailable",
            inquiry_url: null,
            message:
              "We could not verify the travel distance. Please contact our team for a service-area review.",
          },
        },
      },
    }),
  );
  await stepTwo(page);
  await expect(page.getByText(/Enter your event ZIP code/)).toBeVisible();
  await manualAddress(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.locator("#cf-event-type").fill("Synthetic event");
  await page.locator("#cf-starts-at").fill("2099-01-15T15:00");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Get quote", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Submit catering request", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Email our team", exact: true }),
  ).toHaveAttribute("href", "mailto:info@popssibilities.com");
  await page
    .getByRole("button", { name: "Edit event address", exact: true })
    .click();
  await expect(page.locator("#cf-line1")).toHaveValue(location.line1);
});

test("suggestion failure leaves manual address fields usable", async ({
  page,
}) => {
  await addressApi(page, { suggestionsFail: true });
  await stepTwo(page);
  await page.locator("#cf-line1").fill("100 Exam");
  await expect(
    page.getByText(
      "Address suggestions are unavailable. You can enter the address manually.",
    ),
  ).toBeVisible();
  await manualAddress(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Event Schedule", exact: true }),
  ).toBeVisible();
});

for (const width of [320, 375, 768]) {
  test(`address suggestions and service-area controls fit ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await addressApi(page);
    await stepTwo(page);
    await page.locator("#cf-line1").fill("100 Exam");
    await expect(page.getByRole("listbox")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const box = await page.getByRole("listbox").boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await expect
      .poll(() =>
        page.locator(".address-search__results").evaluate((element) => {
          const results = element.getBoundingClientRect();
          const body = element.closest(".modal-body").getBoundingClientRect();
          return (
            results.top >= body.top - 1 && results.bottom <= body.bottom + 1
          );
        }),
      )
      .toBe(true);
    await page.getByRole("option").first().click();
    await expect(page.locator("#cf-postal")).toHaveValue("77000");
  });
}

test("ZIP-only radius checks work even without address suggestions", async ({
  page,
}) => {
  const calls = await addressApi(page, { enabled: false });
  await stepTwo(page);
  await page.locator("#cf-postal").fill("77477");
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/ZIP-area centers within 30 miles of Stafford, TX 77477/),
  ).toBeVisible();
  await expect(page.locator("#cf-line1")).toHaveValue("");
  await expect(page.locator("#cf-city")).toHaveValue("");
  await page.locator("#cf-city").fill("Stafford");
  await page.locator("#cf-line1").fill("Manually entered street");
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toBeVisible();
  expect(calls.checks).toHaveLength(1);
  expect(calls.checks[0].location.postal_code).toBe("77477");
  await page.locator("#cf-postal").fill("77550");
  await expect(
    page.getByText("Owner review needed", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toHaveCount(0);
});

test("an older ZIP result cannot approve a newly entered distant ZIP", async ({
  page,
}) => {
  let release;
  const waiting = new Promise((resolve) => {
    release = resolve;
  });
  const calls = await addressApi(page, {
    enabled: false,
    check: async (route, body) => {
      if (body.location.postal_code === "77477") await waiting;
      return route.fulfill({
        json: { data: area(body.location.postal_code !== "77477") },
      });
    },
  });
  await stepTwo(page);
  await page.locator("#cf-postal").fill("77477");
  await expect.poll(() => calls.checks.length).toBe(1);
  await page.locator("#cf-postal").fill("77550");
  await expect(
    page.getByText("Owner review needed", { exact: true }),
  ).toBeVisible();
  release();
  await expect(
    page.getByText("Owner review needed", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Within our service area", { exact: true }),
  ).toHaveCount(0);
});
