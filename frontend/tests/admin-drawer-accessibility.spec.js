import { expect, test } from "@playwright/test";

const makeItem = (overrides = {}) => ({
  id: "inventory-example-mango",
  name: "Mango",
  category: "Fruit",
  shape: "Standard",
  onHand: 100,
  reserved: 25,
  available: 75,
  minimum: 40,
  notes: "Example inventory notes",
  version: 1,
  active: true,
  ...overrides,
});

async function connect(page, initialItems = [makeItem()]) {
  let items = initialItems;
  let inventoryStatus = 200;
  let inventoryReads = 0;
  await page.route("**/api/v1/**", (route) => {
    const { pathname } = new URL(route.request().url());
    const ok = (data) => route.fulfill({ json: { data } });
    if (pathname === "/api/v1/admin/session") {
      return ok({
        administrator: {
          id: "example-owner",
          name: "Example Owner",
          email: "owner@example.invalid",
          role: "owner",
          permissions: ["bookings:read", "customers:export"],
        },
        csrf_token: "example-csrf",
        expires_at: "2099-01-01T00:00:00Z",
        idle_expires_at: "2099-01-01T00:00:00Z",
      });
    }
    if (pathname === "/api/v1/admin/inventory") {
      inventoryReads += 1;
      return inventoryStatus === 200
        ? ok({ items })
        : route.fulfill({
            status: inventoryStatus,
            json: { error: { code: "access_denied" } },
          });
    }
    if (pathname.endsWith("/history")) {
      return ok({ history: [], page: 1, page_size: 25, total: 0 });
    }
    return route.fulfill({
      status: 401,
      json: { error: { code: "unauthenticated" } },
    });
  });
  return {
    setItems(value) {
      items = value;
    },
    failWith(status) {
      inventoryStatus = status;
    },
    reads: () => inventoryReads,
  };
}

test("detail drawer traps focus, isolates the background, and restores the trigger", async ({
  page,
}) => {
  await connect(page);
  await page.goto("/admin/inventory");
  const trigger = page.getByRole("button", { name: "View details for Mango" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Mango", exact: true });
  const close = dialog.getByRole("button", { name: "Close", exact: true });
  const last = dialog.getByRole("button", { name: "Remove from inventory" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(last).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  expect(
    await page.locator(".adm-main").evaluate((element) => element.inert),
  ).toBe(true);
  expect(
    await page.locator("body").evaluate((element) => element.style.overflow),
  ).toBe("hidden");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(
    await page.locator(".adm-main").evaluate((element) => element.inert),
  ).toBe(false);
  expect(
    await page.locator("body").evaluate((element) => element.style.overflow),
  ).toBe("");
  await trigger.click();
  await page
    .locator("[data-dialog-backdrop]")
    .click({ position: { x: 12, y: 12 } });
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("add drawer keeps keyboard focus inside and restores Add item", async ({
  page,
}) => {
  await connect(page);
  await page.goto("/admin/inventory");
  const trigger = page.getByRole("button", { name: "Add item +", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "ADD NEW ITEM" });
  const first = dialog.getByRole("button", { name: "Close", exact: true });
  const last = dialog.getByRole("button", { name: "Add item", exact: true });
  await expect(first).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(last).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(first).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

for (const action of ["Adjust stock", "Edit item"]) {
  test(`detail to ${action} restores the original inventory trigger`, async ({
    page,
  }) => {
    await connect(page);
    await page.goto("/admin/inventory");
    const trigger = page.getByRole("button", {
      name: "View details for Mango",
    });
    await trigger.click();
    await page
      .getByRole("dialog", { name: "Mango", exact: true })
      .getByRole("button", { name: action, exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toHaveCount(1);
    await expect(dialog.getByRole("button", { name: /Close/ })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(
      await dialog.evaluate((element) =>
        element.contains(document.activeElement),
      ),
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
}

test("a draft survives background refresh but is removed if access is denied", async ({
  page,
}) => {
  await page.clock.install();
  const api = await connect(page);
  await page.goto("/admin/inventory");
  await page.getByRole("button", { name: "Add item +", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "ADD NEW ITEM" });
  const name = dialog.getByRole("textbox", {
    name: "Flavor / product name",
    exact: true,
  });
  await name.fill("Unsaved draft flavor");
  api.setItems([makeItem({ onHand: 120, available: 95 })]);
  const initialReads = api.reads();
  await page.clock.fastForward(60000);
  await expect.poll(api.reads).toBeGreaterThan(initialReads);
  await expect(name).toHaveValue("Unsaved draft flavor");
  await expect(dialog).toBeVisible();
  api.failWith(503);
  const beforeTransientFailure = api.reads();
  await page.clock.fastForward(60000);
  await expect.poll(api.reads).toBeGreaterThan(beforeTransientFailure);
  await expect(name).toHaveValue("Unsaved draft flavor");
  await expect(dialog).toBeVisible();
  await expect(page.locator(".adm-refresh__status")).toContainText(
    "Refresh failed",
  );
  api.failWith(403);
  const beforeDenial = api.reads();
  await page.clock.fastForward(60000);
  await expect.poll(api.reads).toBeGreaterThan(beforeDenial);
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "View details for Mango" }),
  ).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText(
    "Could not load inventory",
  );
});

test("restock review includes zero-stock items without double-counting them", async ({
  page,
}) => {
  await connect(page, [
    makeItem({ id: "mango", available: 20 }),
    makeItem({
      id: "lime",
      name: "Lime",
      onHand: 0,
      reserved: 0,
      available: 0,
    }),
    makeItem({ id: "coconut", name: "Coconut", available: 80 }),
  ]);
  await page.goto("/admin/inventory");
  await expect(page.getByRole("alert")).toContainText(
    "2 FLAVORS NEED A TOP-UP",
  );
  await page.getByRole("button", { name: "Review low stock" }).click();
  await expect(
    page.getByRole("button", { name: "Low stock · 2" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "View details for Mango" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View details for Lime" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "View details for Coconut" }),
  ).toHaveCount(0);
});
