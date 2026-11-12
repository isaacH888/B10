import { expect, test } from "@playwright/test";

const csrf = "synthetic-owner-csrf";
const prefix = "/api/v1/admin/automation";
const booking = {
  id: "a".repeat(32),
  reference: "POP-EXAMPLE",
  status: "awaiting_deposit",
  payment_status: "unpaid",
  calendar_status: "pending",
  revision: 2,
  schedule_revision: 0,
  start: "2027-06-12T19:00:00+00:00",
  end: "2027-06-12T21:00:00+00:00",
  timezone: "America/Chicago",
  venue: "Test venue",
  service_type: "delivery",
  quantity: 50,
  count_finalized: false,
  total_minor: 10001,
  deposit_minor: 5001,
  paid_minor: 0,
  remaining_minor: 10001,
  currency: "USD",
  last_synced_at: null,
  calendar_error: null,
};

async function mock(page, role = "owner") {
  let current = { ...booking };
  const payments = [],
    mutations = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (path === "/api/v1/admin/session") {
      return route.fulfill({
        json: {
          data: {
            administrator: {
              id: "owner-id",
              email: "owner@example.invalid",
              name: "Test",
              role,
              permissions: ["bookings:read", "payments:manage"],
            },
            csrf_token: csrf,
            expires_at: new Date(Date.now() + 3600000).toISOString(),
            idle_expires_at: new Date(Date.now() + 900000).toISOString(),
          },
        },
      });
    }
    if (path === "/api/v1/customer/session")
      return route.fulfill({
        status: 401,
        json: { error: { code: "unauthenticated" } },
      });
    if (request.method() === "POST") {
      expect(request.headers()["x-csrf-token"]).toBe(csrf);
      const body = request.postDataJSON();
      mutations.push({ path, body });
      if (path.endsWith("/payments")) {
        payments.push({ ...body });
        current = {
          ...current,
          revision: 3,
          status: "confirmed",
          payment_status: "deposit_paid",
          paid_minor: 5001,
          remaining_minor: 5000,
        };
      }
      return route.fulfill({ json: { data: current } });
    }
    if (path === prefix + "/google")
      return route.fulfill({
        json: {
          data: {
            status: "reconnect_required",
            last_error: "Reconnect Google Calendar to restore access.",
          },
        },
      });
    if (path === prefix + "/bookings")
      return route.fulfill({ json: { data: [current] } });
    if (path === prefix + "/orders")
      return route.fulfill({ json: { data: [] } });
    if (path === prefix + "/bookings/" + current.id)
      return route.fulfill({
        json: { data: { booking: current, payments, jobs: [] } },
      });
    if (path === "/api/v1/admin/inventory")
      return route.fulfill({ json: { data: { items: [] } } });
    if (
      path ===
      "/api/v1/admin/inventory/bookings/" + current.id + "/allocations"
    )
      return route.fulfill({
        json: {
          data: {
            booking_id: current.id,
            revision: current.revision,
            items: [],
          },
        },
      });
    return route.fulfill({
      status: 404,
      json: { error: { code: "not_found" } },
    });
  });
  return mutations;
}

test("owner verifies a half deposit while the remaining balance and Calendar state remain visible", async ({
  page,
}) => {
  const mutations = await mock(page);
  await page.goto(`/admin/bookings/${booking.id}`);
  await expect(
    page.getByRole("heading", { name: "Catering automation" }),
  ).toBeVisible();
  await expect(
    page.getByText("Reconnect Google Calendar to restore access.", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByLabel("Unique provider transaction reference")
    .fill("provider-123");
  await page.getByLabel("Provider", { exact: true }).fill("Square");
  await page.getByLabel("Verified amount (USD minor units)").fill("5001");
  await page
    .getByLabel("Verification details from provider records")
    .fill("Checked settled Square transaction in merchant account");
  await page.getByRole("button", { name: "Record verified payment" }).click();
  await expect(
    page.getByText("confirmed / deposit_paid / pending", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("$50.01 / $50.00", {
      exact: true,
    }),
  ).toBeVisible();
  expect(mutations[0].body).toMatchObject({
    amount_minor: 5001,
    currency: "USD",
    reference: "provider-123",
    expected_revision: 2,
  });
  await page
    .getByRole("button", { name: "Repair missing event or calendar mapping" })
    .click();
  await expect.poll(() => mutations.length).toBe(2);
  expect(mutations[1].path).toContain("/repair");
});

test("staff cannot open owner automation controls", async ({ page }) => {
  const mutations = await mock(page, "staff");
  await page.goto("/admin/automation");
  await expect(
    page.getByText("Only the owner can operate booking automation.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Record verified payment" }),
  ).not.toBeVisible();
  expect(mutations).toHaveLength(0);
});

test("a booking failure does not hide the Google Calendar connection", async ({
  page,
}) => {
  await mock(page);
  await page.route(`**${prefix}/bookings`, (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          code: "automation_unavailable",
          message: "Bookings are temporarily unavailable.",
        },
      },
    }),
  );
  await page.route(`**${prefix}/google`, (route) =>
    route.fulfill({ json: { data: { status: "disconnected" } } }),
  );
  await page.goto("/admin/automation");
  const google = page.getByRole("group", {
    name: "Google Calendar connection",
  });
  await expect(
    google.getByText("Connection: disconnected", { exact: true }),
  ).toBeVisible();
  await expect(
    google.getByRole("button", {
      name: "Connect Google Calendar",
      exact: true,
    }),
  ).toBeEnabled();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeDisabled();
  await expect(page.getByRole("alert")).toHaveText(
    "Bookings are temporarily unavailable.",
  );
  await expect(
    page.getByText("No bookings yet.", { exact: true }),
  ).not.toBeVisible();
});

test("Google Calendar status failures show the server explanation beside the connection", async ({
  page,
}) => {
  await mock(page);
  await page.route(`**${prefix}/google`, (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: {
          code: "automation_unavailable",
          message: "Booking automation is not configured.",
        },
      },
    }),
  );
  await page.goto("/admin/automation");
  const google = page.getByRole("group", {
    name: "Google Calendar connection",
  });
  await expect(
    google.getByText("Connection: Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(google.getByRole("alert")).toHaveText(
    "Could not load Google Calendar status. Booking automation is not configured.",
  );
  await expect(
    google.getByRole("button", {
      name: "Connect Google Calendar",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeDisabled();
  await expect(
    google.getByRole("button", { name: "Refresh status" }),
  ).toBeEnabled();
  await expect(
    page.getByRole("link", { name: booking.reference, exact: true }),
  ).toBeVisible();
});

test("an unconfigured Google OAuth client explains the setup requirement and disables connect", async ({
  page,
}) => {
  await mock(page);
  const setup =
    "Google Calendar setup is required. Ask your administrator to configure the Google OAuth client before connecting.";
  await page.route(`**${prefix}/google`, (route) =>
    route.fulfill({
      json: {
        data: {
          status: "disconnected",
          configured: false,
          setup_message: setup,
        },
      },
    }),
  );
  await page.goto("/admin/automation");
  const google = page.getByRole("group", {
    name: "Google Calendar connection",
  });
  await expect(google.getByText(setup, { exact: true })).toBeVisible();
  await expect(
    google.getByRole("button", {
      name: "Connect Google Calendar",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeDisabled();
});

test("refreshing Google Calendar clears a stale connection and disables actions until status is known", async ({
  page,
}) => {
  await mock(page);
  let releaseRefresh;
  const refreshResponse = new Promise((resolve) => {
    releaseRefresh = resolve;
  });
  let requests = 0;
  await page.route(`**${prefix}/google`, async (route) => {
    if (++requests === 1)
      return route.fulfill({
        json: { data: { status: "connected", calendar_id: "test-calendar" } },
      });
    await refreshResponse;
    return route.fulfill({
      status: 503,
      json: {
        error: {
          code: "automation_unavailable",
          message: "Calendar status is temporarily unavailable.",
        },
      },
    });
  });
  await page.goto("/admin/automation");
  const google = page.getByRole("group", {
    name: "Google Calendar connection",
  });
  await expect(
    google.getByText("Connection: connected", { exact: true }),
  ).toBeVisible();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeEnabled();
  await google.getByRole("button", { name: "Refresh status" }).click();
  await expect(google.getByRole("status")).toHaveText("Connection: Loading…");
  await expect(
    google.getByText("Calendar: test-calendar", { exact: true }),
  ).not.toBeVisible();
  await expect(
    google.getByRole("button", {
      name: "Connect Google Calendar",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeDisabled();
  releaseRefresh();
  await expect(
    google.getByText("Connection: Unavailable", { exact: true }),
  ).toBeVisible();
  await expect(google.getByRole("alert")).toContainText(
    "Calendar status is temporarily unavailable.",
  );
  await expect(
    google.getByRole("button", {
      name: "Connect Google Calendar",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    google.getByRole("button", { name: "Disconnect Google Calendar" }),
  ).toBeDisabled();
});

test("signed-out private booking links redirect to team sign-in", async ({
  page,
}) => {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    }),
  );
  await page.goto(`/admin/bookings/${booking.id}`);
  await expect(page).toHaveURL(/\/admin\/login$/);
  await expect(
    page.getByRole("heading", { name: "Catering automation" }),
  ).not.toBeVisible();
});

test("owner imports a customer order without retyping its selections or price", async ({
  page,
}) => {
  await mock(page);
  const order = {
    id: "order_customer_123",
    customer: {
      name: "Synthetic Customer",
      email: "customer@example.invalid",
      phone: "+1-202-555-0100",
    },
    event: {
      type: "Celebration",
      starts_at: "2027-06-12T14:00:00-05:00",
      ends_at: null,
      timezone: "America/Chicago",
      notes: "Outdoor event",
    },
    catering_request: {
      quantity: 75,
      popsicle_shape: "heart",
      service_type: "delivery",
      flavor_requests: "Mango",
      add_ons: [],
      dry_ice_blocks: 2,
    },
    pricing: { total_cents: 40000, deposit_due_cents: 20000, currency: "USD" },
  };
  let created = false,
    submitted;
  await page.route(`**${prefix}/orders`, (route) =>
    route.fulfill({ json: { data: created ? [] : [order] } }),
  );
  await page.route(`**${prefix}/orders/${order.id}/booking`, (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(csrf);
    submitted = route.request().postDataJSON();
    created = true;
    return route.fulfill({
      status: 201,
      json: { data: { ...booking, source_order: order } },
    });
  });
  await page.goto("/admin/automation");
  await page
    .getByText(`Synthetic Customer · ${order.id}`, { exact: true })
    .click();
  const intake = page.getByRole("region", { name: "Customer order intake" });
  await expect(
    intake.getByText("75 heart popsicles · delivery", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Confirmed event end (ISO date, time and UTC offset)")
    .fill("2027-06-12T16:00:00-05:00");
  await page
    .getByLabel("Order contract link (HTTPS)")
    .fill("https://example.invalid/contract");
  await page
    .getByRole("button", { name: "Create booking from order", exact: true })
    .click();
  await expect(
    intake.getByText("No customer orders awaiting intake.", { exact: true }),
  ).toBeVisible();
  expect(submitted).toEqual({
    end: "2027-06-12T16:00:00-05:00",
    contract_url: "https://example.invalid/contract",
  });
});
