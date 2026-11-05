import { expect, test, type Page, type Route } from "playwright/test";

// #782 layout-only Chromium fixture: authorized HTTP mock, NOT PG16 business proof.
const permissions = [
  "inventory.read", "catalog.read", "location.read", "ledger.read",
  "stocktake.read", "stocktake.start", "stocktake.count",
  "stocktake.review", "stocktake.cancel", "stocktake.recount", "stocktake.approve",
];
const warehouse = (id: number) => ({
  id, name: id === 11 ? "Main Warehouse" : "Second Warehouse", code: `WH-${id}`,
});
const session = (id: number, kind: "CYCLE_COUNT" | "FULL_COUNT") => ({
  id, reference_number: `STK-0000${id}`, stocktake_type: kind,
  status: "COUNTING", location_id: 11,
  // Parallel cycle sessions must have disjoint product scopes; the backend
  // rejects overlapping whole-product inventory locks with 409.
  scope_product_variant_id: kind === "CYCLE_COUNT" ? (id === 78 ? 119 : 118) : null,
  scope_product_name: kind === "CYCLE_COUNT"
    ? (id === 78 ? "Oats 1.5 kg" : "Chickpeas 750 g") : null,
  scope_batch_id: null, scope_batch_number: null,
  related_work_session_id: null, started_by: 17,
  started_by_name: "Warehouse Operator",
  pending_independent_recount_required: false,
  snapshot_cutoff_at: "2026-11-05T08:00:00Z",
  created_at: "2026-11-05T08:00:00Z",
  updated_at: "2026-11-05T08:00:00Z",
});
function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}
async function setup(page: Page, locale: "ar" | "en") {
  await page.addInitScript(language => {
    const jwt = "x." + btoa(JSON.stringify({
      type: "refresh", sub: "7", company_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })) + ".x";
    localStorage.setItem("admin_token", "stocktake-shell-782-browser-fixture");
    localStorage.setItem("refresh_token", jwt);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");
    localStorage.setItem("backoffice_user_id", "17");
    localStorage.setItem("driver_id", "7");
    localStorage.setItem("wanasah.language", language);
    localStorage.setItem("inventory_active_tab:1", "stocktake");
    localStorage.setItem("inventory_selected_location:1", "11");
  }, locale);
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, "");
    const location = Number(url.searchParams.get("location_id") || 11);
    if (path === "/tenant/identity") return json(route, {
      company_id: 1, company_name: "Shell Fixture",
      company_code: "STK", currency_code: "JOD",
      timezone: "Asia/Amman", country_id: null, country_name: null,
      display_location: "Amman",
    });
    if (path === "/inventory/access/me") return json(route, {
      company_id: 1, principal_id: 7, backoffice_user_id: 17,
      is_company_owner: true,
      location_id: url.searchParams.has("location_id") ? location : null,
      permissions: [], any_permissions: permissions, location_permissions: permissions,
    });
    if (path === "/warehouse/locations/selection" || path === "/warehouse/locations") {
      const selectedId = Number(url.searchParams.get("selected_location_id") || 11);
      return json(route, {
        items: [warehouse(11), warehouse(12)],
        selected: warehouse(selectedId), has_more: false,
        next_cursor: null, total: 2,
      });
    }
    if (path === "/warehouse/setup-status") return json(route, {
      warehouse_ready: true, active_warehouse_count: 2,
      accessible_warehouse_count: 2, can_create: false,
    });
    if (path === "/inventory/access/locations/capabilities") return json(route, {
      locations: { "11": permissions, "12": permissions },
    });
    if (path === "/warehouse/status") return json(route, {
      status: "ACTIVE", stocktake_session_id: null,
      stocktake_reference: null, stocktake_status: null,
    });
    if (path === "/warehouse/unified/stocktakes/active") {
      const items = location === 11 ? [session(77, "CYCLE_COUNT"), session(78, "CYCLE_COUNT")] : [];
      return json(route, { items, total: items.length, next_cursor: null, has_more: false });
    }
    const context = path.match(/^\/warehouse\/unified\/stocktake\/(77|78)\/context$/);
    if (context) return json(route, {
      session_id: Number(context[1]), stocktake_type: "CYCLE_COUNT",
      status: "COUNTING", location_id: 11, related_work_session_id: null,
      source_location_id: 11,
    });
    const countScope = path.match(/^\/warehouse\/unified\/stocktake\/(77|78)\/count-sheet$/);
    if (countScope) {
      const second = countScope[1] === "78";
      return json(route, [
        { product_variant_id: second ? 119 : 118, batch_id: second ? 52 : 51,
          stock_status: "AVAILABLE",
          product_name: second ? "Oats 1.5 kg" : "Chickpeas 750 g",
          batch_number: second ? "TRUE-LOT-52" : "TRUE-LOT-51",
          expiry_date: "2027-01-17", base_uom_id: 7, base_uom_code: "EACH",
          base_uom_name: "Each", quantity_scale: 0, quantity_step: "1" },
      ]);
    }
    if (path === "/warehouse/inventory/summary") return json(route, { stock_total: 1, alert_count: 0 });
    if (path === "/warehouse/inventory/cursor") return json(route, { items: [], next_cursor: null, has_more: false, total: 0 });
    if (path === "/warehouse/inventory/families") return json(route, { items: [], next_cursor: null, has_more: false });
    if (path === "/warehouse/ledger/cursor") return json(route, { items: [], next_cursor: null, has_more: false, total: 0, available_types: [] });
    return json(route, { detail: { code: "SHELL_FIXTURE_UNMOCKED", message: path } }, 404);
  });
}

for (const locale of ["ar", "en"] as const) {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 900 },
    { name: "phone", width: 390, height: 844 },
  ]) {
    test(`#782 shell ${locale} ${viewport.name}: one selector, compact sessions, reentry and location switch`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await setup(page, locale);
      await page.goto("/inventory");
      const stocktake = page.locator(".inventory-stocktake");
      await expect(stocktake).toBeVisible();
      const toolbar = stocktake.locator("[data-stocktake-toolbar='true']");
      await expect(toolbar).toBeVisible();
      const selector = toolbar.locator("select.inventory-location-select");
      await expect(selector).toHaveCount(1);
      await expect(selector).toHaveValue("11");
      await expect(page.locator(".inventory-shared-context-row:visible")).toHaveCount(0);
      await expect(toolbar.getByRole("button", { name: locale === "ar" ? "جرد صنف" : "Count product" })).toBeVisible();
      await expect(toolbar.getByRole("button", { name: locale === "ar" ? "تحديث الجلسات" : "Refresh sessions" })).toBeVisible();

      await expect(toolbar.locator(".inventory-location-label")).toHaveText(
        locale === "ar" ? "المستودع:" : "Warehouse:",
      );
      const sessionsTrigger = toolbar.locator('[data-stocktake-sessions-trigger="true"]');
      await expect(sessionsTrigger).toHaveText(locale === "ar" ? "الجلسات (٢)" : "Sessions (2)");
      await expect(page.getByRole("dialog")).toHaveCount(0);

      const door = stocktake.getByRole("button", {
        name: locale === "ar" ? "إغلاق المستودع وبدء الجرد الشامل" : "Lock warehouse and start full stocktake",
      });
      await expect(door).toBeVisible();
      await expect(door.locator(".animate-spin")).toHaveCount(2); // Original intact door.
      await sessionsTrigger.click();
      const drawer = page.getByRole("dialog", {
        name: locale === "ar" ? "جلسات الجرد النشطة" : "Active stocktake sessions",
      });
      await expect(drawer).toBeVisible();
      await expect(drawer.locator("[role='listitem']")).toHaveCount(2);
      await expect(door).toBeAttached(); // Modal overlays, never replaces the work area.
      await page.keyboard.press("Escape");
      await expect(drawer).toHaveCount(0);
      await expect(sessionsTrigger).toBeFocused();
      await sessionsTrigger.click();
      await drawer.locator("[role='listitem']").last().getByRole("button", {
        name: locale === "ar" ? "فتح" : "Open", exact: true,
      }).click();
      await expect(drawer).toHaveCount(0);
      await expect(stocktake.locator("[data-stocktake-workspace='counting']")).toBeVisible();
      await expect(door).toHaveCount(0); // No giant idle door behind active count.
      await expect(stocktake.locator("[data-stocktake-workspace] input[data-stocktake-count-input='true']:visible")).toHaveCount(1);

      // Same-scope tab reentry must retain the active session workspace.
      await page.locator("nav.inventory-top-dock__dock [role='tab']").first().click();
      await page.getByRole("tab", {
        name: locale === "ar" ? "جرد وتسوية" : "Stocktake & adjustment",
      }).click();
      await expect(stocktake.locator("[data-stocktake-workspace='counting']")).toBeVisible();
      await expect(stocktake.locator("[data-stocktake-toolbar='true'] select.inventory-location-select")).toHaveCount(1);

      // Scope changes must not leak A's sessions or draft into warehouse B.
      await selector.selectOption("12");
      await expect(stocktake.locator("[data-stocktake-toolbar='true'] select.inventory-location-select")).toHaveValue("12");
      await expect(stocktake.locator("[data-stocktake-workspace='idle']")).toBeVisible();
      await expect(stocktake.locator("[data-stocktake-toolbar='true'] select.inventory-location-select")).toHaveCount(1);
      await expect(sessionsTrigger).toHaveText(locale === "ar" ? "الجلسات (٠)" : "Sessions (0)");
      await sessionsTrigger.click();
      const emptyDrawer = page.getByRole("dialog", {
        name: locale === "ar" ? "جلسات الجرد النشطة" : "Active stocktake sessions",
      });
      await expect(emptyDrawer.locator("[role='listitem']")).toHaveCount(0);
      await page.keyboard.press("Escape");
      await expect(emptyDrawer).toHaveCount(0);
      const geometry = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
      expect(geometry.document).toBeLessThanOrEqual(geometry.viewport + 2);
      await page.screenshot({ path: test.info().outputPath(`stocktake-shell-${locale}-${viewport.name}.png`), fullPage: true });
    });
  }
}
