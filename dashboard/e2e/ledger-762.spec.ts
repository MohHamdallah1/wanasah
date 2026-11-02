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
  destination_location_id: 11, destination_location_name: "Warehouse A",
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
    await page.route("**/api/inventory/access/me*", route => {
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
        entry(103, "PHYSICAL", { input_unit_cost: "1.250000",
          total_cost: "10.000000", average_cost_after: "1.125000", input_uom_code: "EACH" }),
      ]));
      referencePages += 1;
      if (url.searchParams.has("cursor")) return send(route, { detail: { code: "LEDGER_READ_FORBIDDEN" } }, 403);
      return send(route, pageData([entry(101, "RESERVATION")], "signed-next"));
    });
    await seedUx(page, locale, "light", "ledger");
    await page.goto("/inventory");
    const panel = page.locator(".inventory-ledger");
    const reservation = panel.locator('[data-ledger-quantity-kind="RESERVATION"]:visible').first();
    const statusChange = panel.locator('[data-ledger-quantity-kind="STATUS_CHANGE"]:visible').first();
    await expect(reservation).toBeVisible();
    await expect(statusChange).toBeVisible();
    await expect(reservation).toContainText(locale === "ar" ? "الحجز" : "reservation");
    await expect(statusChange).toContainText(locale === "ar" ? "دون إضافة" : "no physical stock");
    await expect(panel.getByText(locale === "ar" ? "متوسط تكلفة المخزون التاريخي بعد الحركة" : "Historical inventory average after movement").first()).toBeVisible();
    await page.screenshot({ path: `node_modules/.cache/ledger-762/${locale}-${width}-movements.png`, fullPage: true });
    const link = panel.getByRole("button", { name: locale === "ar" ?
      "فتح دليل المرجع REF-762" : "Open evidence for reference REF-762" }).first();
    await link.click();
    await expect.poll(() => referencePages).toBeGreaterThanOrEqual(2);
    await expect(panel.getByRole("alert", { name: "" })).toContainText(locale === "ar" ?
      "توقف عرض السجل" : "Ledger access changed");
    await expect(panel.getByText("Sensitive ledger item 101")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.screenshot({ path: `node_modules/.cache/ledger-762/${locale}-${width}-revoked.png`, fullPage: true });
  });
}
