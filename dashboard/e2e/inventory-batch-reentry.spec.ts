import { expect, test, type Page, type Route } from "playwright/test";
import { installUxApi, seedUx } from "./live-stock-ux-closure.fixtures";

const WAREHOUSE_A = 11;
const WAREHOUSE_B = 12;
const tabLabels = {
  en: { live: "Live stock", batches: "Batches & expiry" },
  ar: { live: "الرصيد الحي", batches: "التشغيلات والصلاحية" },
} as const;
const fulfill = (route: Route, data: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
const gotoInventory = async (page: Page) => {
  await page.goto("/inventory");
  await expect(page.getByRole("tablist")).toBeVisible();
};
const selectedTab = async (page: Page, name: string) => {
  await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
};


// IT-03/IT-04: Chromium assertions against the actual Inventory shell and
// Batches UI. A route is deliberately held to inspect the *intermediate*
// painted frame rather than checking only the settled result.
const reentryBatch = (id: number) => ({
  batch_id: id, batch_number: `IT-LOT-${id}`, production_date: null, expiry_date: null,
  disposition: "RELEASED", disposition_reason: null, disposition_revision: 1,
  allowed_disposition_targets: [], days_to_expiry: null,
  product_id: id, product_variant_id: id, product_name: `IT Product ${id}`,
  sku: `IT-${id}`, family_name: "IT Family", lot_control_mode: "OPTIONAL",
  expiry_control_mode: "OPTIONAL", minimum_remaining_shelf_life_days: 0,
  sellability_state: "SELLABLE", sellability_reason_codes: [],
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each",
  display_factor_to_base: "1", quantity_scale: 0, quantity_step: "1",
  on_hand_quantity: "8", reserved_quantity: "0", available_for_sale_quantity: "8",
  unavailable_quantity: "0", available_status_quantity: "8",
  quarantined_quantity: "0", blocked_quantity: "0", recalled_quantity: "0",
  damaged_quantity: "0", disposal_pending_quantity: "0",
});
const reentryPage = (locationId: number) => ({
  location_id: locationId, as_of_date: "2026-11-02",
  items: [reentryBatch(locationId === WAREHOUSE_A ? 41 : 42)],
  next_cursor: null, has_more: false,
});
const reentrySummary = (locationId: number) => ({
  location_id: locationId, as_of_date: "2026-11-02",
  total_relevant_batches: 1, expired_count: 0, expiring_soon_count: 0,
  non_sellable_count: 0, quarantined_count: 0, blocked_count: 0,
  recalled_count: 0, damaged_or_disposal_attention_count: 0,
});

for (const { locale, width } of [
  { locale: "en", width: 1440 },
  { locale: "ar", width: 1440 },
  { locale: "en", width: 390 },
  { locale: "ar", width: 390 },
] as const) {
  test(`IT03/IT04 ${locale} ${width}: real batch reentry stays scoped, busy and mutation-safe`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installUxApi(page, 1, { allowOtherInventoryReads: true });
    let readsA = 0;
    const heldA: Route[] = [];
    await page.route("**/api/warehouse/inventory/batches/**", (route) => {
      const url = new URL(route.request().url());
      const location = Number(url.searchParams.get("location_id"));
      if (location === WAREHOUSE_A && url.pathname.endsWith("/cursor")) {
        readsA += 1;
        if (readsA > 1) { heldA.push(route); return; }
      }
      const result = url.pathname.endsWith("/cursor") ? reentryPage(location) : reentrySummary(location);
      return fulfill(route, result);
    });
    await seedUx(page, locale, "light", "batches");
    await gotoInventory(page);
    await selectedTab(page, tabLabels[locale].batches);
    const batchPanel = page.locator('[data-batch-panel-active="true"]');
    const visibleBatch = (id: number) =>
      batchPanel.locator("tr:visible, article:visible").filter({ hasText: `IT-LOT-${id}` });

    await expect(visibleBatch(41)).toHaveCount(1);
    await expect(batchPanel.locator("section[aria-busy='false']").first()).toBeVisible();
    const readsBeforeLeave = readsA;
    await page.getByRole("tab", { name: tabLabels[locale].live, exact: true }).click();
    await selectedTab(page, tabLabels[locale].live);
    await expect(page.locator(".inventory-batches-view")).toBeHidden();
    expect(readsA).toBe(readsBeforeLeave); // No background batch fetching.

    await page.getByRole("tab", { name: tabLabels[locale].batches, exact: true }).click();
    await selectedTab(page, tabLabels[locale].batches);
    await expect.poll(() => readsA).toBe(readsBeforeLeave + 1);
    await expect(visibleBatch(41)).toHaveCount(1); // No empty repaint.
    await expect(batchPanel.locator('section[aria-busy="true"]').first()).toBeVisible();
    await expect(batchPanel.getByRole("button", {
      name: locale === "ar" ? "عرض تفاصيل التشغيلة" : "View batch details",
    }).first()).toBeDisabled();

    // Change the authorized Warehouse while its old HTTP response is held.
    await page.getByLabel(locale === "ar" ? "المستودع المحدد" : "Selected warehouse")
      .selectOption(String(WAREHOUSE_B));
    await expect(visibleBatch(41)).toHaveCount(0);
    await expect(visibleBatch(42)).toHaveCount(1);
    await Promise.allSettled(heldA.map((route) => fulfill(route, reentryPage(WAREHOUSE_A))));
    await expect(visibleBatch(41)).toHaveCount(0);
    await expect(visibleBatch(42)).toHaveCount(1);
  });
}

test("IT04 browser: revocation of batch access hides previously admitted LOT immediately", async ({ page }) => {
  await installUxApi(page, 1, { allowOtherInventoryReads: true });
  let denied = false;
  await page.route("**/api/inventory/access/me*", (route) =>
    denied ? fulfill(route, { detail: { code: "FORBIDDEN" } }, 403) : route.fallback());
  await page.route("**/api/warehouse/inventory/batches/**", (route) => {
    const url = new URL(route.request().url());
    if (denied) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
    const location = Number(url.searchParams.get("location_id"));
    return fulfill(route, url.pathname.endsWith("/cursor") ? reentryPage(location) : reentrySummary(location));
  });
  await seedUx(page, "en", "light", "batches");
  await gotoInventory(page);
  await expect(page.locator(".inventory-batches-view").getByText("IT-LOT-41").first()).toBeVisible();
  denied = true;
  await page.getByRole("button", { name: "Refresh batches" }).click();
  await expect(page.getByText("IT-LOT-41")).toHaveCount(0);
  await expect(page.locator(".inventory-batches-view button", { hasText: "View batch details" })).toHaveCount(0);
});
