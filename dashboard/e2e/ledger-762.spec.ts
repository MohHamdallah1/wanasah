import { expect, test, type Route } from "playwright/test";
import { installUxApi, seedUx } from "./live-stock-ux-closure.fixtures";

const send = (route: Route, payload: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });

const entry = (id: number, kind: string, overrides: Record<string, unknown> = {}) => ({
  id, product_variant_id: id, product_name: "Sensitive ledger item " + id,
  base_uom_id: 1, base_uom_code: "EACH", quantity_scale: 0, quantity_step: "1",
  type: kind === "STATUS_CHANGE" ? "STATUS_CHANGE" : kind === "RESERVATION" ? "TRANSFER" : "INBOUND_SUPPLIER",
  reference_type: kind === "STATUS_CHANGE" ? "STATUS_CHANGE" : kind === "RESERVATION" ? "TRANSFER" : "INBOUND_SUPPLIER",
  movement_kind: kind, quantity: kind === "PHYSICAL" ? "8" : "-3",
  balance_before: "10", balance_after: kind === "PHYSICAL" ? "18" : "10",
  balance_scope: "PRODUCT_LOCATION",
  batch_id: 71, batch_number: "LOT-A", source_location_id: kind === "PHYSICAL" ? null : 11,
  source_location_name: kind === "PHYSICAL" ? null : "Warehouse A",
  source_location_type: kind === "PHYSICAL" ? null : "WAREHOUSE",
  destination_location_id: 11, destination_location_name: "Warehouse A",
  destination_location_type: "WAREHOUSE",
  source_stock_status: kind === "STATUS_CHANGE" ? "AVAILABLE" : null,
  destination_stock_status: kind === "STATUS_CHANGE" ? "DAMAGED" : "AVAILABLE",
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "حبة", display_factor_to_base: "1",
  currency_code: "JOD", cost_method: null, input_quantity: null,
  input_uom_code: null, input_uom_name: null, input_unit_cost: null, total_cost: null,
  average_cost_after: null, average_cost_uom_code: null, average_cost_uom_name: null,
  admin_name: "Sensitive operator", reference: "REF-762",
  notes: "Sensitive reference note", supplier_name: null, supplier_code: null, supplier_id: null,
  date: "2026-11-02T09:00:00+00:00", ...overrides,
});
const pageData = (items: unknown[], next: string | null = null) => ({
  items, has_more: next !== null, next_cursor: next, total: items.length,
  available_types: ["TRANSFER", "STATUS_CHANGE", "INBOUND_SUPPLIER"],
});

for (const locale of ["ar", "en"] as const) for (const width of [1440, 390] as const) {
  test(`ledger reference fail closed ${locale} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await installUxApi(page, 1, { allowOtherInventoryReads: true });
    let revoked = false;
    await page.route("**/api/inventory/access/me*", route => {
      if (revoked) return send(route, { detail: { code: "LEDGER_READ_FORBIDDEN" } }, 403);
      const url = new URL(route.request().url());
      const location = url.searchParams.get("location_id");
      return send(route, { company_id: 1, principal_id: 7, backoffice_user_id: 17,
        is_company_owner: true, location_id: location ? Number(location) : null,
        permissions: ["inventory.read", "location.read", "ledger.read", "ledger.adjust"],
        location_permissions: location ? ["ledger.read", "ledger.adjust"] : [],
        any_permissions: ["inventory.read", "location.read", "ledger.read"] });
    });
    let referencePages = 0;
    await page.route("**/api/warehouse/ledger/cursor?*", route => {
      const url = new URL(route.request().url());
      if (!url.searchParams.has("reference_id")) return send(route, pageData([
        entry(101, "RESERVATION"), entry(102, "STATUS_CHANGE"),
        entry(103, "PHYSICAL", { input_unit_cost: null, cost_method: "FIFO",
          total_cost: "10.000000", average_cost_after: "1.125000", average_cost_uom_code: "EACH",
          supplier_name: "Supplier proof", supplier_code: "SUP-9" }),
      ]));
      referencePages += 1;
      if (url.searchParams.has("cursor")) {
        revoked = true;
        return send(route, { detail: { code: "LEDGER_READ_FORBIDDEN" } }, 403);
      }
      return send(route, pageData([entry(101, "RESERVATION")], "signed-next"));
    });
    await seedUx(page, locale, "light", "ledger");
    await page.goto("/inventory");
    const panel = page.locator(".inventory-ledger");
    await panel.getByRole("button", { name: locale === "ar" ? "الحركات التفصيلية" : "Detailed movements" }).click();
    const reservation = panel.locator('[data-ledger-quantity-kind="RESERVATION"]:visible').first();
    const statusChange = panel.locator('[data-ledger-quantity-kind="STATUS_CHANGE"]:visible').first();
    await expect(reservation).toBeVisible();
    await expect(statusChange).toBeVisible();
    await expect(reservation).toContainText(locale === "ar" ? "الحجز" : "reservation");
    await expect(statusChange).toContainText(locale === "ar" ? "دون إضافة" : "no physical stock");
    const average = panel.getByText(locale === "ar" ? "متوسط تكلفة المخزون التاريخي بعد الحركة" : "Historical inventory average after movement", { exact: false });
    await expect(width === 390 ? average.last() : average.first()).toBeVisible();
    const visibleSurface = width === 390
      ? panel.locator('[data-cp13-phone-list="true"]')
      : panel.locator('[data-cp13-ledger-list="chronological"]');
    await expect(visibleSurface.getByText(locale === "ar" ? "قيمة حركة المخزون: 10.000000 JOD" : "Inventory value movement: 10.000000 JOD")).toBeVisible();
    await expect(visibleSurface.getByText("Supplier proof", { exact: false })).toBeVisible();
    await expect(visibleSurface.getByText(locale === "ar" ? "الوارد أولاً يُصرف أولاً (FIFO)" : "First in, first out (FIFO)", { exact: false })).toBeVisible();
    await page.screenshot({ path: `node_modules/.cache/ledger-762/${locale}-${width}-movements.png`, fullPage: true });
    const link = panel.getByRole("button", { name: locale === "ar" ?
      "فتح دليل المرجع REF-762" : "Open evidence for reference REF-762" }).first();
    await link.click();
    await expect.poll(() => referencePages).toBeGreaterThanOrEqual(2);
    // The shell may remove the whole tab after its fresh 403 capability read.
    // Both paths must hide *all* old Ledger evidence, never report zero/empty.
    await expect(page.getByText("Sensitive ledger item 101")).toHaveCount(0);
    await expect(page.getByText("Sensitive operator")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.screenshot({ path: `node_modules/.cache/ledger-762/${locale}-${width}-revoked.png`, fullPage: true });
  });
}

for (const locale of ["ar", "en"] as const) for (const width of [1440, 700, 390] as const) {
  test(`ledger #818 real-operation row and lazy detail ${locale} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
    await installUxApi(page, 1, { allowOtherInventoryReads: true });
    // The shared Live Stock fixture intentionally grants inventory.read only.
    // Ledger grouping requires a genuine location-scoped ledger.read grant;
    // keep denial/revocation coverage in the separate tests above.
    await page.route("**/api/inventory/access/me*", route => {
      const url = new URL(route.request().url());
      const location = url.searchParams.get("location_id");
      return send(route, {
        company_id: 1, principal_id: 7, backoffice_user_id: 17,
        is_company_owner: true, location_id: location ? Number(location) : null,
        permissions: ["inventory.read", "location.read", "ledger.read", "ledger.adjust"],
        location_permissions: location ? ["ledger.read", "ledger.adjust"] : [],
        any_permissions: ["inventory.read", "location.read", "ledger.read"],
      });
    });
    await page.route("**/api/warehouse/ledger/operations/cursor?*", route => send(route, {
      items: [{
        group_key: "opaque-818-transfer", group_kind: "TRANSFER",
        operation_type: "WAREHOUSE_TRANSFER", reference: "TX-818",
        latest_at: "2026-11-07T15:00:00+00:00", latest_movement_id: 302,
        source_location_name: "Warehouse A", destination_location_name: "Warehouse B",
        latest_actor_name: "Operator", stage_types: ["TRANSFER_DISPATCH", "TRANSFER_RECEIPT"],
        movement_kinds: ["PHYSICAL"], movement_count: 20, product_variant_count: 10,
        batch_count: 10, expandable: true, count_meaning: "AUTHORIZED_IMMUTABLE_MOVEMENTS",
        stocktake_history: null,
      }],
      next_cursor: null, has_more: false, snapshot_max_movement_id: 302,
      type_filter_semantics: "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED",
    }));
    await page.route("**/api/warehouse/ledger/operations/opaque-818-transfer/movements/cursor?*", route =>
      send(route, {
        group_key: "opaque-818-transfer",
        items: [
          entry(301, "PHYSICAL", {
            type: "TRANSFER_DISPATCH", reference_type: "TRANSFER_DISPATCH", reference: "TX-818",
            batch_number: "LOT-SEND", matches_filter: true,
            total_cost: "0.000000", average_cost_after: "1.250000", cost_method: "FIFO",
            average_cost_uom_code: "EACH", notes: "Real dispatch phase",
          }),
          entry(302, "PHYSICAL", {
            type: "TRANSFER_RECEIPT", reference_type: "TRANSFER_RECEIPT", reference: "TX-818",
            batch_number: "LOT-RECV", matches_filter: true,
            total_cost: null, notes: "Real receipt phase",
          }),
        ],
        next_cursor: null, has_more: false,
      }));
    await seedUx(page, locale, "light", "ledger");
    await page.goto("/inventory");
    const panel = page.locator(".inventory-ledger");
    const label = locale === "ar" ? "عملية تحويل" : "Warehouse transfer";
    await expect(panel.getByText(label)).toBeVisible();
    await expect(panel.locator('[data-ledger-operation-row="true"]')).toHaveCount(1);
    await expect(panel.getByText(locale === "ar" ? "10 أصناف" : "10 products")).toBeVisible();
    await page.screenshot({
      path: `node_modules/.cache/ledger-762/${locale}-${width}-operation.png`, fullPage: true,
    });
    await panel.getByRole("button", { name: `${locale === "ar" ? "التفاصيل" : "Details"}: TX-818` }).click();
    await expect(page.locator('[data-ledger-operation-details="true"]')).toBeVisible();
    await expect(page.locator('[data-ledger-child-id="301"]')).toBeVisible();
    await expect(page.locator('[data-ledger-child-id="302"]')).toBeVisible();
    await expect(page.getByText("LOT-SEND")).toBeVisible();
    await expect(page.getByText("LOT-RECV")).toBeVisible();
    await expect(page.getByText(locale === "ar" ? "قيمة حركة المخزون: 0.000000 JOD" :
      "Inventory value movement: 0.000000 JOD")).toBeVisible();
    await page.screenshot({
      path: `node_modules/.cache/ledger-762/${locale}-${width}-operation-details.png`, fullPage: true,
    });
  });
}


const OWNER_825_TRN = "TRN-F492EC77AA084613A047F261A8BEE9E9";
for (const locale of ["ar", "en"] as const) for (const width of [1440, 700, 390] as const) {
  test("ledger #825 directional columns, exact reference and in-panel Back " + locale + " " + width,
    async ({ page }) => {
      await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
      await installUxApi(page, 1, { allowOtherInventoryReads: true });
      await page.route("**/api/inventory/access/me*", route => {
        const url = new URL(route.request().url());
        const location = url.searchParams.get("location_id");
        return send(route, {
          company_id: 1, principal_id: 7, backoffice_user_id: 17,
          is_company_owner: true, location_id: location ? Number(location) : null,
          permissions: ["inventory.read", "location.read", "ledger.read", "ledger.adjust"],
          location_permissions: location ? ["ledger.read", "ledger.adjust"] : [],
          any_permissions: ["inventory.read", "location.read", "ledger.read"],
        });
      });
      const op = (id: number, reference: string) => ({
        group_key: "signed-group-" + id, group_kind: "TRANSFER",
        operation_type: "TRANSFER_DISPATCH", reference,
        latest_at: "2026-11-08T04:10:00+00:00", latest_movement_id: 500 + id,
        source_location_name: id === 1 ? "Vehicle 12-25132" : "Warehouse A",
        destination_location_name: "Warehouse B", latest_actor_name: "Operator",
        stage_types: ["TRANSFER_DISPATCH"], movement_kinds: ["PHYSICAL"],
        movement_count: 1, product_variant_count: 1, batch_count: 1,
        expandable: true, count_meaning: "AUTHORIZED_IMMUTABLE_MOVEMENTS",
        stocktake_history: null,
      });
      await page.route("**/api/warehouse/ledger/operations/cursor?*", route => send(route, {
        items: [op(1, OWNER_825_TRN), op(2, "13"), op(3, "13")],
        next_cursor: null, has_more: false, snapshot_max_movement_id: 503,
        type_filter_semantics: "MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED",
      }));
      await page.route("**/api/warehouse/ledger/operations/signed-group-1/movements/cursor?*", route =>
        send(route, { group_key: "signed-group-1", items: [entry(501, "PHYSICAL", {
          type: "TRANSFER_DISPATCH", reference_type: "TRANSFER_DISPATCH",
          reference: OWNER_825_TRN, batch_number: "LOT-SEND",
          source_location_name: "Vehicle 12-25132", source_location_type: "VEHICLE",
          source_stock_status: "AVAILABLE", destination_location_name: "Warehouse B",
          matches_filter: true,
        })], next_cursor: null, has_more: false }));
      let referenceCalls = 0;
      await page.route("**/api/warehouse/ledger/cursor?*", route => {
        const req = new URL(route.request().url());
        expect(req.searchParams.get("reference_id")).toBe(OWNER_825_TRN);
        referenceCalls++;
        return send(route, pageData([entry(501, "PHYSICAL", {
          type: "TRANSFER_DISPATCH", reference_type: "TRANSFER_DISPATCH",
          reference: OWNER_825_TRN, batch_number: "LOT-SEND",
        })]));
      });
      await seedUx(page, locale, "light", "ledger");
      await page.goto("/inventory");
      const panel = page.locator(".inventory-ledger");
      const rows = panel.locator('[data-ledger-operation-row="true"]');
      await expect(rows).toHaveCount(3);
      await expect(rows.locator('[data-ledger-column="columnReference"] bdi').filter({ hasText: /^13$/ })).toHaveCount(2);
      await expect(rows.first().getByRole("button", { name: (locale === "ar" ? "التفاصيل: " : "Details: ") + OWNER_825_TRN })).toBeVisible();
      const summaryRef = rows.first().locator('[data-ledger-column="columnReference"] bdi');
      await expect(summaryRef).toContainText("…");
      await expect(summaryRef).toHaveAttribute("title", OWNER_825_TRN);
      await summaryRef.focus();
      await expect(summaryRef).toBeFocused();
      const time = rows.first().locator('[data-ledger-column="columnDate"] time');
      await expect(time).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      await expect(time).toHaveAttribute("dateTime", "2026-11-08T04:10:00+00:00");
      await expect(rows.first()).toContainText(locale === "ar" ? "مركبة 12-25132" : "Vehicle 12-25132");
      await expect(rows.first()).toContainText(locale === "ar" ? "1 صنف" : "1 product");
      if (width === 1440) {
        for (const col of ["columnType", "columnReference", "columnDate", "columnRoute",
          "columnProducts", "columnMovements", "columnAction"]) {
          const header = await panel.locator('[role="columnheader"][data-ledger-column="' + col + '"]').boundingBox();
          const cell = await rows.first().locator('[role="cell"][data-ledger-column="' + col + '"]').boundingBox();
          // Fractional fr tracks and scrollbar rounding can shift individual x by a few px.
          // Header/body still share the exact same seven-track CSS grid.
          expect(header && cell && Math.abs(header.x - cell.x)).toBeLessThan(12);
        }
        const displays = await panel.locator('[role="table"] [role="row"]').evaluateAll(nodes =>
          nodes.slice(0, 2).map(node => getComputedStyle(node).display));
        expect(displays).toEqual(["table-row", "table-row"]);
        await expect(panel.getByText(locale === "ar" ? "مرجع العملية" : "Operation reference")).toBeVisible();
      }
      await page.screenshot({ path: "node_modules/.cache/ledger-762/825-" + locale + "-" + width + "-operations.png", fullPage: true });
      await rows.first().getByRole("button", { name: (locale === "ar" ? "التفاصيل: " : "Details: ") + OWNER_825_TRN }).click();
      await expect(page.locator('[data-ledger-full-operation-reference="true"] bdi')).toHaveText(OWNER_825_TRN);
      await expect(page.locator('[data-ledger-child-id="501"]')).toBeVisible();
      await page.screenshot({ path: "node_modules/.cache/ledger-762/825-" + locale + "-" + width + "-details.png", fullPage: true });
      const evidence = page.getByRole("button", { name: locale === "ar" ? "دليل المرجع" : "Reference evidence" });
      await evidence.click();
      const back = page.getByRole("button", { name: locale === "ar" ? "الرجوع إلى تفاصيل العملية" : "Back to operation details" });
      await expect(back).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await expect.poll(() => referenceCalls).toBe(1);
      await page.screenshot({ path: "node_modules/.cache/ledger-762/825-" + locale + "-" + width + "-reference.png", fullPage: true });
      await back.click();
      await expect(evidence).toBeFocused();
      await expect(page.locator('[data-ledger-child-id="501"]')).toBeVisible();
      await expect(page.getByRole("dialog")).toHaveCount(1);
      await page.screenshot({ path: "node_modules/.cache/ledger-762/825-" + locale + "-" + width + "-back.png", fullPage: true });
    });
}
