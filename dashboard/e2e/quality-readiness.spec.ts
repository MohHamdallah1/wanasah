import { expect, test } from "playwright/test";

import { createInventoryWholeProductIssueNavigationState } from "../src/features/inventory/navigation";
import { resources } from "../src/i18n/resources";
import { inventoryReadAccess } from "../src/test/fixtures/batchFocus";
import { productQualityPage } from "../src/test/fixtures/productQuality";

for (const locale of ["ar", "en"] as const) for (const ready of [false, true]) {
  test(`${locale}: server ready=${ready}, keyboard entry/back and Western digits`, async ({ page }) => {
    const copy = resources[locale].translation;
    const unexpected: string[] = [];
    const reads: string[] = [];
    let closed = false;
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace(/^\/api/, "");
      const response = path === "/inventory/access/me" ? inventoryReadAccess()
        : path === "/warehouse/variants/118/quality-issue-sources" ? { ...productQualityPage(ready ? [] : undefined),
          ready_to_resume_sales: ready, company_requirements_remaining: !ready }
        : path === "/tenant/identity" ? { company_id: 1, company_name: "Fixture", company_code: "FIXTURE",
          currency_code: "JOD", timezone: "Asia/Amman", country_id: null, country_name: null, display_location: "Fixture" } : null;
      if (request.method() !== "GET" || response === null) {
        if (!closed) unexpected.push(`${request.method()} ${path}`);
        return route.fulfill({ status: 403, json: { code: "TEST_UNEXPECTED_REQUEST", context: {}, request_id: "quality-read-only" } });
      }
      reads.push(path);
      return route.fulfill({ json: response });
    });
    await page.addInitScript(({ language, intent }) => {
      const refresh = `test.${btoa(JSON.stringify({ type: "refresh", sub: "7", company_id: 1, exp: Math.floor(Date.now() / 1000) + 3600 }))}.test`;
      localStorage.setItem("admin_token", "read-only-browser-fixture");
      localStorage.setItem("refresh_token", refresh);
      localStorage.setItem("company_id", "1"); localStorage.setItem("driver_id", "7");
      localStorage.setItem("inventory_selected_location:1", "999");
      localStorage.setItem("wanasah.language", language);
      history.replaceState({ usr: intent, key: "quality-acceptance", idx: 0 }, "", "/inventory");
    }, { language: locale, intent: createInventoryWholeProductIssueNavigationState({ variantId: 118, productName: "Fixture product", locationId: 999 }) });
    await page.goto("/inventory");
    const workspace = page.locator('section[aria-labelledby="product-quality-heading"]');
    const readiness = copy.inventoryQualityIssue.readiness;
    await expect(workspace.getByRole("status")).toContainText(ready ? readiness.readyTitle : readiness.pendingTitle);
    await expect(workspace.getByRole("status")).toContainText(ready ? readiness.readyHint : readiness.pendingHint);
    await expect(workspace).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
    await expect(workspace.getByText(copy.inventoryQualityIssue.companyHoldTitle, { exact: true })).toBeVisible();
    if (!ready) for (const name of ["Warehouse A", "Warehouse C", "Vehicle 13"]) await expect(workspace.getByText(name, { exact: true })).toBeVisible();
    expect(await workspace.textContent()).not.toMatch(/[٠-٩۰-۹]/);
    await expect(workspace.getByRole("button", { name: copy.inventoryBatches.quantityActions.openTransfers, exact: true })).toHaveCount(0);
    await expect(workspace.getByRole("button", { name: copy.catalogLifecycle.actions.closeRecall, exact: true })).toHaveCount(0);
    await expect(page.locator("#product-quality-heading")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(workspace.getByRole("button", { name: copy.batchFocus.back, exact: true })).toBeFocused();
    expect(await page.evaluate(() => history.state.usr)).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem("inventory_selected_location:1"))).toBe("999");
    expect(reads.filter((path) => path.includes("quality-issue-sources"))).toHaveLength(1);
    expect(unexpected).toEqual([]);
    // The returning warehouse shell is outside this read-only quality harness.
    closed = true;
    await page.keyboard.press("Enter");
    await expect(workspace).toHaveCount(0);
    expect(await page.evaluate(() => history.state.usr)).toBeNull();
  });
}
