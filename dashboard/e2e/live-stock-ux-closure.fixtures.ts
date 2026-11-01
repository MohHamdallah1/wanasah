import { type Page, type Route } from "playwright/test";

export type Locale = "ar" | "en";
export type Theme = "light" | "dark";

export type UxFixture = {
  requests: Array<{ method: string; path: string; location: number | null }>;
  unexpected: string[];
  otherReads: string[];
  cursorReads: number;
  summaryReads: number;
  familyReads: number;
  batchReads: number;
  sourceReads: Record<number, number>;
  failSummaryOnce: boolean;
  failCursorAt: Set<number>;
  failSourceBatchOnce: Set<number>;
  denyAccess: boolean;
  sourceDelayMs: number;
  accessDelayMs: number;
  cursorDelayMs: number;
  rows: number;
};

const warehouses = [
  { id: 11, name: "Warehouse A", code: "AMMAN-A" },
  { id: 12, name: "Warehouse B", code: "AMMAN-B" },
];

const longName = (index: number) =>
  index % 4 === 0
    ? `Stock Item ${String(index).padStart(4, "0")} — extra long descriptive product name for variable row height acceptance`
    : `Stock Item ${String(index).padStart(4, "0")}`;

const item = (index: number, location = 11) => ({
  id: 118 + index,
  product_id: 118 + index,
  name: location === 11 ? longName(index) : `Warehouse B Item ${index}`,
  sku: `SKU-${118 + index}`,
  family_name: index % 2 === 0 ? "Snacks" : "Drinks",
  base_uom_id: 7,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 8,
  display_uom_code: "CARTON",
  display_uom_name: "Carton",
  display_factor_to_base: "8",
  currency_code: "JOD",
  average_cost_display: index === 1 ? null : "0.125000",
  last_purchase_cost: index === 1 ? null : "1.500001",
  last_purchase_uom_code: index === 1 ? null : "EACH",
  last_purchase_date: index === 1 ? null : "2026-10-15",
  quantity_scale: 6,
  quantity_step: "0.000001",
  on_hand_quantity: "26",
  reserved_quantity: index % 3 === 0 ? "10" : "2",
  available_for_sale_quantity: index % 3 === 0 ? "16" : "24",
  unavailable_quantity: "0",
  vehicle_quantity_scope: "COMPANY_WIDE" as const, vehicle_quantity: index % 5 === 0 ? "8" : "0",
  recalled_quantity: "0",
  available_quantity: index % 3 === 0 ? "16" : "24",
  blocked_quantity: "0",
  total_quantity_scope: "WAREHOUSE_PHYSICAL" as const, total_quantity: "26",
  damaged_quantity: "0",
  minimum_quantity: "1",
  is_low_stock: false,
});

const makeBatch = (batchId: number, number: string, onHand: string, reserved: string) => ({
  batch_id: batchId,
  batch_number: number,
  production_date: batchId === 71 ? "2026-08-01" : "2026-09-01",
  expiry_date: batchId === 71 ? "2027-08-01" : "2027-09-01",
  disposition: "RELEASED",
  disposition_revision: 1,
  disposition_reason: null,
  allowed_disposition_targets: ["QUARANTINED"],
  days_to_expiry: batchId === 71 ? 270 : 300,
  on_hand_quantity: onHand,
  reserved_quantity: reserved,
  available_for_sale_quantity: String(Number(onHand) - Number(reserved)),
  unavailable_quantity: "0",
  restricted_quantity: "0",
  expiry_unavailable_quantity: "0",
  quarantined_quantity: "0",
  blocked_quantity: "0",
  recalled_quantity: "0",
  damaged_quantity: "0",
  disposal_pending_quantity: "0",
  latest_purchase_cost: "1.500001",
  latest_purchase_uom_code: "EACH",
  latest_purchase_date: "2026-10-15",
  purchase_event_count: 1,
});

const batches = [
  makeBatch(71, "LOT-71", "18", "10"),
  makeBatch(72, "LOT-72", "8", "2"),
];

const source = (location: number, batchId: number) => {
  const onHand = batchId === 71 ? "18" : "8";
  const reserved = batchId === 71 ? "10" : "2";
  const movable = batchId === 71 ? "8" : "6";
  return {
    location_id: location,
    location_name: warehouses.find((w) => w.id === location)?.name ?? "Unknown",
    product_variant_id: 118,
    batch_id: batchId,
    statuses: [{
      stock_status: "AVAILABLE",
      on_hand_quantity: onHand,
      reserved_quantity: reserved,
      movable_quantity: movable,
      reservation_evidence: {
        coverage: "PARTIAL",
        owners: batchId === 71
          ? [
              { transfer_id: 9001, reference_number: "RES-9001", quantity: "8" },
              { transfer_id: 9002, reference_number: "RES-9002", quantity: "1" },
            ]
          : [{ transfer_id: 9010, reference_number: "RES-9010", quantity: "1" }],
        owners_truncated: batchId === 71,
        unattributed_quantity: batchId === 71 ? "1" : "1",
      },
    }],
  };
};

const fulfill = (route: Route, payload: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });

const delay = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

export async function seedUx(
  page: Page,
  locale: Locale,
  theme: Theme = "light",
  activeTab = "live",
  warehouse = 11,
) {
  await page.addInitScript(
    ({ language, selectedTheme, selectedTab, selectedWarehouse }) => {
      const refresh = `test.${btoa(JSON.stringify({
        type: "refresh",
        sub: "7",
        company_id: 1,
        exp: Math.floor(Date.now() / 1000) + 3600,
      }))}.test`;
      localStorage.setItem("admin_token", "live-stock-ux-fixture");
      localStorage.setItem("refresh_token", refresh);
      localStorage.setItem("company_id", "1");
      localStorage.setItem("principal_id", "7");
      localStorage.setItem("backoffice_user_id", "17");
      localStorage.setItem("driver_id", "7");
      localStorage.setItem("wanasah.language", language);
      localStorage.setItem("inventory_active_tab:1", selectedTab);
      localStorage.setItem("inventory_selected_location:1", String(selectedWarehouse));
      document.documentElement.classList.toggle("dark", selectedTheme === "dark");
    },
    {
      language: locale,
      selectedTheme: theme,
      selectedTab: activeTab,
      selectedWarehouse: warehouse,
    },
  );
}

export async function installUxApi(
  page: Page,
  rows = 120,
  options: { allowOtherInventoryReads?: boolean } = {},
): Promise<UxFixture> {
  const state: UxFixture = {
    requests: [],
    unexpected: [],
    otherReads: [],
    cursorReads: 0,
    summaryReads: 0,
    familyReads: 0,
    batchReads: 0,
    sourceReads: {},
    failSummaryOnce: false,
    failCursorAt: new Set(),
    failSourceBatchOnce: new Set(),
    denyAccess: false,
    sourceDelayMs: 0,
    accessDelayMs: 0,
    cursorDelayMs: 0,
    rows,
  };

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = request.method();
    const location = url.searchParams.has("location_id")
      ? Number(url.searchParams.get("location_id"))
      : null;
    state.requests.push({ method, path: path + url.search, location });

    if (method !== "GET") {
      state.unexpected.push(`${method} ${path}`);
      return fulfill(route, { detail: { code: "BROWSER_MUTATION_FORBIDDEN" } }, 403);
    }

    if (path === "/tenant/identity") {
      return fulfill(route, {
        company_id: 1,
        company_name: "UX Fixture Company",
        company_code: "LIVEUX",
        currency_code: "JOD",
        timezone: "Asia/Amman",
        country_id: null,
        country_name: null,
        display_location: "Amman",
      });
    }

    if (path === "/inventory/access/me") {
      if (state.accessDelayMs > 0) await delay(state.accessDelayMs);
      if (state.denyAccess) {
        return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      }
      const scoped = location !== null;
      return fulfill(route, {
        company_id: 1,
        principal_id: 7,
        backoffice_user_id: 17,
        is_company_owner: true,
        location_id: location,
        permissions: ["inventory.read", "location.read"],
        any_permissions: ["inventory.read", "location.read"],
        location_permissions: scoped ? ["inventory.read", "location.read"] : [],
      });
    }

    if (path === "/warehouse/locations/selection") {
      const selected = Number(url.searchParams.get("selected_location_id") ?? 11);
      return fulfill(route, {
        items: warehouses,
        selected: warehouses.find((w) => w.id === selected) ?? null,
        next_cursor: null,
        has_more: false,
        total: warehouses.length,
      });
    }

    if (path === "/warehouse/setup-status") {
      return fulfill(route, {
        warehouse_ready: true,
        active_warehouse_count: 2,
        accessible_warehouse_count: 2,
        can_create: false,
      });
    }

    if (path === "/warehouse/status") {
      return fulfill(route, {
        status: "ACTIVE",
        stocktake_session_id: null,
        stocktake_reference: null,
        stocktake_status: null,
      });
    }

    if (path === "/warehouse/inventory/summary") {
      state.summaryReads += 1;
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      if (state.failSummaryOnce) {
        state.failSummaryOnce = false;
        return fulfill(route, { detail: { code: "SUMMARY_TEMPORARY" } }, 503);
      }
      return fulfill(route, {
        stock_total: location === 11 ? state.rows : 1,
        alert_count: 0,
      });
    }

    if (path === "/warehouse/inventory/families") {
      state.familyReads += 1;
      const families = [
        { id: 21, name: "Snacks", code: "SN" },
        { id: 22, name: "Drinks", code: "DR" },
      ];
      const search = url.searchParams.get("search")?.toLowerCase();
      return fulfill(route, {
        items: search
          ? families.filter((family) => family.name.toLowerCase().includes(search))
          : families,
        next_cursor: null,
        has_more: false,
      });
    }

    if (path === "/warehouse/inventory/cursor") {
      state.cursorReads += 1;
      if (state.cursorDelayMs > 0) await delay(state.cursorDelayMs);
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      const start = Number(url.searchParams.get("cursor") ?? 0);
      if (state.failCursorAt.has(start)) {
        state.failCursorAt.delete(start);
        return fulfill(route, { detail: { code: "CURSOR_TEMPORARY" } }, 503);
      }
      let results = location === 12
        ? [item(0, 12)]
        : Array.from({ length: state.rows }, (_, index) => item(index));
      const search = url.searchParams.get("search")?.toLowerCase();
      if (search) {
        results = results.filter((row) =>
          row.name.toLowerCase().includes(search) ||
          row.sku.toLowerCase().includes(search));
      }
      const family = url.searchParams.get("family_id");
      if (family === "21") results = results.filter((row) => row.family_name === "Snacks");
      if (family === "22") results = results.filter((row) => row.family_name === "Drinks");
      if (url.searchParams.get("stock_state") === "out_of_stock") results = [];
      const limit = Math.min(
        50,
        Math.max(1, Number(url.searchParams.get("limit") ?? 50)),
      );
      const end = Math.min(results.length, start + limit);
      return fulfill(route, {
        items: results.slice(start, end),
        next_cursor: end < results.length ? String(end) : null,
        has_more: end < results.length,
        total: null,
        alert_count: 0,
        alert_samples: [],
      });
    }

    const batchMatch = path.match(/^\/warehouse\/inventory\/(\d+)\/batches$/);
    if (batchMatch) {
      state.batchReads += 1;
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      return fulfill(route, {
        location_id: location,
        product_variant_id: Number(batchMatch[1]),
        currency_code: "JOD",
        batches,
        next_cursor: null,
        has_more: false,
      });
    }

    const sourceMatch = path.match(
      /^\/warehouse\/inventory\/(\d+)\/batches\/(\d+)\/source$/,
    );
    if (sourceMatch) {
      const batchId = Number(sourceMatch[2]);
      state.sourceReads[batchId] = (state.sourceReads[batchId] ?? 0) + 1;
      if (state.sourceDelayMs > 0) await delay(state.sourceDelayMs);
      if (state.denyAccess) return fulfill(route, { detail: { code: "FORBIDDEN" } }, 403);
      if (state.failSourceBatchOnce.has(batchId)) {
        state.failSourceBatchOnce.delete(batchId);
        return fulfill(route, { detail: { code: "SOURCE_TEMPORARY" } }, 503);
      }
      return fulfill(route, {
        ...source(location ?? 11, batchId),
        product_variant_id: Number(sourceMatch[1]),
      });
    }

    if (options.allowOtherInventoryReads) {
      state.otherReads.push(path);
      return fulfill(route, {
        items: [],
        batches: [],
        next_cursor: null,
        has_more: false,
        total: 0,
      });
    }

    state.unexpected.push(`${method} ${path}`);
    return fulfill(route, { detail: { code: "UNMOCKED_UX_BROWSER_API" } }, 404);
  });

  return state;
}

export const visualCases: Array<{
  name: string;
  locale: Locale;
  theme: Theme;
  width: number;
  height: number;
  mobile: boolean;
}> = [
  { name: "desktop-en-light", locale: "en", theme: "light", width: 1440, height: 900, mobile: false },
  { name: "desktop-ar-dark", locale: "ar", theme: "dark", width: 1440, height: 900, mobile: false },
  { name: "mobile-en-dark", locale: "en", theme: "dark", width: 390, height: 844, mobile: true },
  { name: "mobile-ar-light", locale: "ar", theme: "light", width: 390, height: 844, mobile: true },
  { name: "tablet-en-light", locale: "en", theme: "light", width: 900, height: 760, mobile: false },
];
