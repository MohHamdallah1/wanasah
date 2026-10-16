import { expect, test, type Page, type Route } from "playwright/test";

import {
  createInventoryBatchFocusNavigationState,
  createInventoryTabNavigationState,
} from "../src/features/inventory/navigation";
import {
  batchFocusPayload,
  batchSource,
} from "../src/test/fixtures/batchFocus";

const COMPANY_ID = 1;
const PRINCIPAL_ID = 7;
const BACKOFFICE_USER_ID = 17;
const WAREHOUSE_A = 11;
const WAREHOUSE_B = 12;
const VARIANT_ID = 118;

const tabLabels = {
  ar: {
    live: "الرصيد الحي",
    batches: "الدفعات والصلاحية",
    inbound: "توريد بضاعة",
    transfers: "الحوالات",
    ledger: "سجل الحركات",
    stocktake: "جرد وتسوية",
    warehouses: "إدارة المستودعات",
    permissions: "الصلاحيات",
  },
  en: {
    live: "Live stock",
    batches: "Batches & expiry",
    inbound: "Inbound receipt",
    transfers: "Transfers",
    ledger: "Movement ledger",
    stocktake: "Stocktake & adjustment",
    warehouses: "Warehouse management",
    permissions: "Permissions",
  },
} as const;

type Locale = keyof typeof tabLabels;
type MockOptions = {
  failLiveOnce?: boolean;
};
type MockState = {
  liveCalls: number;
  mutationCalls: string[];
};

const companyPermissions = ["supplier.read", "batch.disposition"];
const locationPermissions = [
  "inventory.read",
  "catalog.read",
  "inbound.create",
  "transfer.read",
  "transfer.send",
  "transfer.destination",
  "ledger.read",
  "stocktake.read",
  "stocktake.start",
  "stocktake.count",
  "stocktake.review",
  "stocktake.recount",
  "stocktake.approve",
  "stocktake.cancel",
  "location.read",
];
const anyPermissions = [...new Set([...locationPermissions, "location.read"])];

const locations = [
  { id: WAREHOUSE_A, name: "Main Warehouse", code: "AMMAN-01" },
  { id: WAREHOUSE_B, name: "Long Secondary Warehouse Label For Responsive Acceptance", code: "AMMAN-02" },
];

const liveProduct = {
  id: VARIANT_ID,
  name: "Device UX Product",
  sku: "UX-118",
  product_id: VARIANT_ID,
  family_name: "UX Family",
  base_uom_id: 7,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  display_uom_id: 7,
  display_uom_code: "EACH",
  display_uom_name: "Each",
  display_factor_to_base: "1",
  currency_code: "JOD",
  average_cost_display: "12.375",
  last_purchase_cost: null,
  last_purchase_uom_code: null,
  last_purchase_date: null,
  quantity_scale: 3,
  quantity_step: "0.001",
  on_hand_quantity: "1234.500",
  reserved_quantity: "34.500",
  available_for_sale_quantity: "1200.000",
  unavailable_quantity: "0",
  vehicle_quantity: "0",
  recalled_quantity: "0",
  available_quantity: "1200.000",
  blocked_quantity: "0",
  total_quantity: "1234.500",
  damaged_quantity: "0",
  minimum_quantity: "100.000",
};

const catalogVariant = {
  id: VARIANT_ID,
  product_id: VARIANT_ID,
  sku: "UX-118",
  gtin: null,
  name: "Device UX Product",
  base_uom: { id: 7, code: "EACH", name: "Each" },
  quantity_scale: 3,
  quantity_step: "0.001",
  lot_control_mode: "REQUIRED",
  expiry_control_mode: "REQUIRED",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 1,
  published_at: "2026-01-01T00:00:00Z",
  retired_at: null,
  archived_at: null,
};

const fulfill = (route: Route, json: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(json) });

function accessPayload(locationId: number | null) {
  return {
    company_id: COMPANY_ID,
    principal_id: PRINCIPAL_ID,
    backoffice_user_id: BACKOFFICE_USER_ID,
    is_company_owner: true,
    location_id: locationId,
    permissions: companyPermissions,
    any_permissions: anyPermissions,
    location_permissions: locationId === null ? [] : locationPermissions,
  };
}

async function seedBrowser(
  page: Page,
  locale: Locale,
  options: {
    activeTab?: string;
    selectedLocation?: number;
    routeState?: unknown;
    draft?: boolean;
    pendingInbound?: boolean;
  } = {},
) {
  await page.addInitScript((input) => {
    const refresh = `test.${btoa(JSON.stringify({
      type: "refresh",
      sub: "7",
      company_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    }))}.test`;
    localStorage.setItem("admin_token", "cp14d-browser-fixture");
    localStorage.setItem("refresh_token", refresh);
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "7");
    localStorage.setItem("backoffice_user_id", "17");
    localStorage.setItem("driver_id", "7");
    localStorage.setItem("wanasah.language", input.locale);
    if (!localStorage.getItem("inventory_active_tab:1") && input.activeTab) {
      localStorage.setItem("inventory_active_tab:1", input.activeTab);
    }
    if (!localStorage.getItem("inventory_selected_location:1")) {
      localStorage.setItem("inventory_selected_location:1", String(input.selectedLocation ?? 11));
    }
    if (input.draft) {
      localStorage.setItem(
        "wanasah:inbound:v6:1:17:11:drafts",
        JSON.stringify({
          "118": [{
            row_id: "cp14d-draft-118",
            quantity: "7.500",
            uom_id: "7",
            unit_cost: "12.375",
            batch_number: "LOT-DRAFT-118",
            production_date: "2026-10-01",
            expiry_date: "2027-10-01",
          }],
        }),
      );
      localStorage.setItem("wanasah:inbound:v6:1:17:11:reference", "REC-DRAFT-118");
      localStorage.setItem(
        "wanasah:inbound:v6:2:99:11:drafts",
        JSON.stringify({
          "118": [{
            row_id: "foreign-draft",
            quantity: "99",
            uom_id: "7",
            unit_cost: "99",
            batch_number: "FOREIGN-CONTEXT",
            production_date: "",
            expiry_date: "",
          }],
        }),
      );
    }
    if (input.pendingInbound) {
      localStorage.setItem(
        "wanasah:inbound:v6:1:17:11:request-id",
        "11111111-1111-4111-8111-111111111111",
      );
      localStorage.setItem(
        "wanasah:inbound:v6:1:17:11:fingerprint",
        JSON.stringify({
          supplier_id: 5,
          location_id: 11,
          reference_id: "REC-LOST-RESPONSE",
          notes: null,
          items: [],
        }),
      );
    }
    if (input.routeState) {
      history.replaceState(
        { usr: input.routeState, key: "cp14d-route", idx: 0 },
        "",
        "/inventory",
      );
    }
  }, {
    locale,
    activeTab: options.activeTab ?? "live",
    selectedLocation: options.selectedLocation ?? WAREHOUSE_A,
    routeState: options.routeState ?? null,
    draft: options.draft ?? false,
    pendingInbound: options.pendingInbound ?? false,
  });
}

async function installApi(page: Page, options: MockOptions = {}): Promise<MockState> {
  const state: MockState = { liveCalls: 0, mutationCalls: [] };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const method = request.method();

    if (path === "/tenant/identity") {
      return fulfill(route, {
        company_id: COMPANY_ID,
        company_name: "CP14-D Browser Company",
        company_code: "CP14D",
        currency_code: "JOD",
        timezone: "Asia/Amman",
        country_id: null,
        country_name: null,
        display_location: "Amman",
      });
    }
    if (path === "/inventory/access/me") {
      const raw = url.searchParams.get("location_id");
      return fulfill(route, accessPayload(raw === null ? null : Number(raw)));
    }
    if (path === "/inventory/access/locations/capabilities" && method === "POST") {
      const body = request.postDataJSON() as { location_ids?: number[] };
      return fulfill(route, {
        locations: Object.fromEntries((body.location_ids ?? []).map((id) => [String(id), locationPermissions])),
      });
    }
    if (path === "/warehouse/locations") {
      return fulfill(route, { items: locations, next_cursor: null, has_more: false, total: locations.length });
    }
    if (path === "/warehouse/setup-status") {
      return fulfill(route, {
        warehouse_ready: true,
        active_warehouse_count: locations.length,
        accessible_warehouse_count: locations.length,
        can_create: false,
      });
    }
    if (path === "/warehouse/status") return fulfill(route, { status: "OPEN" });
    if (path === "/warehouse/inventory/summary") return fulfill(route, { stock_total: 1, alert_count: 0 });
    if (path === "/warehouse/inventory/families") return fulfill(route, { items: [], has_more: false });
    if (path === "/warehouse/inventory/cursor") {
      state.liveCalls += 1;
      if (options.failLiveOnce && state.liveCalls === 1) {
        return fulfill(route, {
          detail: { code: "LIVE_STOCK_TEMPORARY_FAILURE", message: "Temporary CP14-D failure" },
        }, 503);
      }
      return fulfill(route, {
        items: [liveProduct],
        next_cursor: null,
        has_more: false,
        total: 1,
        alert_count: 0,
        alert_samples: [],
      });
    }
    if (path === "/warehouse/unified/transfers") {
      return fulfill(route, { items: [], next_cursor: null, has_more: false, total: 0 });
    }
    if (path === "/warehouse/unified/stocktakes/active") {
      return fulfill(route, { items: [], next_cursor: null, has_more: false, total: 0 });
    }
    if (path === "/warehouse/ledger/cursor") {
      return fulfill(route, { items: [], next_cursor: null, has_more: false, total: 0, available_types: [] });
    }
    if (path === "/warehouse/locations/manage") {
      return fulfill(route, {
        items: locations.map((location) => ({
          ...location,
          branch_id: null,
          branch_name: null,
          is_active: true,
          version: 1,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-10-01T00:00:00Z",
        })),
        next_cursor: null,
        has_more: false,
        total: locations.length,
      });
    }
    if (path === "/inventory/access/roles") {
      return fulfill(route, { items: [{ id: 21, name: "Inventory Reader", permissions: ["inventory.read"], is_system_role: false }], next_id: null });
    }
    if (path === "/inventory/access/users") {
      return fulfill(route, { items: [{ principal_id: 7, backoffice_user_id: 17, full_name: "Browser Operator", is_company_owner: true, is_active: true }], next_id: null });
    }
    if (path === "/inventory/access/locations") {
      return fulfill(route, { items: locations.map((location) => ({ ...location, location_type: "WAREHOUSE", is_active: true })), next_id: null });
    }
    if (path === "/inventory/access/catalog") {
      return fulfill(route, { permissions: [...new Set([...companyPermissions, ...locationPermissions])], company_only: ["supplier.read", "batch.disposition"] });
    }
    if (path === "/catalog/variants" && method === "GET") {
      return fulfill(route, { items: [catalogVariant], next_cursor: null, has_more: false });
    }
    if (path === "/warehouse/inbound/options" && method === "POST") {
      return fulfill(route, {
        currency_code: "JOD",
        items: [{
          product_variant_id: VARIANT_ID,
          base_uom_id: 7,
          uoms: [{ id: 7, code: "EACH", name: "Each", factor_to_base: "1" }],
        }],
      });
    }
    if (path === "/warehouse/costing-policy") {
      return fulfill(route, {
        method: "MOVING_AVERAGE",
        is_selected: true,
        selection_status: "SELECTED",
        selected_at: "2026-01-01T00:00:00Z",
        is_active: true,
        is_locked: true,
        locked_at: "2026-01-01T00:00:00Z",
        version: 1,
        currency_code: "JOD",
        can_change: false,
      });
    }
    if (path === "/suppliers") return fulfill(route, { items: [], next_cursor: null, has_more: false });
    if (path === "/warehouse/batches/41/stock-sources") {
      return fulfill(route, batchFocusPayload([batchSource(WAREHOUSE_A, "Main Warehouse")]));
    }
    if (path.startsWith("/warehouse/inventory/batches/")) {
      const locationId = Number(url.searchParams.get("location_id") ?? WAREHOUSE_A);
      if (path.endsWith("/cursor")) {
        return fulfill(route, { location_id: locationId, items: [], next_cursor: null, has_more: false });
      }
      if (path.endsWith("/summary")) {
        return fulfill(route, {
          location_id: locationId,
          total_batches: 0,
          sellable_batches: 0,
          expiring_soon_batches: 0,
          expired_batches: 0,
          held_batches: 0,
          unavailable_batches: 0,
          damaged_batches: 0,
          disposal_pending_batches: 0,
        });
      }
    }

    if (!["GET", "HEAD", "OPTIONS"].includes(method)) state.mutationCalls.push(`${method} ${path}`);
    return fulfill(route, { detail: { code: "CP14D_UNEXPECTED_REQUEST", message: `${method} ${path}` } }, 404);
  });
  return state;
}

async function gotoInventory(page: Page) {
  await page.goto("/inventory");
  await expect(page.getByRole("tablist")).toBeVisible();
}

async function selectedTab(page: Page, name: string) {
  const tab = page.getByRole("tab", { name, exact: true });
  await expect(tab).toHaveAttribute("aria-selected", "true");
  return tab;
}

async function pressDockKey(page: Page, from: string, key: string, expected: string) {
  const current = page.getByRole("tab", { name: from, exact: true });
  await current.focus();
  await expect(current).toBeFocused();
  await page.keyboard.press(key);
  return selectedTab(page, expected);
}

async function formValueCount(page: Page, value: string) {
  return page.locator("input, textarea").evaluateAll(
    (nodes, expected) => nodes.filter((node) => (node as HTMLInputElement | HTMLTextAreaElement).value === expected).length,
    value,
  );
}

for (const locale of ["ar", "en"] as const) {
  test(`${locale}: desktop direction, labels, Western digits, roving keyboard and focus`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installApi(page);
    await seedBrowser(page, locale);
    await gotoInventory(page);

    const expectedDir = locale === "ar" ? "rtl" : "ltr";
    await expect.poll(() => page.evaluate(() => document.documentElement.dir)).toBe(expectedDir);
    const tablist = page.getByRole("tablist");
    await expect.poll(() => tablist.evaluate((node) => getComputedStyle(node).direction)).toBe(expectedDir);

    for (const label of Object.values(tabLabels[locale])) {
      const tab = page.getByRole("tab", { name: label, exact: true });
      await expect(tab).toBeVisible();
      await expect(tab).toHaveCount(1);
    }
    const active = await selectedTab(page, tabLabels[locale].live);
    await active.focus();
    await expect(active).toBeFocused();
    await expect.poll(() => active.evaluate((node) => node.matches(":focus-visible"))).toBe(true);

    const afterRight = locale === "ar" ? tabLabels[locale].permissions : tabLabels[locale].batches;
    await pressDockKey(page, tabLabels[locale].live, "ArrowRight", afterRight);
    await pressDockKey(page, afterRight, "Home", tabLabels[locale].live);
    await pressDockKey(page, tabLabels[locale].live, "End", tabLabels[locale].permissions);
    await pressDockKey(
      page,
      tabLabels[locale].permissions,
      "ArrowLeft",
      locale === "ar" ? tabLabels[locale].live : tabLabels[locale].warehouses,
    );

    const focused = page.locator(":focus");
    await focused.press("Tab");
    await page.keyboard.press("Shift+Tab");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText).toMatch(/[0-9]/);
    expect(bodyText).not.toMatch(/[\u0660-\u0669\u06f0-\u06f9]/);
    if (locale === "en") expect(bodyText).not.toMatch(/[\u0600-\u06ff]/);
    else expect(bodyText).toMatch(/[\u0600-\u06ff]/);

    const navigationName = locale === "ar" ? "التنقل الرئيسي" : "Main navigation";
    const sidebarNavigation = page.getByRole("navigation", { name: navigationName, exact: true });
    await expect(sidebarNavigation).toHaveCount(1);
    await expect(sidebarNavigation).toHaveAttribute("aria-label", navigationName);
    const pseudoContent = await sidebarNavigation.evaluate((node) => getComputedStyle(node, "::before").content);
    expect(pseudoContent).not.toBe(`"${navigationName}"`);
    await expect(page.getByText(navigationName, { exact: true })).toHaveCount(0);

    const unnamedButtons = await page.locator("button:visible").evaluateAll((buttons) =>
      buttons.filter((button) => !(
        button.getAttribute("aria-label")
        ?? button.getAttribute("title")
        ?? button.textContent
        ?? ""
      ).trim()).length,
    );
    expect(unnamedButtons).toBe(0);

    for (const icon of await page.locator(".inventory-top-dock__icon").all()) {
      await expect.poll(() => icon.evaluate((node) => getComputedStyle(node).transform)).toBe("none");
    }
  });
}

test("keyboard activates representative Inventory surfaces with Enter and Space", async ({ page }) => {
  await installApi(page);
  await seedBrowser(page, "en");
  await gotoInventory(page);

  const transfers = page.getByRole("tab", { name: tabLabels.en.transfers, exact: true });
  await transfers.focus();
  await page.keyboard.press("Enter");
  await selectedTab(page, tabLabels.en.transfers);
  await expect(page.locator(".inventory-transfers")).toBeVisible();

  const stocktake = page.getByRole("tab", { name: tabLabels.en.stocktake, exact: true });
  await stocktake.focus();
  await page.keyboard.press("Space");
  await selectedTab(page, tabLabels.en.stocktake);
  await expect(page.locator(".inventory-stocktake")).toBeVisible();

  await page.getByRole("tab", { name: tabLabels.en.ledger, exact: true }).click();
  await expect(page.locator(".inventory-ledger")).toBeVisible();
  await page.getByRole("tab", { name: tabLabels.en.warehouses, exact: true }).click();
  await expect(page.locator(".inventory-locations")).toBeVisible();
  await page.getByRole("tab", { name: tabLabels.en.permissions, exact: true }).click();
  await expect(page.locator(".inventory-access")).toBeVisible();
});

test("Batch focus is direct, accessible, modal focus-safe, Escape-closeable and returns focus", async ({ page }) => {
  await installApi(page);
  await seedBrowser(page, "ar", {
    routeState: createInventoryBatchFocusNavigationState({
      batchId: 41,
      variantId: VARIANT_ID,
      productName: "Untrusted browser label",
      locationId: 999,
    }),
  });
  await page.goto("/inventory");

  const heading = page.locator("#batch-focus-heading");
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused();
  const workspace = page.locator('section[aria-labelledby="batch-focus-heading"]');
  await expect(workspace).toHaveAttribute("dir", "rtl");
  await expect(workspace.getByText("LOT-41", { exact: true })).toBeVisible();
  await expect(page.getByText("Untrusted browser label")).toHaveCount(0);
  expect(await page.evaluate(() => history.state.usr)).toBeNull();

  const changeDisposition = workspace.getByRole("button", { name: "مراجعة قرار الدفعة", exact: true });
  await expect(changeDisposition).toBeVisible();
  await changeDisposition.focus();
  await changeDisposition.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  const labelledBy = await dialog.getAttribute("aria-labelledby");
  expect(labelledBy).toBeTruthy();
  await expect(dialog).toHaveAccessibleName(/.+/);
  await expect.poll(() => dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);

  for (let i = 0; i < 6; i += 1) await page.keyboard.press("Tab");
  await expect.poll(() => dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(changeDisposition).toBeFocused();
});

test("direct tab navigation, Warehouse restoration and refresh are mutation-free; stale state fails safe", async ({ page }) => {
  const api = await installApi(page);
  await seedBrowser(page, "en", {
    selectedLocation: WAREHOUSE_B,
    routeState: createInventoryTabNavigationState("transfers", WAREHOUSE_B),
  });
  await gotoInventory(page);
  await selectedTab(page, tabLabels.en.transfers);
  await expect(page.getByLabel("Selected warehouse")).toHaveValue(String(WAREHOUSE_B));
  expect(await page.evaluate(() => history.state.usr)).toBeNull();
  expect(api.mutationCalls).toEqual([]);

  await page.reload();
  await selectedTab(page, tabLabels.en.transfers);
  await expect(page.getByLabel("Selected warehouse")).toHaveValue(String(WAREHOUSE_B));
  expect(api.mutationCalls).toEqual([]);

  await page.evaluate(() => {
    history.replaceState(
      { usr: { inventoryNavigation: { version: 1, kind: "tab", tab: "not-a-tab", locationId: 11 } }, key: "stale", idx: 0 },
      "",
      "/inventory",
    );
  });
  await page.reload();
  await expect(page.getByRole("tablist")).toBeVisible();
  await expect(page.locator('[role="tab"][aria-selected="true"]')).toHaveCount(1);
  expect(api.mutationCalls).toEqual([]);
});

test("Live Stock failure is explicit, stale data is not authoritative and retry recovers", async ({ page }) => {
  const api = await installApi(page, { failLiveOnce: true });
  await seedBrowser(page, "en");
  await gotoInventory(page);

  const alert = page.getByRole("alert").filter({ has: page.getByRole("button", { name: /retry/i }) }).first();
  await expect(alert).toBeVisible();
  await expect(page.getByText("Device UX Product", { exact: true })).toHaveCount(0);
  await alert.getByRole("button", { name: /retry/i }).click();
  await expect(page.getByText("Device UX Product", { exact: true }).first()).toBeVisible();
  expect(api.liveCalls).toBeGreaterThanOrEqual(2);
});

test("Inbound draft survives recoverable reload, stays company/actor/Warehouse scoped and exposes offline state", async ({ page, context }) => {
  await installApi(page);
  await seedBrowser(page, "en", { activeTab: "inbound", draft: true });
  await gotoInventory(page);
  await selectedTab(page, tabLabels.en.inbound);
  await expect.poll(() => formValueCount(page, "LOT-DRAFT-118")).toBe(1);
  await expect.poll(() => formValueCount(page, "7.500")).toBeGreaterThan(0);
  await expect(page.getByText("FOREIGN-CONTEXT")).toHaveCount(0);

  await page.reload();
  await expect.poll(() => formValueCount(page, "LOT-DRAFT-118")).toBe(1);
  await expect.poll(() => formValueCount(page, "REC-DRAFT-118")).toBe(1);

  await page.getByLabel("Selected warehouse").selectOption(String(WAREHOUSE_B));
  await expect.poll(() => formValueCount(page, "LOT-DRAFT-118")).toBe(0);
  await expect(page.getByText("FOREIGN-CONTEXT")).toHaveCount(0);

  await page.getByLabel("Selected warehouse").selectOption(String(WAREHOUSE_A));
  await expect.poll(() => formValueCount(page, "LOT-DRAFT-118")).toBe(1);
  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.locator(".inventory-inbound").getByRole("status").first()).toBeVisible();
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
});

test("Inbound lost-response state exposes a single durable retry and does not duplicate mutation automatically", async ({ page }) => {
  const api = await installApi(page);
  await seedBrowser(page, "en", { activeTab: "inbound", pendingInbound: true });
  await gotoInventory(page);
  await selectedTab(page, tabLabels.en.inbound);

  const pending = page.locator(".inventory-inbound").getByRole("alert").filter({ has: page.getByRole("button", { name: /retry/i }) }).first();
  await expect(pending).toBeVisible();
  await expect(pending.getByRole("button", { name: /retry/i })).toHaveCount(1);
  expect(api.mutationCalls.filter((value) => value.includes("/warehouse/inbound"))).toEqual([]);
  await page.reload();
  await expect(page.locator(".inventory-inbound").getByRole("alert").filter({ has: page.getByRole("button", { name: /retry/i }) }).first()).toBeVisible();
  expect(api.mutationCalls.filter((value) => value.includes("/warehouse/inbound"))).toEqual([]);
});

for (const locale of ["ar", "en"] as const) {
  test(`${locale}: narrow phone keeps critical actions reachable and intentional table overflow contained`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installApi(page);
    await seedBrowser(page, locale);
    await gotoInventory(page);

    await expect.poll(() => page.evaluate(() => ({
      pageWidth: document.scrollingElement?.scrollWidth ?? 0,
      viewport: innerWidth,
    }))).toMatchObject({ viewport: 390 });
    expect(await page.evaluate(() => (document.scrollingElement?.scrollWidth ?? 0) <= innerWidth + 2)).toBe(true);

    const search = page.getByRole("searchbox").first();
    await expect(search).toBeVisible();
    const searchBox = await search.boundingBox();
    expect(searchBox?.width ?? 0).toBeGreaterThan(120);

    await page.getByRole("tab", { name: tabLabels[locale].inbound, exact: true }).click();
    await expect(page.locator(".inventory-inbound")).toBeVisible();
    const inboundScroll = page.locator(".inventory-inbound .overflow-auto").first();
    await expect(inboundScroll).toBeVisible();
    const overflow = await inboundScroll.evaluate((node) => ({ client: node.clientWidth, scroll: node.scrollWidth }));
    expect(overflow.scroll).toBeGreaterThan(overflow.client);
    expect(await page.evaluate(() => (document.scrollingElement?.scrollWidth ?? 0) <= innerWidth + 2)).toBe(true);

    const activeTab = page.getByRole("tab", { name: tabLabels[locale].inbound, exact: true });
    const target = await activeTab.boundingBox();
    expect(target?.height ?? 0).toBeGreaterThanOrEqual(36);
  });
}

test("narrow phone Batch dialog fits viewport and retains accessible close semantics", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installApi(page);
  await seedBrowser(page, "en", {
    routeState: createInventoryBatchFocusNavigationState({ batchId: 41, variantId: VARIANT_ID, productName: "Browser fixture", locationId: WAREHOUSE_A }),
  });
  await page.goto("/inventory");
  const workspace = page.locator('section[aria-labelledby="batch-focus-heading"]');
  const changeDisposition = workspace.getByRole("button", { name: "Review batch decision", exact: true });
  await expect(changeDisposition).toBeVisible();
  await changeDisposition.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 0) >= -1 && (box?.y ?? 0) >= -1).toBe(true);
  expect((box?.width ?? 9999) <= 390 + 2).toBe(true);
  expect((box?.height ?? 9999) <= 844 + 2).toBe(true);
  await expect(dialog.getByRole("button", { name: /close/i })).toBeVisible();
});