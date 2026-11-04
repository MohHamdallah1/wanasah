import { expect, test, type Route } from "playwright/test";
import { installUxApi, seedUx } from "./live-stock-ux-closure.fixtures";

const send = (r: Route, data: unknown, status = 200) =>
  r.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
const item = (id: number, family = "Original Family") => ({
  batch_id: id, batch_number: "LOT-" + id, production_date: null, expiry_date: null,
  disposition: "RELEASED", disposition_reason: null, disposition_revision: 1,
  allowed_disposition_targets: [], days_to_expiry: null,
  product_id: id, product_variant_id: id, product_name: "Product " + id,
  sku: "SKU-" + id, family_name: family, lot_control_mode: "OPTIONAL",
  expiry_control_mode: "OPTIONAL", minimum_remaining_shelf_life_days: 0,
  sellability_state: "SELLABLE", sellability_reason_codes: [],
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "حبة",
  display_uom_id: 2, display_uom_code: "PACK", display_uom_name: "باكيت",
  display_factor_to_base: "8", quantity_scale: 0, quantity_step: "1",
  on_hand_quantity: "12", reserved_quantity: "0", available_for_sale_quantity: "12",
  unavailable_quantity: "0", available_status_quantity: "12",
  quarantined_quantity: "0", blocked_quantity: "0", recalled_quantity: "0",
  damaged_quantity: "0", disposal_pending_quantity: "0",
});
for (const locale of ["en", "ar"] as const) for (const width of [1440, 390] as const) {
  test("Batches selector owner " + locale + " " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installUxApi(page, 1, { allowOtherInventoryReads: true });
    let batchReads = 0, productReads = 0, failOnce = true;
    await page.route("**/api/warehouse/inventory/batch-products?*", r => {
      productReads++;
      const u = new URL(r.request().url());
      if (u.searchParams.get("search") === "Remote Product" && failOnce) {
        failOnce = false;
        return send(r, { detail: { code: "TEST_FAILURE" } }, 500);
      }
      return send(r, { items: [{
        id: 990, name: "Remote Product", sku: "R-990", family_name: "Remote",
        base_uom_code: "EACH", display_uom_code: "PACK",
        display_factor_to_base: "8", currency_code: "JOD",
      }], next_cursor: null, has_more: false });
    });
    await page.route("**/api/warehouse/inventory/batches/**", r => {
      const u = new URL(r.request().url());
      const location_id = Number(u.searchParams.get("location_id"));
      if (u.pathname.endsWith("/summary")) return send(r, {
        location_id, as_of_date: "2026-11-02", total_relevant_batches: 2,
        expired_count: 0, expiring_soon_count: 0, non_sellable_count: 0,
        quarantined_count: 0, blocked_count: 0, recalled_count: 0,
        damaged_or_disposal_attention_count: 0,
      });
      batchReads++;
      return send(r, { location_id, as_of_date: "2026-11-02",
        items: [u.searchParams.get("search") === "Target Family"
          ? item(901, "Target Family") : item(41)],
        next_cursor: null, has_more: false });
    });
    await seedUx(page, locale, "light", "batches");
    await page.goto("/inventory");
    const panel = page.locator('[data-batch-panel-active="true"]');
    const visibleRow = panel.locator("tr:visible, article:visible").filter({ hasText: "LOT-41" });
    await expect(visibleRow).toHaveCount(1);
    const toolbar = panel.locator('[data-batches-compact-toolbar="true"]');
    await expect(toolbar.getByRole("searchbox", { name: locale === "ar" ?
      "ابحث بالمنتج أو SKU أو رقم التشغيلة..." : "Search product, SKU, or lot number..." })).toBeVisible();
    await expect(toolbar.getByRole("combobox", { name: locale === "ar" ? "المستودع" : "Warehouse" })).toBeVisible();
    await expect(toolbar.locator('[data-batches-loaded-count="true"]')).toContainText("1");
    await expect(toolbar.getByRole("button", { name: locale === "ar" ? "تحديث" : "Refresh", exact: true })).toBeVisible();
    await expect(panel.getByRole("spinbutton", { name: locale === "ar" ?
      "عدد أيام التنبيه قبل انتهاء الصلاحية" : "Expiry warning window in days" })).toHaveValue("30");
    await expect(page.locator(".inventory-shared-context-row")).toHaveCount(0);
    // Regression: the legacy two-column Batches CSS pushed the only
    // list into a 19rem-wide RTL grid track and left most of the page empty.
    // Check the real rendered geometry for Arabic/English, desktop/phone.
    const batchGeometry = await panel.locator(".inventory-batches-view").evaluate(view => {
      const list = view.firstElementChild as HTMLElement | null;
      return {
        display: getComputedStyle(view).display,
        viewportWidth: view.getBoundingClientRect().width,
        listWidth: list?.getBoundingClientRect().width ?? 0,
      };
    });
    expect(batchGeometry.display).toBe("block");
    expect(batchGeometry.viewportWidth).toBeGreaterThan(0);
    expect(batchGeometry.listWidth).toBeGreaterThan(batchGeometry.viewportWidth * 0.90);
    await panel.getByText(locale === "ar" ? "توضيح الأرقام" : "About these counts", { exact: true }).click();
    await expect(panel.getByText(new RegExp(locale === "ar" ? "هذا الملخص يتبع" : "This summary follows"))).toBeVisible();
    await expect(visibleRow.locator('[data-commercial-quantity="true"]').first().locator('[data-quantity-number]')).toHaveText(["1", "4"]);
    // One combined selector per family/product, with lazy authorized discovery.
    const familyLabel = locale === "ar" ? "العائلة" : "Family";
    const productLabel = locale === "ar" ? "المنتج" : "Product";
    const familyPicker = panel.getByRole("combobox", { name: familyLabel, exact: true });
    const productPicker = panel.getByRole("combobox", { name: productLabel, exact: true });
    await expect(panel.getByRole("searchbox")).toHaveCount(1); // Global batch search only when menus are closed.
    await familyPicker.click();
    await page.getByRole("searchbox", { name: locale === "ar" ?
      "ابحث عن عائلة لها تشغيلات في المستودع" : "Search families with batches in this warehouse" }).fill("Target Family");
    await expect(page.getByRole("option", { name: "Target Family" })).toHaveAttribute("data-choice-id", "901");
    await page.getByRole("option", { name: "Target Family" }).click();
    await expect(familyPicker).toHaveAttribute("aria-expanded", "false");
    await expect.poll(() => batchReads).toBeGreaterThan(1);
    await productPicker.click();
    await page.getByRole("searchbox", { name: locale === "ar" ?
      "ابحث عن منتج له تشغيلات في المستودع" : "Search products with batches in this warehouse" }).fill("Remote Product");
    await page.getByRole("button", { name: locale === "ar" ? "إعادة محاولة الخيارات" : "Retry options" }).click();
    await expect(page.getByRole("option", { name: "Remote Product · R-990" })).toHaveAttribute("data-choice-id", "990");
    await page.getByRole("option", { name: "Remote Product · R-990" }).click();
    await expect(familyPicker).toContainText("Target Family");
    await expect(productPicker).toContainText("Remote Product");
    await panel.getByRole("combobox", { name: locale === "ar" ? "الترتيب" : "Sort" }).selectOption("PRODUCT_ASC");
    await panel.getByRole("combobox", { name: locale === "ar" ? "الصلاحية" : "Expiry" }).selectOption("EXPIRED");
    await page.screenshot({ path: "node_modules/.cache/batches-selector-owner/" + locale + "-" + width + "-filters.png", fullPage: true });
    const live = locale === "ar" ? "الرصيد الحي" : "Live stock";
    const batches = locale === "ar" ? "التشغيلات والصلاحية" : "Batches & expiry";
    await page.getByRole("tab", { name: live, exact: true }).click();
    const hiddenReads = productReads;
    await page.waitForTimeout(350);
    expect(productReads).toBe(hiddenReads);
    await page.getByRole("tab", { name: batches, exact: true }).click();
    await expect(panel).toBeVisible();
    await page.screenshot({ path: "node_modules/.cache/batches-selector-owner/" + locale + "-" + width + "-reentry.png", fullPage: true });
  });
}
