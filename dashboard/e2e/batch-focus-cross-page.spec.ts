import { expect, test } from "playwright/test";

import { batchFocusPayload, batchSource, inventoryReadAccess } from "../src/test/fixtures/batchFocus";

const productPage = {
  currency_code: "JOD",
  pricing_visible: false,
  items: [
    {
      id: 118,
      product_id: 118,
      name: "Browser quality product",
      family_name: "Quality fixtures",
      sku: "QUALITY-118",
      units_per_package: 6,
      legacy_packs_per_carton: 1,
      base_uom_id: 7,
      base_uom_code: "EACH",
      package_uom_id: 8,
      package_uom_code: "BOX",
      currency_code: "JOD",
      package_price: null,
      unit_price: null,
      unit_barcode: null,
      package_barcode: null,
      package_uses_base_barcode: false,
      version: 3,
      lot_control_mode: "REQUIRED",
      expiry_control_mode: "REQUIRED",
      lifecycle_status: "ACTIVE",
      operational_hold: "NONE",
      batch_restrictions: {
        schema_version: 1,
        scope: "COMPANY",
        affected_batch_count: 1,
        affected_on_hand_quantity: "10.000000",
        quantity_unit: "BASE_STOCK_UNIT",
        counts_by_disposition: { QUARANTINED: 1, BLOCKED: 0, RECALLED: 0 },
        representative_reason: {
          selection: "LOWEST_BATCH_ID_WITH_CURRENT_REASON",
          batch_id: 41,
          disposition: "QUARANTINED",
          disposition_revision: 3,
          disposition_reason: "Saved inspection reason",
        },
      },
      simple_compatible: true,
    },
  ],
  next_cursor: null,
  has_more: false,
};

for (const locale of ["en", "ar"] as const) {
  test(`${locale}: Products warning opens authoritative batch workspace in the browser`, async ({ page }) => {
    const calls: string[] = [];
    const unexpected: string[] = [];
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace(/^\/api/, "");
      calls.push(path);
      const payload = path === "/inventory/access/me" ? inventoryReadAccess(true)
        : path === "/simple-products" ? productPage
        : path === "/simple-products/summary" ? {
            schema_version: 2, company_id: 1, total: 1, families: 1, available: 1, stopped: 0, archived: 0,
          }
        : path === "/simple-products/tracking/defaults" ? {
            lot_control_mode: "REQUIRED", expiry_control_mode: "REQUIRED",
            lot_control_source: "COMPANY", expiry_control_source: "COMPANY",
          }
        : path === "/simple-products/package-uoms" ? {
            items: [{ id: 8, code: "BOX" }],
          }
        : path === "/warehouse/batches/41/stock-sources" ? batchFocusPayload([
            batchSource(11, "Warehouse A"),
            batchSource(13, "Vehicle 13", "VEHICLE"),
          ])
        : path === "/tenant/identity" ? {
            company_id: 1, company_name: "Browser fixture company", company_code: "FIXTURE",
            currency_code: "JOD", timezone: "Asia/Amman", country_id: null, country_name: null,
            display_location: "Fixture",
          }
        : null;
      if (request.method() !== "GET" || payload === null) {
        unexpected.push(`${request.method()} ${path}`);
        return route.fulfill({ status: 403, json: { code: "TEST_UNEXPECTED_REQUEST", context: {}, request_id: "browser-cross-page" } });
      }
      return route.fulfill({ json: payload });
    });

    await page.addInitScript((language) => {
      const refresh = `test.${btoa(JSON.stringify({ type: "refresh", sub: "7", company_id: 1, exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`;
      localStorage.setItem("admin_token", "read-only-browser-fixture");
      localStorage.setItem("refresh_token", refresh);
      localStorage.setItem("company_id", "1");
      localStorage.setItem("driver_id", "7");
      localStorage.setItem("inventory_selected_location:1", "999");
      localStorage.setItem("wanasah.language", language);
    }, locale);

    await page.goto("/products");
    await expect(page.getByText("Browser quality product", { exact: true })).toBeVisible();
    const warning = page.getByRole("button").filter({ hasText: "Saved inspection reason" });
    await expect(warning).toHaveCount(1);
    await warning.click();

    await expect(page).toHaveURL(/\/inventory$/);
    await expect(page.getByRole("heading", { name: "LOT-41", exact: true })).toBeVisible();
    const workspace = page.locator('section[aria-labelledby="batch-focus-heading"]');
    await expect(workspace).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(workspace.getByText("Warehouse A", { exact: true }).last()).toBeVisible();
    await expect(workspace.getByText("Vehicle 13", { exact: true }).last()).toBeVisible();
    await expect(page.locator("#batch-focus-heading")).toBeFocused();
    expect(await page.evaluate(() => history.state.usr)).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem("inventory_selected_location:1"))).toBe("999");
    expect(calls.filter((path) => path === "/warehouse/batches/41/stock-sources")).toHaveLength(1);
    expect(unexpected).toEqual([]);
  });
}
