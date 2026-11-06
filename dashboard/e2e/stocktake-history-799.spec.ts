import { expect, test, type Page, type Route } from "playwright/test";

// Browser acceptance checks real Chromium UI/focus with mocked, read-only
// HTTP fixtures. Real bearer + restricted PG16 are proven independently.
const respond = (route: Route, data: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });

async function setup(page: Page, locale: "ar" | "en", reviewGranted: boolean) {
  const permissions = [
    "inventory.read", "catalog.read", "location.read",
    "stocktake.read", "stocktake.start", "stocktake.count",
    ...(reviewGranted ? ["stocktake.review"] : []),
  ];
  await page.addInitScript(({ locale }) => {
    const jwt = "x." + btoa(JSON.stringify({
      type: "refresh", sub: "7", company_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })) + ".x";
    localStorage.setItem("admin_token", "stocktake-history-browser-fixture");
    localStorage.setItem("refresh_token", jwt);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");
    localStorage.setItem("backoffice_user_id", "17");
    localStorage.setItem("driver_id", "7");
    localStorage.setItem("wanasah.language", locale);
    localStorage.setItem("inventory_active_tab:1", "stocktake");
    localStorage.setItem("inventory_selected_location:1", "11");
  }, { locale });
  await page.route("**/api/**", async route => {
    const uri = new URL(route.request().url());
    const path = uri.pathname.replace(/^\/api/, "");
    if (path === "/tenant/identity") return respond(route, {
      company_id: 1, company_name: "Stocktake History Browser Fixture",
      company_code: "STK", currency_code: "JOD", timezone: "Asia/Amman",
      country_id: null, country_name: null, display_location: "Amman",
    });
    if (path === "/inventory/access/me") return respond(route, {
      company_id: 1, principal_id: 7, backoffice_user_id: 17,
      is_company_owner: false, location_id: Number(uri.searchParams.get("location_id")) || null,
      permissions: [], any_permissions: permissions, location_permissions: permissions,
    });
    if (path === "/inventory/access/locations/capabilities") return respond(route, {
      locations: { "11": permissions },
    });
    if (path === "/warehouse/locations" || path === "/warehouse/locations/selection") return respond(route, {
      items: [{ id: 11, name: "Main Warehouse", code: "WH-11" }],
      next_cursor: null, has_more: false, total: 1,
      selected: { id: 11, name: "Main Warehouse", code: "WH-11" },
    });
    if (path === "/warehouse/setup-status") return respond(route, {
      warehouse_ready: true, active_warehouse_count: 1,
      accessible_warehouse_count: 1, can_create: false,
    });
    if (path === "/warehouse/status") return respond(route, {
      status: "ACTIVE", stocktake_session_id: null,
      stocktake_reference: null, stocktake_status: null,
    });
    if (path === "/warehouse/unified/stocktakes/active") return respond(route, {
      items: [], next_cursor: null, has_more: false, total: 0,
    });
    if (path === "/warehouse/unified/stocktakes/history") {
      if (uri.searchParams.get("location_id") !== "11") return respond(route, { detail: "Wrong warehouse" }, 403);
      return respond(route, {
        items: [
          { id: 81, reference_number: "STK-HISTORY-81", status: "CANCELLED",
            stocktake_type: "CYCLE_COUNT", location_id: 11,
            scope_product_name: "Chickpeas 750 g", scope_batch_number: "REAL-LOT-9",
            created_at: "2026-11-06T07:00:00Z", finished_at: "2026-11-06T09:00:00Z",
            started_by_name: "Original operator", counted_by_name: "Independent counter",
            attempt_number: 2, approved_by_name: null, cancelled_by_name: "Supervisor",
            cancellation_reason: "Discrepancy confirmed", cancelled_after_count: true },
          { id: 82, reference_number: "STK-HISTORY-82", status: "POSTED",
            stocktake_type: "FULL_COUNT", location_id: 11,
            scope_product_name: null, scope_batch_number: null,
            created_at: "2026-11-06T05:00:00Z", finished_at: "2026-11-06T06:00:00Z",
            started_by_name: "Original operator", counted_by_name: "Counter",
            attempt_number: 1, approved_by_name: "Supervisor", cancelled_by_name: null,
            cancellation_reason: null, cancelled_after_count: false },
        ], next_cursor: null, has_more: false,
      });
    }
    if (path === "/warehouse/unified/stocktakes/history/81") return respond(route, {
      session: {
        id: 81, reference_number: "STK-HISTORY-81", status: "CANCELLED",
        stocktake_type: "CYCLE_COUNT", location_id: 11,
        created_at: "2026-11-06T07:00:00Z", finished_at: "2026-11-06T09:00:00Z",
        snapshot_cutoff_at: "2026-11-06T07:00:00Z",
        scope_product_name: "Chickpeas 750 g", scope_batch_number: "REAL-LOT-9",
        cancellation_reason: "Discrepancy confirmed", notes: "Physical audit note",
        cancelled_after_count: true, adjustment_movement_count: 0,
      },
      attempts: { items: [
        { id: 92, attempt_number: 2, counted_by_name: "Independent counter",
          submitted_at: "2026-11-06T08:30:00Z", recount_reason: "Second count",
          requires_independent_recount: false, recount_of_attempt_id: 91 },
        { id: 91, attempt_number: 1, counted_by_name: "Original operator",
          submitted_at: "2026-11-06T07:30:00Z", recount_reason: null,
          requires_independent_recount: true, recount_of_attempt_id: null },
      ], next_cursor: null, has_more: false },
      audit: { items: [
        { id: 77, action_type: "STOCKTAKE_CANCELLED", actor_name: "Supervisor",
          timestamp: "2026-11-06T09:00:00Z", details: { reason: "Discrepancy confirmed" } },
      ], next_cursor: null, has_more: false },
    });
    if (path === "/warehouse/unified/stocktakes/history/81/attempts/92/lines") return respond(route, {
      items: [{ id: 902, product_name: "Chickpeas 750 g",
        batch_number: "REAL-LOT-9", stock_status: "QUARANTINED",
        line_origin: "SNAPSHOT", base_uom_name: "Each",
        expected_quantity: "12", actual_quantity: "7", variance_quantity: "-5" }],
      next_cursor: null, has_more: false,
    });
    if (path === "/warehouse/unified/stocktakes/history/81/attempts/91/lines") return respond(route, {
      items: [{ id: 901, product_name: "Chickpeas 750 g",
        batch_number: "REAL-LOT-9", stock_status: "QUARANTINED",
        line_origin: "SNAPSHOT", base_uom_name: "Each",
        expected_quantity: "12", actual_quantity: "8", variance_quantity: "-4" }],
      next_cursor: null, has_more: false,
    });
    if (path === "/warehouse/inventory/summary") return respond(route, { stock_total: 0, alert_count: 0 });
    if (path === "/warehouse/inventory/families") return respond(route, { items: [], next_cursor: null, has_more: false });
    if (path === "/warehouse/unified/transfers") return respond(route, { items: [], next_cursor: null, has_more: false, total: 0 });
    if (path === "/warehouse/ledger/cursor") return respond(route, { items: [], next_cursor: null, has_more: false, total: 0, available_types: [] });
    return respond(route, { detail: { code: "STOCKTAKE_799_UNMOCKED", message: path } }, 404);
  });
}

for (const lang of ["ar", "en"] as const) {
  for (const size of [
    { title: "desktop", width: 1440, height: 900 },
    { title: "phone", width: 390, height: 844 },
  ]) {
    test(lang + " " + size.title + " immutable terminal history Chromium", async ({ page }, testInfo) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await setup(page, lang, true);
      await page.goto("/inventory");
      const trigger = page.getByRole("button", { name: lang === "ar" ? "سجل الجرد" : "Stocktake history" });
      await expect(trigger).toBeVisible();
      await trigger.click();
      const dialog = page.getByRole("dialog", { name: lang === "ar" ? "سجل الجرد" : "Stocktake history" });
      await expect(dialog).toBeVisible();
      await expect(dialog.locator('[role="listitem"]')).toHaveCount(2);
      await expect(dialog.getByText("STK-HISTORY-81")).toBeVisible();
      await expect(dialog.getByText("STK-HISTORY-82")).toBeVisible();
      await expect(dialog.getByText(lang === "ar" ? "تم الإلغاء بعد تثبيت العد" : "Cancelled after count submission")).toBeVisible();
      await expect(dialog.getByText("12 Each")).toHaveCount(0);
      await dialog.getByRole("button", { name: lang === "ar" ? "التفاصيل" : "Details" }).first().click();
      await expect(dialog.getByText("12 Each")).toBeVisible();
      await expect(dialog.getByText("7 Each")).toBeVisible();
      await expect(dialog.getByText("REAL-LOT-9").first()).toBeVisible();
      await expect(dialog.getByText("Discrepancy confirmed").first()).toBeVisible();
      await dialog.screenshot({ path: testInfo.outputPath("history-review.png") });
      await dialog.getByRole("button", {
        name: (lang === "ar" ? "محاولة العد" : "Count attempt") + " #1 · Original operator",
      }).click();
      await expect(dialog.getByText("8 Each")).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(trigger).toBeFocused();
      const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }));
      expect(width.page).toBeLessThanOrEqual(width.viewport + 1);
    });
    test(lang + " " + size.title + " count-only cannot reveal expected quantities", async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await setup(page, lang, false);
      await page.goto("/inventory");
      await page.getByRole("button", { name: lang === "ar" ? "سجل الجرد" : "Stocktake history" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByText("STK-HISTORY-81")).toBeVisible();
      await expect(dialog.getByRole("button", { name: lang === "ar" ? "التفاصيل" : "Details" }).first()).toBeDisabled();
      await expect(dialog.getByText("12 Each")).toHaveCount(0);
    });
  }
}
