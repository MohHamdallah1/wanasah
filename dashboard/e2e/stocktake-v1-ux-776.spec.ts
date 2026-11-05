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
const firstAttempt = {
  id: 91, attempt_number: 1, counted_by: 17,
  counted_by_name: "Original counter",
  authorized_by: null, authorized_by_name: null,
  recount_of_attempt_id: null, recount_reason: null,
  requires_independent_recount: true,
  submitted_at: "2026-11-04T09:00:00Z",
};
const secondAttempt = {
  id: 92, attempt_number: 2, counted_by: 18,
  counted_by_name: "Independent counter",
  authorized_by: 30, authorized_by_name: "Review supervisor",
  recount_of_attempt_id: 91, recount_reason: "Damaged shelf recount",
  requires_independent_recount: false,
  submitted_at: "2026-11-04T11:15:00+03:00",
};
const review = {
  session_id: 77, reference_number: "STK-000077",
  stocktake_type: "FULL_COUNT", status: "PENDING_REVIEW", location_id: 11,
  independent_recount_satisfied: true,
  latest_attempt: secondAttempt,
  attempt_history: [firstAttempt, secondAttempt],
  // Only latest attempt lines are in this canonical response.
  lines: countSheet.map((item, i) => ({
    attempt_line_id: 101 + i, ...item,
    line_origin: i ? "DISCOVERED" : "SNAPSHOT",
    expected_quantity: i ? "0" : "20",
    actual_quantity: i ? "5" : "18",
    variance_quantity: i ? "5" : "-2", notes: null,
  })),
};
function respond(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status, contentType: "application/json", body: JSON.stringify(data),
  });
}
async function setup(page: Page, locale: "ar" | "en", stage: "counting" | "review" | "cycle") {
  let cycleStartedProduct: number | null = null;
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
    if (stage !== "cycle") {
      localStorage.setItem("unified_stocktake_session:1:11", "77");
      localStorage.setItem("unified_stocktake_phase:1:11", stage === "review" ? "REVIEW" : "COUNTING");
    }
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
      status: stage === "cycle" && cycleStartedProduct === null ? "ACTIVE" : "AUDIT_LOCK",
      stocktake_session_id: stage === "cycle" && cycleStartedProduct === null ? null : 77,
      stocktake_reference: stage === "cycle" && cycleStartedProduct === null ? null : "STK-000077",
      stocktake_status: stage === "cycle" && cycleStartedProduct === null ? null : stage === "review" ? "PENDING_REVIEW" : "COUNTING",
    });
    if (path === "/warehouse/unified/stocktakes/active") {
      return respond(route, {
        items: stage === "cycle" && cycleStartedProduct === null ? [] : [{
          ...items[0], stocktake_type: stage === "cycle" ? "CYCLE_COUNT" : "FULL_COUNT",
          scope_product_variant_id: stage === "cycle" ? cycleStartedProduct : null,
          scope_product_name: stage === "cycle" ? (cycleStartedProduct === 120 ? "Missing stock" : "Chickpeas 750 g") : null,
          status: stage === "review" ? "PENDING_REVIEW" : "COUNTING",
        }],
        next_cursor: null, has_more: false, total: stage === "cycle" && cycleStartedProduct === null ? 0 : 1,
      });
    }
    if (path.includes("/stocktake/77/context")) {
      return respond(route, {
        session_id: 77, stocktake_type: stage === "cycle" ? "CYCLE_COUNT" : "FULL_COUNT",
        status: stage === "review" ? "PENDING_REVIEW" : "COUNTING",
        location_id: 11, related_work_session_id: null,
        source_location_id: 11,
      });
    }
    if (path === "/warehouse/unified/stocktake/77/count-sheet") return respond(route,
      stage !== "cycle" ? countSheet : cycleStartedProduct === 120 ? [] : [
        { ...countSheet[0], product_variant_id: 118, batch_id: 51, batch_number: "LOT-2026-A", stock_status: "AVAILABLE" },
        { ...countSheet[0], product_variant_id: 118, batch_id: 52, batch_number: "LOT-2026-B", stock_status: "QUARANTINED" },
      ]);
    if (stage === "cycle" && path === "/warehouse/unified/stocktake/start") {
      const body = JSON.parse(request.postData() ?? "{}");
      cycleStartedProduct = Number(body.product_variant_id);
      return respond(route, { session_id: 77, id: 77, reference_number: "STK-000077" });
    }
    if (stage === "cycle" && path === "/warehouse/inventory/cursor") {
      const query = new URL(request.url()).searchParams;
      if (query.get("location_id") !== "11") return respond(route, { detail: "Wrong warehouse" }, 403);
      const meta = {
        base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
        quantity_scale: 0, quantity_step: "1",
      };
      const product = (id: number, name: string) => ({ id, name, sku: "P-" + id, ...meta });
      const raw = query.get("view") === "warehouse" && query.get("stock_state") === "on_hand"
        ? [product(118, "Chickpeas 750 g"), product(119, "Quarantined item")]
        : query.get("view") === "catalog" && query.get("stock_state") === "all"
          ? [product(118, "Chickpeas 750 g"), product(119, "Quarantined item"), product(120, "Missing stock")]
          : [];
      const search = (query.get("search") ?? "").toLowerCase();
      const filtered = raw.filter(item => !search || item.name.toLowerCase().includes(search) || item.sku.toLowerCase().includes(search));
      return respond(route, { items: filtered, next_cursor: null, has_more: false, total: filtered.length });
    }
    if (stage === "cycle" && path === "/warehouse/unified/stocktake/cycle-batches") {
      const query = new URL(request.url()).searchParams;
      if (query.get("product_variant_id") !== "118") return respond(route, { items: [], next_cursor: null, has_more: false, total: 0 });
      return respond(route, { items: [
        { id: 51, product_variant_id: 118, batch_number: "LOT-2026-A", production_date: "2026-01-10", expiry_date: "2027-01-17", is_active: true },
        { id: 52, product_variant_id: 118, batch_number: "LOT-2026-B", production_date: "2026-01-10", expiry_date: "2027-02-28", is_active: true },
      ], next_cursor: null, has_more: false, total: 2 });
    }
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
          ? locale === "ar" ? "العد جارٍ" : "Count in progress"
          : locale === "ar" ? "مراجعة العد" : "Review count";
        await expect(stocktake.getByText(needle, { exact: false }).first()).toBeVisible({ timeout: 15000 });
        if (stage === "review") {
          // #779: exact canonical response -> visible reviewer evidence on both breakpoints.
          const historyLabel = locale === "ar" ? "سجل محاولات العد" : "Count attempt history";
          const disclosure = stocktake.locator(".inventory-data-panel details");
          await expect(disclosure).not.toHaveAttribute("open");
          await disclosure.locator("summary").click();
          await expect(disclosure).toHaveAttribute("open");
          const list = stocktake.getByRole("list", { name: historyLabel });
          await expect(list).toBeVisible();
          await expect(list.getByRole("listitem")).toHaveCount(2);
          await expect(list.getByText("Original counter", { exact: false })).toBeVisible();
          await expect(list.getByText("Independent counter", { exact: false })).toBeVisible();
          await expect(list.getByText("Review supervisor", { exact: false })).toBeVisible();
          await expect(list.getByText("Damaged shelf recount", { exact: false })).toBeVisible();
          await expect(list.locator("time")).toHaveCount(2);
          await expect(list.locator("time").nth(1)).toHaveAttribute("datetime", secondAttempt.submitted_at);
          await expect(stocktake.locator("span:visible").filter({ hasText: "2027-02-28" }).first()).toBeVisible();
          const originLabel = locale === "ar" ? "بضاعة مكتشفة أثناء الجرد" : "Discovered during count";
          await expect(stocktake.getByText(originLabel, { exact: true }).locator("visible=true")).toBeVisible();
          const currentLines = size.name === "phone"
            ? stocktake.locator(".inventory-data-panel article:visible")
            : stocktake.locator(".inventory-data-panel tbody tr:visible");
          await expect(currentLines).toHaveCount(2); // Never invent previous attempt count lines.
          // Retain an expanded audit screenshot separately; default view keeps Lot lines accessible.
          await page.screenshot({ path: test.info().outputPath(locale + "-" + size.name + "-review-history.png"), fullPage: true });
          await disclosure.locator("summary").click();
          await expect(disclosure).not.toHaveAttribute("open");
          console.log("STOCKTAKE_779_REVIEW_PARITY=PASS " + JSON.stringify({ locale, size: size.name }));
        }
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
          // Two count views exist in the DOM for responsive rendering; only visible
          // fields belong to the operator's Enter navigation sequence.
          const inputs = stocktake.locator("input[data-stocktake-count-input='true']:visible");
          await expect(inputs).toHaveCount(2);
          await inputs.nth(0).fill("18");
          await inputs.nth(0).press("Enter");
          await expect(inputs.nth(1)).toBeFocused();
          await inputs.nth(1).fill("5");
          await inputs.nth(1).press("Enter");
          // Enter on the last VISIBLE field must open confirmation; it must
          // never jump into the other breakpoint's hidden field.
          await expect(page.getByRole("dialog")).toBeVisible();
          console.log("STOCKTAKE_776_ENTER_VISIBLE_SUBMIT=PASS " + JSON.stringify({ locale, size: size.name }));
        }
      });
    }
  }
}


for (const locale of ["ar", "en"] as const) {
  for (const size of [{ name: "desktop", width: 1440, height: 900 }, { name: "phone", width: 390, height: 844 }]) {
    test("#782 " + locale + " " + size.name + " product-first all-batch count", async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await setup(page, locale, "cycle");
      const seen: string[] = [];
      page.on("request", request => {
        const url = new URL(request.url());
        if (url.pathname === "/api/warehouse/inventory/cursor") seen.push(url.search);
      });
      await page.goto("/inventory");
      const stocktake = page.locator(".inventory-stocktake");
      await stocktake.getByRole("button", { name: locale === "ar" ? "جرد صنف" : "Count product" }).click();
      const dialog = page.getByRole("dialog", { name: locale === "ar" ? "جرد صنف" : "Product count" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("button", { name: locale === "ar" ? "أصناف موجودة بالمستودع" : "Products on hand here" })).toHaveAttribute("aria-pressed", "true");
      await expect(dialog.getByRole("button", { name: "Quarantined item" })).toBeVisible();
      await expect(dialog.getByRole("button", { name: "Missing stock" })).toHaveCount(0);
      await expect.poll(() => seen.some(q => q.includes("view=warehouse") && q.includes("stock_state=on_hand") && q.includes("location_id=11"))).toBeTruthy();

      // Optional catalog mode includes zero-stock products, but all-batches remains the default.
      const catalogLabel = locale === "ar" ? "بحث في جميع أصناف الشركة" : "Search entire company catalog";
      await dialog.getByRole("button", { name: catalogLabel }).click();
      await expect(dialog.getByRole("button", { name: "Missing stock" })).toBeVisible();
      await expect.poll(() => seen.some(q => q.includes("view=catalog") && q.includes("stock_state=all") && q.includes("location_id=11"))).toBeTruthy();
      await dialog.getByRole("button", { name: "Chickpeas 750 g" }).click();
      await expect(dialog.locator("details")).not.toHaveAttribute("open");
      // Optional advanced single-batch choice is genuine, and returning to all is explicit.
      await dialog.locator("details summary").click();
      const lot = dialog.getByRole("button", { name: /LOT-2026-A/ });
      await expect(lot).toBeVisible();
      await lot.click();
      await expect(dialog.locator("details summary")).toContainText("LOT-2026-A");
      await dialog.getByRole("button", { name: locale === "ar" ? "كل تشغيلات الصنف" : "All product batches" }).click();
      await expect(dialog.locator("details summary")).toContainText(locale === "ar" ? "كل تشغيلات الصنف" : "All product batches");
      const startLabel = locale === "ar" ? "بدء العد" : "Start count";
      const startRequest = page.waitForRequest(req => req.url().endsWith("/warehouse/unified/stocktake/start") && req.method() === "POST");
      await dialog.getByRole("button", { name: startLabel }).click();
      const request = await startRequest;
      const payload = request.postDataJSON() as { stocktake_type: string; product_variant_id: number; batch_id: number | null; location_id: number };
      expect(payload).toMatchObject({ stocktake_type: "CYCLE_COUNT", product_variant_id: 118, batch_id: null, location_id: 11 });
      await expect(stocktake.getByText(locale === "ar" ? "العد جارٍ" : "Count in progress")).toBeVisible();
      await expect(dialog).toBeHidden(); // Wait for mobile modal/backdrop exit before judging rendered page.
      await expect(stocktake.locator("input[data-stocktake-count-input='true']:visible")).toHaveCount(2);
      await expect(stocktake.getByText("LOT-2026-A", { exact: false }).locator("visible=true")).toBeVisible();
      await expect(stocktake.getByText("LOT-2026-B", { exact: false }).locator("visible=true")).toBeVisible();
      // No expected inventory is ever disclosed on an unsubmitted count.
      await expect(stocktake.getByRole("button", { name: locale === "ar" ? "إنهاء العد وتثبيت المحاولة" : "Finish count and submit attempt" })).toBeDisabled();
      await page.screenshot({ path: test.info().outputPath("782-" + locale + "-" + size.name + "-count.png"), fullPage: true });
      console.log("STOCKTAKE_782_PRODUCT_COUNT=PASS " + JSON.stringify({ locale, size: size.name }));
    });

    test("#782 " + locale + " " + size.name + " zero stock guidance & cancellation", async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await setup(page, locale, "cycle");
      await page.goto("/inventory");
      const stocktake = page.locator(".inventory-stocktake");
      await stocktake.getByRole("button", { name: locale === "ar" ? "جرد صنف" : "Count product" }).click();
      const dialog = page.getByRole("dialog", { name: locale === "ar" ? "جرد صنف" : "Product count" });
      await dialog.getByRole("button", { name: locale === "ar" ? "بحث في جميع أصناف الشركة" : "Search entire company catalog" }).click();
      await dialog.getByRole("button", { name: "Missing stock" }).click();
      await dialog.getByRole("button", { name: locale === "ar" ? "بدء العد" : "Start count" }).click();
      await expect(dialog).toBeHidden();
      const hint = locale === "ar" ? "لا توجد كميات مسجلة" : "There is no recorded stock";
      await expect(stocktake.getByRole("status").getByText(hint, { exact: false })).toBeVisible();
      await expect(stocktake.getByRole("button", { name: locale === "ar" ? "إنهاء العد وتثبيت المحاولة" : "Finish count and submit attempt" })).toBeDisabled();
      await expect(stocktake.getByRole("status").getByRole("button")).toBeVisible();
      await stocktake.getByRole("button", { name: locale === "ar" ? "إلغاء الجرد" : "Cancel stocktake" }).click();
      await expect(page.getByRole("dialog", { name: locale === "ar" ? "إلغاء جلسة الجرد" : "Cancel stocktake session" })).toBeVisible();
      await page.screenshot({ path: test.info().outputPath("782-" + locale + "-" + size.name + "-zero.png"), fullPage: true });
      console.log("STOCKTAKE_782_ZERO_STOCK=PASS " + JSON.stringify({ locale, size: size.name }));
    });
  }
}
