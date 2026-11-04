import { expect, test, type Page, type Route } from "playwright/test";

// Issue #776: screenshot-only, mocked read fixture. Not real PG16 business acceptance.
const permissions = [
  "inventory.read", "catalog.read", "location.read",
  "stocktake.read", "stocktake.start", "stocktake.count",
  "stocktake.review", "stocktake.approve", "stocktake.recount",
  "stocktake.cancel",
];
const items = [{
  id: 77, reference_number: "STK-000077", stocktake_type: "FULL_COUNT",
  status: "COUNTING", location_id: 11,
  scope_product_variant_id: null, scope_product_name: null,
  scope_batch_id: null, scope_batch_number: null,
  related_work_session_id: null, started_by: 17,
  started_by_name: "Warehouse Operator",
  pending_independent_recount_required: false,
  snapshot_cutoff_at: "2026-11-04T08:00:00Z",
  created_at: "2026-11-04T08:00:00Z", updated_at: "2026-11-04T08:00:00Z",
}];
const countSheet = [
  {
    product_variant_id: 118, batch_id: 51, stock_status: "AVAILABLE",
    product_name: "Chickpeas 750 g", batch_number: "LOT-2026-A",
    expiry_date: "2027-01-17", base_uom_id: 7, base_uom_code: "EACH",
    base_uom_name: "Each", quantity_scale: 0, quantity_step: "1",
  },
  {
    product_variant_id: 119, batch_id: 52, stock_status: "QUARANTINED",
    product_name: "Oats 1.5 kg", batch_number: "LOT-2026-B",
    expiry_date: "2027-02-28", base_uom_id: 7, base_uom_code: "EACH",
    base_uom_name: "Each", quantity_scale: 0, quantity_step: "1",
  },
];
const review = {
  session_id: 77, reference_number: "STK-000077",
  stocktake_type: "FULL_COUNT", status: "PENDING_REVIEW", location_id: 11,
  independent_recount_satisfied: false,
  latest_attempt: {
    id: 91, attempt_number: 1, counted_by: 17,
    counted_by_name: "Warehouse Operator",
    authorized_by: null, authorized_by_name: null,
    recount_of_attempt_id: null, recount_reason: null,
    requires_independent_recount: true,
    submitted_at: "2026-11-04T09:00:00Z",
  },
  attempt_history: [{
    id: 91, attempt_number: 1, counted_by: 17,
    counted_by_name: "Warehouse Operator",
    authorized_by: null, authorized_by_name: null,
    recount_of_attempt_id: null, recount_reason: null,
    requires_independent_recount: true,
    submitted_at: "2026-11-04T09:00:00Z",
  }],
  lines: countSheet.map((item, i) => ({
    attempt_line_id: 101 + i, ...item, line_origin: "SNAPSHOT",
    expected_quantity: i ? "5" : "20",
    actual_quantity: i ? "5" : "18",
    variance_quantity: i ? "0" : "-2", notes: null,
  })),
};
function respond(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status, contentType: "application/json", body: JSON.stringify(data),
  });
}
async function setup(page: Page, locale: "ar" | "en", stage: "counting" | "review") {
  await page.addInitScript(({ locale, stage }) => {
    const jwt = "x." + btoa(JSON.stringify({
      type: "refresh", sub: "7", company_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })) + ".x";
    localStorage.setItem("admin_token", "stocktake-776-browser-fixture");
    localStorage.setItem("refresh_token", jwt);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");
    localStorage.setItem("backoffice_user_id", "17");
    localStorage.setItem("driver_id", "7");
    localStorage.setItem("wanasah.language", locale);
    localStorage.setItem("inventory_active_tab:1", "stocktake");
    localStorage.setItem("inventory_selected_location:1", "11");
    localStorage.setItem("unified_stocktake_session:1:11", "77");
    localStorage.setItem("unified_stocktake_phase:1:11", stage === "review" ? "REVIEW" : "COUNTING");
  }, { locale, stage });

  await page.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (path === "/tenant/identity") return respond(route, {
      company_id: 1, company_name: "Stocktake Browser Fixture",
      company_code: "STK", currency_code: "JOD", timezone: "Asia/Amman",
      country_id: null, country_name: null, display_location: "Amman",
    });
    if (path === "/inventory/access/me") {
      const id = Number(new URL(request.url()).searchParams.get("location_id"));
      return respond(route, {
        company_id: 1, principal_id: 7, backoffice_user_id: 17,
        is_company_owner: true, location_id: Number.isFinite(id) && id > 0 ? id : null,
        permissions: [], any_permissions: permissions,
        location_permissions: permissions,
      });
    }
    if (path === "/inventory/access/locations/capabilities") return respond(route, {
      locations: { "11": permissions },
    });
    if (path === "/warehouse/locations" || path === "/warehouse/locations/selection") {
      return respond(route, {
        items: [{ id: 11, name: "Main Warehouse", code: "AMMAN-01" }],
        next_cursor: null, has_more: false, total: 1,
        selected: { id: 11, name: "Main Warehouse", code: "AMMAN-01" },
      });
    }
    if (path === "/warehouse/setup-status") return respond(route, {
      warehouse_ready: true, active_warehouse_count: 1,
      accessible_warehouse_count: 1, can_create: false,
    });
    if (path === "/warehouse/status") return respond(route, {
      status: "ACTIVE", stocktake_session_id: 77,
      stocktake_reference: "STK-000077",
      stocktake_status: stage === "review" ? "PENDING_REVIEW" : "COUNTING",
    });
    if (path === "/warehouse/unified/stocktakes/active") {
      return respond(route, {
        items: [{ ...items[0], status: stage === "review" ? "PENDING_REVIEW" : "COUNTING" }],
        next_cursor: null, has_more: false, total: 1,
      });
    }
    if (path.includes("/stocktake/77/context")) {
      return respond(route, {
        session_id: 77, stocktake_type: "FULL_COUNT",
        status: stage === "review" ? "PENDING_REVIEW" : "COUNTING",
        location_id: 11, related_work_session_id: null,
        source_location_id: 11,
      });
    }
    if (path === "/warehouse/unified/stocktake/77/count-sheet") return respond(route, countSheet);
    if (path === "/warehouse/unified/stocktake/77/review") return respond(route, review);
    if (path.includes("/stocktake/77/discovery-options")) {
      const url = new URL(request.url());
      if (url.searchParams.has("product_variant_id")) return respond(route, {
        items: [{
          id: 53, product_variant_id: 118,
          batch_number: "LOT-2026-Z", production_date: "2026-01-10",
          expiry_date: "2027-01-10", is_active: true, disposition: "RELEASED",
        }], next_cursor: null, has_more: false, total: 1,
      });
      return respond(route, {
        items: [{
          id: 118, name: "Chickpeas 750 g", sku: "CH-750",
          base_uom_id: 7, base_uom_code: "EACH",
          base_uom_name: "Each", quantity_scale: 0, quantity_step: "1",
        }], next_cursor: null, has_more: false, total: 1,
      });
    }
    if (path === "/warehouse/inventory/summary") return respond(route, { stock_total: 2, alert_count: 0 });
    if (path === "/warehouse/inventory/families") return respond(route, { items: [], next_cursor: null, has_more: false });
    if (path === "/warehouse/unified/transfers") return respond(route, { items: [], next_cursor: null, has_more: false, total: 0 });
    if (path === "/warehouse/ledger/cursor") return respond(route, { items: [], next_cursor: null, has_more: false, total: 0, available_types: [] });
    return respond(route, { detail: { code: "STOCKTAKE_776_UNMOCKED", message: path } }, 404);
  });
}
for (const locale of ["ar", "en"] as const) {
  for (const size of [{ name: "desktop", width: 1440, height: 900 }, { name: "phone", width: 390, height: 844 }]) {
    for (const stage of ["counting", "review"] as const) {
      test(locale + " " + size.name + " " + stage + " Chromium screenshot", async ({ page }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        await setup(page, locale, stage);
        await page.goto("/inventory");
        const stocktake = page.locator(".inventory-stocktake");
        await expect(stocktake).toBeVisible();
        // Session list is intentionally the operator navigation; open the selected fixture explicitly.
        await stocktake.getByRole("button", { name: locale === "ar" ? "فتح" : "Open", exact: true }).click();
        const needle = stage === "counting"
          ? locale === "ar" ? "عد أعمى نشط" : "Blind count in progress"
          : locale === "ar" ? "مراجعة محاولة" : "Review attempt";
        await expect(stocktake.getByText(needle, { exact: false }).first()).toBeVisible({ timeout: 15000 });
        await page.screenshot({ path: test.info().outputPath(locale + "-" + size.name + "-" + stage + ".png"), fullPage: true });
        // Observe actual usable controls and horizontal overflow; do not mutate stocktake.
        const overflow = await page.evaluate(() => ({
          viewport: innerWidth, document: document.documentElement.scrollWidth,
        }));
        console.log("STOCKTAKE_776_GEOMETRY=" + JSON.stringify({ locale, size: size.name, stage, ...overflow }));
        expect(overflow.document).toBeLessThanOrEqual(overflow.viewport + 2);
        if (stage === "counting") {
          const visibleInput = stocktake.locator("input[data-stocktake-count-input='true']:visible").first();
          await expect(visibleInput).toBeVisible();
          const focus = await page.evaluate(() => {
            const active = document.activeElement;
            return {
              tag: active?.tagName,
              visible: !!active && !!(active as HTMLElement).getClientRects().length,
              countInput: (active as HTMLElement)?.dataset.stocktakeCountInput === "true",
            };
          });
          console.log("STOCKTAKE_776_COUNT_FOCUS=" + JSON.stringify({ locale, size: size.name, ...focus }));
        }
      });
    }
  }
}
