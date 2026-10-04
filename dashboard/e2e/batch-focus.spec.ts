import { expect, test } from "playwright/test";

import { createInventoryBatchFocusNavigationState } from "../src/features/inventory/navigation";
import { batchFocusPayload, batchSource, inventoryReadAccess } from "../src/test/fixtures/batchFocus";

// No live API, credentials or mutation requests: only existing read contracts.
const cases = [
  { name: "one warehouse", sources: [batchSource(11, "Readable A")] },
  { name: "two warehouses", sources: [batchSource(11, "Readable A"), batchSource(12, "Readable B")] },
  { name: "warehouse and vehicle", sources: [batchSource(11, "Readable A"), batchSource(13, "Vehicle 13", "VEHICLE")] },
  { name: "vehicle only", sources: [batchSource(13, "Vehicle 13", "VEHICLE")] },
  { name: "hidden second source", sources: [batchSource(11, "Readable A", "WAREHOUSE", false)], restricted: true },
];

for (const locale of ["en", "ar"] as const) for (const scenario of cases) {
  test(`${locale}: ${scenario.name}, wrong saved warehouse, consumed focus`, async ({ page }) => {
    const calls: string[] = [];
    const unexpected: string[] = [];
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(/^\/api/, "");
      calls.push(path);
      const payload = path === "/inventory/access/me" ? inventoryReadAccess(!scenario.restricted)
        : path === "/warehouse/batches/41/stock-sources" ? batchFocusPayload(scenario.sources)
        : path === "/tenant/identity" ? { company_id: 1, company_name: "Browser fixture company", company_code: "FIXTURE",
          currency_code: "JOD", timezone: "Asia/Amman", country_id: null, country_name: null, display_location: "Fixture" } : null;
      if (request.method() !== "GET" || payload === null) {
        unexpected.push(`${request.method()} ${path}`);
        return route.fulfill({ status: 403, json: { code: "TEST_UNEXPECTED_REQUEST", context: {}, request_id: "browser-read-only" } });
      }
      return route.fulfill({ json: payload });
    });
    await page.addInitScript(({ language, intent }) => {
      const refresh = `test.${btoa(JSON.stringify({ type: "refresh", sub: "7", company_id: 1, exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`;
      localStorage.setItem("admin_token", "read-only-browser-fixture");
      localStorage.setItem("refresh_token", refresh);
      localStorage.setItem("company_id", "1"); localStorage.setItem("driver_id", "7");
      localStorage.setItem("inventory_selected_location:1", "999");
      localStorage.setItem("wanasah.language", language);
      // BrowserRouter's typed route state, never a localStorage command bridge.
      history.replaceState({ usr: intent, key: "batch-acceptance", idx: 0 }, "", "/inventory");
    }, { language: locale, intent: createInventoryBatchFocusNavigationState({ batchId: 41, variantId: 118,
      productName: "Untrusted navigation label", locationId: 999 }) });
    await page.goto("/inventory");
    await expect(page.getByRole("heading", { name: "LOT-41", exact: true })).toBeVisible();
    const workspace = page.locator('section[aria-labelledby="batch-focus-heading"]');
    await expect(workspace).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    for (const source of scenario.sources) await expect(workspace.getByText(source.location_name, { exact: true }).last()).toBeVisible();
    await expect(workspace.getByText("Hidden B")).toHaveCount(0);
    await expect(page.getByText("Untrusted navigation label")).toHaveCount(0);
    await expect(page.locator("#batch-focus-heading")).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.tagName)).toBe("BUTTON");
    expect(await page.evaluate(() => history.state.usr)).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem("inventory_selected_location:1"))).toBe("999");
    expect(calls.filter((path) => path === "/warehouse/batches/41/stock-sources")).toHaveLength(1);
    expect(unexpected).toEqual([]);
  });
}
