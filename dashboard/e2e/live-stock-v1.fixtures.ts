import { type Page, type Route } from "playwright/test";

// Synthetic browser-only data. No live API, accounts, database, or financial commands.
export type Locale = "ar" | "en";
export type Fixture = {
  requests: Array<{ method: string; path: string; location: number | null }>;
  unexpected: string[];
  cursorReads: number;
  failCursorOnce: boolean;
  failSourceOnce: boolean;
  denyAccess: boolean;
  rows: number;
};

const warehouses = [
  { id: 11, name: "Warehouse A", code: "AMMAN-A" },
  { id: 12, name: "Warehouse B", code: "AMMAN-B" },
];

export const item = (index: number, location = 11) => ({
  id: 118 + index,
  product_id: 118 + index,
  name: location === 11 ? `Stock Item ${String(index).padStart(4, "0")}` : `Warehouse B Item ${index}`,
  sku: `SKU-${118 + index}`,
  family_name: index % 2 === 0 ? "Snacks" : "Drinks",
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  display_uom_id: 8, display_uom_code: "CARTON", display_uom_name: "Carton",
  display_factor_to_base: "8", currency_code: "JOD",
  average_cost_display: index === 1 ? null : "0.125000",
  last_purchase_cost: index === 1 ? null : "1.500001",
  last_purchase_uom_code: index === 1 ? null : "EACH",
  last_purchase_date: index === 1 ? null : "2026-10-15",
  quantity_scale: 6, quantity_step: "0.000001",
  on_hand_quantity: "26", reserved_quantity: "10",
  available_for_sale_quantity: "16", unavailable_quantity: "0",
  vehicle_quantity: "0", recalled_quantity: "0",
  available_quantity: "16", blocked_quantity: "0",
  total_quantity: "26", damaged_quantity: "0", minimum_quantity: "1",
  is_low_stock: false,
});

const batch = {
  batch_id: 71, batch_number: "LOT-71", production_date: "2026-08-01",
  expiry_date: "2027-08-01", disposition: "RELEASED",
  disposition_revision: 1, disposition_reason: null, allowed_disposition_targets: ["QUARANTINED"],
  days_to_expiry: 270, on_hand_quantity: "26", reserved_quantity: "10",
  available_for_sale_quantity: "16", unavailable_quantity: "0", restricted_quantity: "0",
  expiry_unavailable_quantity: "0", quarantined_quantity: "0", blocked_quantity: "0",
  recalled_quantity: "0", damaged_quantity: "0", disposal_pending_quantity: "0",
  latest_purchase_cost: null, latest_purchase_uom_code: null,
  latest_purchase_date: null, purchase_event_count: 0,
};

const source = (location: number) => ({
  location_id: location, location_name: warehouses.find((w) => w.id === location)?.name ?? "Unknown",
  product_variant_id: 118, batch_id: 71,
  statuses: [{
    stock_status: "AVAILABLE", on_hand_quantity: "26",
    reserved_quantity: "10", movable_quantity: "16",
    reservation_evidence: {
      coverage: "PARTIAL",
      owners: [
        { transfer_id: 9001, reference_number: "RES-9001", quantity: "8" },
        { transfer_id: 9002, reference_number: "RES-9002", quantity: "1" },
      ],
      owners_truncated: true, unattributed_quantity: "1",
    },
  }],
});

const fulfill = (route: Route, payload: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });

export async function seedLiveStock(page: Page, locale: Locale, warehouse = 11) {
  // Same valid synthetic session/storage bootstrap used by CP14-D.
  await page.addInitScript(({ language, selected }) => {
    const refresh = `test.${btoa(JSON.stringify({
      type: "refresh", sub: "7", company_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))}.test`;
    localStorage.setItem("admin_token", "live-stock-chromium-fixture");
    localStorage.setItem("refresh_token", refresh);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");
    localStorage.setItem("backoffice_user_id", "17");
    localStorage.setItem("driver_id", "7");
    localStorage.setItem("wanasah.language", language);
    localStorage.setItem("inventory_active_tab:1", "live");
    localStorage.setItem("inventory_selected_location:1", String(selected));
  }, { language: locale, selected: warehouse });
}

export async function installLiveStockApi(page: Page, rows = 2): Promise<Fixture> {
  const state: Fixture = {
    requests: [], unexpected: [], cursorReads: 0, failCursorOnce: false,
    failSourceOnce: false, denyAccess: false, rows,
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = request.method();
    const location = url.searchParams.has("location_id")
      ? Number(url.searchParams.get("location_id")) : null;
    state.requests.push({ method, path: path + url.search, location });

    if (method !== "GET") {
      state.unexpected.push(`${method} ${path}`);
      return fulfill(route, { detail: { code: "BROWSER_MUTATION_FORBIDDEN" } }, 403);
    }
    if (path === "/tenant/identity") {
      return fulfill(route, {
        company_id: 1, company_name: "Browser Fixture Company",
        company_code: "LIVEV1", currency_code: "JOD",
        timezone: "Asia/Amman", country_id: null, country_name: null,
        display_location: "Amman",
      });
    }
    if (path === "/inventory/access/me") {
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      const scoped = location !== null;
      const allowed = location === null || warehouses.some((w) => w.id === location);
      if (!allowed) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      return fulfill(route, {
        company_id: 1, principal_id: 7, backoffice_user_id: 17,
        is_company_owner: true, location_id: location,
        permissions: ["inventory.read", "location.read"],
        any_permissions: ["inventory.read", "location.read"],
        location_permissions: scoped ? ["inventory.read", "location.read"] : [],
      });
    }
    if (path === "/warehouse/locations/selection") {
      const selected = Number(url.searchParams.get("selected_location_id") ?? 11);
      return fulfill(route, {
        items: warehouses, selected: warehouses.find((w) => w.id === selected) ?? null,
        next_cursor: null, has_more: false, total: warehouses.length,
      });
    }
    if (path === "/warehouse/setup-status") {
      return fulfill(route, { warehouse_ready: true, active_warehouse_count: 2,
        accessible_warehouse_count: 2, can_create: false });
    }
    if (path === "/warehouse/status") return fulfill(route, { status: "OPEN" });
    if (path === "/warehouse/inventory/summary") {
      if (!warehouses.some((w) => w.id === location)) return fulfill(route, {}, 403);
      return fulfill(route, { stock_total: location === 11 ? state.rows : 1, alert_count: 0 });
    }
    if (path === "/warehouse/inventory/families") {
      if (!warehouses.some((w) => w.id === location)) return fulfill(route, {}, 403);
      return fulfill(route, { items: [{ id: 21, name: "Snacks", code: "SN" },
        { id: 22, name: "Drinks", code: "DR" }], next_cursor: null, has_more: false });
    }
    if (path === "/warehouse/inventory/cursor") {
      state.cursorReads++;
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      if (state.failCursorOnce) {
        state.failCursorOnce = false;
        return fulfill(route, { detail: { code: "TEMPORARY_UNAVAILABLE" } }, 503);
      }
      if (!warehouses.some((w) => w.id === location)) return fulfill(route, {}, 403);
      let results = location === 12 ? [item(0, 12)]
        : Array.from({ length: state.rows }, (_, i) => item(i));
      const search = url.searchParams.get("search")?.toLowerCase();
      if (search) results = results.filter((r) =>
        r.name.toLowerCase().includes(search) || r.sku.toLowerCase().includes(search));
      const family = url.searchParams.get("family_id");
      if (family === "21") results = results.filter((r) => r.family_name === "Snacks");
      else if (family === "22") results = results.filter((r) => r.family_name === "Drinks");
      const filter = url.searchParams.get("stock_state");
      if (filter === "out_of_stock" || filter === "low_stock") results = [];
      const start = Number(url.searchParams.get("cursor") ?? 0);
      const limit = Math.min(50, Math.max(1, Number(url.searchParams.get("limit") ?? 50)));
      const end = Math.min(results.length, start + limit);
      return fulfill(route, { items: results.slice(start, end),
        next_cursor: end < results.length ? String(end) : null,
        has_more: end < results.length, total: null, alert_count: 0, alert_samples: [] });
    }
    const batchMatch = path.match(/^\/warehouse\/inventory\/(\d+)\/batches$/);
    if (batchMatch) {
      if (state.denyAccess) return fulfill(route, {}, 403);
      return fulfill(route, {
        location_id: location, product_variant_id: Number(batchMatch[1]), currency_code: "JOD",
        batches: [batch], next_cursor: null, has_more: false,
      });
    }
    const sourceMatch = path.match(/^\/warehouse\/inventory\/(\d+)\/batches\/71\/source$/);
    if (sourceMatch) {
      if (state.denyAccess) return fulfill(route, {}, 403);
      if (state.failSourceOnce) {
        state.failSourceOnce = false;
        return fulfill(route, { detail: { code: "SOURCE_TEMPORARY" } }, 503);
      }
      return fulfill(route, { ...source(location ?? 11),
        product_variant_id: Number(sourceMatch[1]) });
    }
    state.unexpected.push(`${method} ${path}`);
    return fulfill(route, { detail: { code: "UNMOCKED_BROWSER_API" } }, 404);
  });
  return state;
}
