import { expect, test } from "@playwright/test";

const csrfToken = "customer-test-email-csrf";
const endpoint = "/api/v1/customer/test-email";

function session(area = "customer", overrides = {}) {
  return {
    [area === "customer" ? "customer" : "administrator"]: {
      id: `${area}-sample`,
      email: `${area}@example.com`,
      name: "Sample customer",
      ...(area === "admin" ? { role: "owner", permissions: [] } : {}),
      ...overrides,
    },
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    idle_expires_at: new Date(Date.now() + 900000).toISOString(),
    csrf_token: csrfToken,
  };
}

async function mockApi(page, options = {}) {
  const requests = [];
  const state = { customer: session(), ...options };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === endpoint) {
      requests.push({
        method: request.method(),
        headers: request.headers(),
        body: request.postDataJSON(),
      });
      if (state.onSend) return state.onSend(route, state, requests.length);
      return route.fulfill({
        json: {
          data: {
            status: "accepted",
            reference: "TEST-SAMPLE",
            duplicate: false,
          },
        },
      });
    }
    if (path.endsWith("/session")) {
      const area = path.includes("/admin/") ? "admin" : "customer";
      const data = state[area];
      return route.fulfill(
        data
          ? { json: { data } }
          : {
              status: state[`${area}Status`] || 401,
              json: { error: { code: "session_expired" } },
            },
      );
    }
    return route.fulfill({
      status: 404,
      json: { error: { code: "not_found" } },
    });
  });
  return { state, requests };
}

test("account navigation keeps a sent email disabled when switching sections", async ({
  page,
}) => {
  const { requests } = await mockApi(page);
  await page.goto("/account");
  await expect(
    page.getByRole("heading", { name: "My Account", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Account details" }),
  ).toContainText("customer@example.com");
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).not.toBeVisible();
  const nav = page.getByRole("navigation", { name: "My account navigation" });
  await nav.getByRole("link", { name: "Email Preview" }).click();
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  await nav.getByRole("link", { name: "Account Overview" }).click();
  await nav.getByRole("link", { name: "Sign-In & Security" }).click();
  await expect(
    page.getByRole("region", { name: "Sign-in details" }),
  ).toContainText("Current session ends");
  await nav.getByRole("link", { name: "Email Preview" }).click();
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).toBeDisabled();
  expect(requests).toHaveLength(1);
});

for (const width of [320, 375, 768, 1440]) {
  test(`account details and navigation fit a ${width}px screen`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page, {
      customer: session("customer", {
        name: "A customer with a longer display name",
        email: "a-long-customer-email-address@example.invalid",
      }),
    });
    await page.goto("/account");
    const nav = page.getByRole("navigation", { name: "My account navigation" });
    for (const view of [
      "Account Overview",
      "Sign-In & Security",
      "Email Preview",
    ]) {
      const link = nav.getByRole("link", { name: view });
      await link.click();
      await expect(link).toHaveAttribute("aria-current", "page");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
    const button = page.getByRole("button", {
      name: "Send test order confirmation",
    });
    const box = await button.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    await nav.getByRole("link", { name: "Account Overview" }).click();
    await page.getByRole("link", { name: "Request a catering quote" }).click();
    await expect(page).toHaveURL(/\/order$/);
    await page.goBack();
    await expect(
      page.getByRole("heading", { name: "My Account", exact: true }),
    ).toBeVisible();
  });
}

test("a signed-in customer explicitly sends only to their server-selected account", async ({
  page,
}) => {
  const { requests } = await mockApi(page);
  await page.goto("/account?view=email");
  await expect(
    page.getByRole("heading", { name: "Test Order Confirmation", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("does not place an order or charge you", { exact: false }),
  ).toBeVisible();
  expect(requests).toHaveLength(0);
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).toBeDisabled();
  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe("POST");
  expect(requests[0].body).toEqual({});
  expect(requests[0].headers["x-csrf-token"]).toBe(csrfToken);
  expect(requests[0].headers["idempotency-key"]).toMatch(/^[a-f0-9-]{36}$/);
  expect(requests[0].headers["content-type"]).toBe("application/json");
  expect(requests[0].headers.origin).toBe("http://127.0.0.1:5190");
  expect(
    await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    })),
  ).toEqual({ local: {}, session: {} });
});

test("a pending send blocks rapid duplicate clicks", async ({ page }) => {
  let complete;
  const pending = new Promise((resolve) => {
    complete = resolve;
  });
  const { requests } = await mockApi(page, {
    onSend: async (route) => {
      await pending;
      await route.fulfill({
        json: {
          data: {
            status: "accepted",
            reference: "TEST-SAMPLE",
            duplicate: false,
          },
        },
      });
    },
  });
  await page.goto("/account?view=email");
  const button = page.getByRole("button", {
    name: "Send test order confirmation",
  });
  await button.evaluate((element) => {
    element.click();
    element.click();
  });
  await expect(
    page.getByRole("button", { name: "Sending test email…" }),
  ).toBeDisabled();
  await expect.poll(() => requests.length).toBe(1);
  complete();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
});

test("network failures reuse the same request key on explicit retry", async ({
  page,
}) => {
  const { requests } = await mockApi(page, {
    onSend: (route, _state, count) =>
      count === 1
        ? route.abort("connectionfailed")
        : route.fulfill({
            json: {
              data: {
                status: "accepted",
                reference: "TEST-SAMPLE",
                duplicate: true,
              },
            },
          }),
  });
  await page.goto("/account?view=email");
  const button = page.getByRole("button", {
    name: "Send test order confirmation",
  });
  await button.click();
  await expect(page.getByRole("alert")).toContainText("retry safely");
  expect(requests).toHaveLength(1);
  await button.click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  expect(requests).toHaveLength(2);
  expect(requests[0].headers["idempotency-key"]).toBe(
    requests[1].headers["idempotency-key"],
  );
});

for (const code of ["email_rejected", "email_unavailable"]) {
  test(`${code} allows an intentional new request after the service is repaired`, async ({
    page,
  }) => {
    const { requests } = await mockApi(page, {
      onSend: (route, _state, count) =>
        count === 1
          ? route.fulfill({ status: 503, json: { error: { code } } })
          : route.fulfill({
              json: {
                data: {
                  status: "accepted",
                  reference: "TEST-REPAIRED",
                  duplicate: false,
                },
              },
            }),
    });
    await page.goto("/account?view=email");
    const button = page.getByRole("button", {
      name: "Send test order confirmation",
    });
    await button.click();
    await expect(page.getByRole("alert")).toBeVisible();
    expect(requests).toHaveLength(1);
    await button.click();
    await expect(page.getByRole("status")).toContainText(
      "accepted for sending",
    );
    expect(requests).toHaveLength(2);
    expect(requests[0].headers["idempotency-key"]).not.toBe(
      requests[1].headers["idempotency-key"],
    );
  });
}

for (const [status, code, text] of [
  [429, "email_rate_limited", "Please wait before sending another test email"],
  [503, "email_unavailable", "The email service needs to be configured"],
]) {
  test(`${code} is explained without leaking provider details`, async ({
    page,
  }) => {
    await mockApi(page, {
      onSend: (route) =>
        route.fulfill({
          status,
          json: { error: { code, message: "private-provider-detail" } },
        }),
    });
    await page.goto("/account?view=email");
    await page
      .getByRole("button", { name: "Send test order confirmation" })
      .click();
    await expect(page.getByRole("alert")).toContainText(text);
    await expect(page.getByText("private-provider-detail")).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "Send test order confirmation" }),
    ).toBeEnabled();
  });
}

test("an uncertain send asks the customer to check their inbox and prevents another send", async ({
  page,
}) => {
  const { requests } = await mockApi(page, {
    onSend: (route) =>
      route.fulfill({
        status: 409,
        json: { error: { code: "email_delivery_uncertain" } },
      }),
  });
  await page.goto("/account?view=email");
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "may already have been sent",
  );
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).toBeDisabled();
  expect(requests).toHaveLength(1);
});

for (const status of [401, 403]) {
  test(`a send rejected with ${status} refreshes the customer session and removes the action`, async ({
    page,
  }) => {
    const { requests } = await mockApi(page, {
      onSend: (route, state) => {
        state.customer = null;
        state.customerStatus = status;
        return route.fulfill({
          status,
          json: { error: { code: "session_expired" } },
        });
      },
    });
    await page.goto("/account?view=email");
    await page
      .getByRole("button", { name: "Send test order confirmation" })
      .click();
    if (status === 401)
      await expect(page).toHaveURL(/\/login\?error=session_expired$/);
    else
      await expect(
        page.getByRole("heading", { name: "Access unavailable" }),
      ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Send test order confirmation" }),
    ).not.toBeVisible();
    expect(requests).toHaveLength(1);
  });
}

for (const scenario of ["signed-out", "administrator"]) {
  test(`${scenario} pages have no customer email action`, async ({ page }) => {
    const { requests } = await mockApi(
      page,
      scenario === "administrator"
        ? { customer: null, admin: session("admin") }
        : { customer: null },
    );
    await page.goto(scenario === "administrator" ? "/admin" : "/account");
    await expect(
      page.getByRole("heading", {
        name:
          scenario === "administrator" ? "Team account" : "Customer Sign-In",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Send test order confirmation" }),
    ).not.toBeVisible();
    expect(requests).toHaveLength(0);
  });
}

test("reloading the customer page never automatically repeats a send", async ({
  page,
}) => {
  const { requests } = await mockApi(page);
  await page.goto("/account?view=email");
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).toBeEnabled();
  expect(requests).toHaveLength(1);
});

test("switching the authenticated customer clears the previous request state", async ({
  page,
}) => {
  const { state, requests } = await mockApi(page);
  await page.clock.install();
  await page.goto("/account?view=email");
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  state.customer = session("customer", {
    id: "different-customer",
    email: "different@example.com",
  });
  await page.clock.fastForward(61000);
  await expect(
    page.getByText(
      "Send a sample order confirmation to different@example.com",
      { exact: false },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send test order confirmation" }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Send test order confirmation" })
    .click();
  await expect(page.getByRole("status")).toContainText("accepted for sending");
  expect(requests).toHaveLength(2);
  expect(requests[0].headers["idempotency-key"]).not.toBe(
    requests[1].headers["idempotency-key"],
  );
});
