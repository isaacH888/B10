import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("sample admin screens work without login, cookies, or real API responses", async ({
  page,
  context,
}) => {
  const apiResponses = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.startsWith("/api/v1/")) {
      apiResponses.push(response);
    }
  });
  await page.goto("/admin/dashboard");
  await expect(
    page.getByRole("complementary", { name: "Sample preview" }),
  ).toContainText("Sample data");
  await expect(
    page.getByRole("region", { name: "New catering requests", exact: true }),
  ).toContainText("1");
  const nav = page.getByRole("navigation", { name: "Admin pages" });
  await nav.getByRole("link", { name: "Orders", exact: true }).click();
  const firstOrder = page.getByRole("row", { name: /^preview_order_001 / });
  await expect(firstOrder).toBeVisible();
  await firstOrder.getByRole("link", { name: "View details ↗" }).click();
  await expect(
    page.getByRole("heading", {
      name: /preview_order_001.*SAMPLE ELENA CRUZ/i,
    }),
  ).toBeVisible();
  await nav.getByRole("link", { name: "Calendar", exact: true }).click();
  await page
    .getByRole("button", {
      name: "Sample Avery Morgan, Full Service, 250 paletas, confirmed",
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("100 Example Street");
  await page.getByRole("button", { name: "Close event details" }).click();
  await nav.getByRole("link", { name: "Inventory", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "View details for Mango", exact: true }),
  ).toBeVisible();
  await expect(context.cookies()).resolves.toEqual([]);
  expect(errors).toEqual([]);
  expect(apiResponses.length).toBeGreaterThan(5);
  for (const response of apiResponses) {
    expect(response.headers()["x-admin-preview"]).toBe("sample-data");
    expect(response.headers()["set-cookie"]).toBeUndefined();
  }
});

test("preview blocks mutations and never falls through to real services", async ({
  request,
}) => {
  const before = await request.get("/api/v1/admin/inventory");
  const original = await before.json();
  for (const path of [
    "/admin/inventory",
    "/admin/login",
    "/admin/automation/google/connect",
  ]) {
    const response = await request.post(`/api/v1${path}`, { data: {} });
    expect(response.status()).toBe(403);
    expect((await response.json()).error.code).toBe("preview_read_only");
    expect(response.headers()["x-admin-preview"]).toBe("sample-data");
    expect(response.headers()["set-cookie"]).toBeUndefined();
  }
  const unknown = await request.get("/api/v1/admin/unknown-live-endpoint");
  expect(unknown.status()).toBe(404);
  expect(unknown.headers()["x-admin-preview"]).toBe("sample-data");
  const after = await request.get("/api/v1/admin/inventory");
  expect(await after.json()).toEqual(original);
});

test("preview exports only clearly marked sample records", async ({ page }) => {
  await page.goto("/admin/orders/preview_order_001");
  const response = page.waitForResponse((response) =>
    response.url().includes("/preview_order_001/export"),
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export summary" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("order-summary.csv");
  const exported = await response;
  expect(exported.headers()["x-admin-preview"]).toBe("sample-data");
  expect(await readFile(await file.path(), "utf8")).toContain(
    '"PREVIEW","preview_order_001","Sample Elena Cruz"',
  );
});

for (const width of [390, 1440]) {
  test(`sample dashboard fits a ${width}px viewport`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto("/admin/dashboard");
    await expect(
      page.getByRole("region", { name: "New catering requests", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`admin-preview-${width}.png`),
      fullPage: true,
    });
  });
}
