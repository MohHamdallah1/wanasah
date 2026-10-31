import { expect, test, type Page } from "playwright/test";
import { installLiveStockApi, seedLiveStock, type Locale, type Fixture } from "./live-stock-v1.fixtures";

// Real Chromium on the built production Dashboard; API requests are deterministic,
// explicitly intercepted, fail-closed, and NOT a PostgreSQL/business accounting proof.
const desktop = (page: Page) => page.locator(".live-stock-table");
const mobile = (page: Page) => page.getByTestId("live-stock-mobile-cards");
const stock = (page: Page) => page.locator('[data-cp13-surface="live-stock"]');
const rows = (page: Page) => page.locator(".live-stock-row");
const cards = (page: Page) => page.locator("[data-cp13-stock-card]");
const loadList = async (page: Page) => {
  await page.goto("/inventory");
  await expect(stock(page)).toBeVisible();
  await expect(page.locator("[data-live-authority]")).toBeVisible();
};
const openFirst = async (page: Page) => {
  const open = page.locator('[data-live-stock-product-open="118"]');
  await expect(open).toBeVisible();
  await open.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("LOT-71")).toBeVisible();
};
const noUnexpected = (state: Fixture) => expect(state.unexpected, "unmocked API or mutation").toEqual([]);

for (const locale of ["en", "ar"] as const) {
  test(`${locale}: desktop warehouse selector, authority and keyboard-focusable table`, async ({ page }) => {
    await page.setViewportSize({ width: 1360, height: 900 });
    const state = await installLiveStockApi(page);
    await seedLiveStock(page, locale);
    await loadList(page);
    await expect.poll(() => page.evaluate(() => document.documentElement.dir))
      .toBe(locale === "ar" ? "rtl" : "ltr");
    await expect(desktop(page)).toBeVisible();
    await expect(mobile(page)).toHaveCount(0);
    await expect(rows(page)).toHaveCount(2);
    await expect(rows(page).first()).toContainText("Stock Item 0000");
    const open = page.locator('[data-live-stock-product-open="118"]');
    await open.focus();
    await expect(open).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(open).toBeFocused();

    const select = stock(page).locator(".live-stock-context-select");
    await select.selectOption("12");
    await expect(rows(page)).toHaveCount(1);
    await expect(rows(page).first()).toContainText("Warehouse B Item 0");
    await expect(stock(page).getByText("Stock Item 0000")).toHaveCount(0);
    expect(state.requests.filter((r) => r.path.startsWith("/warehouse/inventory/cursor") &&
      r.location === 12)).not.toHaveLength(0);
    await select.selectOption("11");
    await expect(rows(page).first()).toContainText("Stock Item 0000");
    noUnexpected(state);
  });

  test(`${locale}: mobile actual purchase/average cost, distinct UOM, null, direction`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    const state = await installLiveStockApi(page);
    await seedLiveStock(page, locale);
    await loadList(page);
    await expect.poll(() => page.evaluate(() => document.documentElement.dir))
      .toBe(locale === "ar" ? "rtl" : "ltr");
    await expect(desktop(page)).toHaveCount(0);
    await expect(mobile(page)).toBeVisible();
    await expect(cards(page)).toHaveCount(2);
    const card = cards(page).first();
    const purchase = card.locator('[data-live-stock-mobile-cost="last-purchase"]');
    const average = card.locator('[data-live-stock-mobile-cost="average"]');
    await expect(purchase).toContainText("1.500");
    await expect(average).toContainText("0.125");
    await expect(purchase.locator("[title]").first()).toHaveAttribute("title", /1\.500001/);
    await expect(purchase).toContainText(locale === "ar" ? "لكل حبة" : "per Unit");
    await expect(average).toContainText(locale === "ar" ? "لكل كرتونة" : "per Carton");
    await expect(purchase).not.toContainText(locale === "ar" ? "لكل كرتونة" : "per Carton");
    await expect(average).not.toContainText(locale === "ar" ? "لكل حبة" : "per Unit");
    await expect(purchase).toContainText(locale === "ar" ? "د.أ." : "JOD");
    for (const label of ["on-hand", "available", "reserved", "unavailable", "vehicle"]) {
      await expect(card.locator(`[data-cp13-quantity="${label}"]`)).toHaveCount(1);
    }
    const second = cards(page).nth(1);
    await expect(second.locator('[data-live-stock-mobile-cost="last-purchase"]')).toContainText("—");
    await expect(second.locator('[data-live-stock-mobile-cost="average"]')).toContainText("—");
    await expect(second.locator('[data-live-stock-mobile-cost="last-purchase"]')).not.toContainText("0");
    const clipped = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(clipped, "no body-wide horizontal overflow on mobile").toBe(false);
    noUnexpected(state);
  });
}

test("search, family filter and correct location-scoped response without row leakage", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 840 });
  const state = await installLiveStockApi(page, 80);
  await seedLiveStock(page, "en");
  await loadList(page);
  const search = stock(page).getByRole("searchbox", { name: /search/i }).first();
  await search.fill("Stock Item 0002");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("Stock Item 0002");
  expect(state.requests.some((r) => r.path.includes("search=Stock+Item+0002") ||
    r.path.includes("search=Stock%20Item%200002"))).toBe(true);
  await search.fill("");
  await expect.poll(() => rows(page).count()).toBeGreaterThan(1);
  expect(await rows(page).count()).toBeLessThanOrEqual(40); // viewport-dependent NEW-01 window
  await stock(page).locator(".live-stock-family-button").click();
  await expect(page.locator(".live-stock-family-option").filter({ hasText: "Snacks" })).toBeVisible();
  await page.locator(".live-stock-family-option").filter({ hasText: "Snacks" }).click();
  await expect.poll(() => state.requests.some((r) => /family_id=21/.test(r.path))).toBe(true);
  await expect(rows(page).first()).toContainText("Stock Item 0000");
  expect(await rows(page).allTextContents()).not.toContain("Stock Item 0001");
  noUnexpected(state);
});

test("continuous scroll fetches distinct cursor pages without mounting all accumulated rows", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 900 });
  const state = await installLiveStockApi(page, 200);
  await seedLiveStock(page, "en");
  await loadList(page);
  const list = stock(page).locator("[data-cp13-stock-list]");
  await expect(rows(page).first()).toContainText("Stock Item 0000");
  for (const expectedRequests of [2, 3, 4]) {
    await list.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
      node.dispatchEvent(new Event("scroll"));
    });
    await expect.poll(() => state.cursorReads, { timeout: 10000 })
      .toBeGreaterThanOrEqual(expectedRequests);
    await expect.poll(() => list.evaluate((node) => node.scrollHeight))
      .toBeGreaterThan(0);
  }
  await expect(desktop(page)).toHaveAttribute("aria-rowcount", "201");
  const positions = await rows(page).evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("aria-rowindex")));
  expect(positions.length).toBeGreaterThan(0);
  expect(positions.length).toBeLessThanOrEqual(40);
  expect(new Set(positions).size).toBe(positions.length);
  const ids = await rows(page).locator("[data-live-stock-product-open]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-live-stock-product-open")));
  expect(new Set(ids).size).toBe(ids.length);
  const requested = state.requests.filter((r) => r.path.startsWith("/warehouse/inventory/cursor"));
  expect(requested.some((r) => r.path.includes("cursor=50"))).toBe(true);
  expect(requested.some((r) => r.path.includes("cursor=100"))).toBe(true);
  expect(requested.some((r) => r.path.includes("cursor=150"))).toBe(true);
  noUnexpected(state);
});

test("batch details show bounded partial/truncated owners, quantities and fresh reopening", async ({ page }) => {
  await page.setViewportSize({ width: 1350, height: 850 });
  const state = await installLiveStockApi(page);
  await seedLiveStock(page, "en");
  await loadList(page);
  await openFirst(page);
  const dialog = page.getByRole("dialog");
  const sourceButton = dialog.getByRole("button", { name: "Actionable Warehouse source and reservations" });
  await sourceButton.focus();
  await sourceButton.press("Enter");
  await expect(sourceButton).toHaveAttribute("aria-expanded", "true");
  const known = dialog.getByRole("list", { name: "Known reservations" });
  await expect(known.locator("li")).toHaveCount(2);
  await expect(known).toContainText("RES-9001");
  await expect(known).toContainText("RES-9002");
  await expect(known).toContainText("1 Carton");
  await expect(dialog.getByText("Reservation evidence partial")).toBeVisible();
  await expect(dialog.getByText(/Truncated list:/)).toBeVisible();
  await expect(dialog.getByText(/Unattributed reserved quantity:/)).toContainText("1 Unit");
  await expect(known.locator("a, button")).toHaveCount(0);
  await sourceButton.click();
  await expect(sourceButton).toHaveAttribute("aria-expanded", "false");
  await expect(known).toHaveCount(0);
  await sourceButton.click();
  await expect(known.locator("li")).toHaveCount(2);
  const before = state.requests.filter((r) => r.path.includes("/source?")).length;
  expect(before).toBe(2);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  noUnexpected(state);
});

test("loading, retry, failed source and refresh invalidate old reservation evidence", async ({ page }) => {
  const state = await installLiveStockApi(page);
  state.failCursorOnce = true;
  state.failSourceOnce = true;
  await seedLiveStock(page, "en");
  await page.goto("/inventory");
  await expect(stock(page).locator('[data-cp13-state="error"]')).toBeVisible();
  await stock(page).locator('[data-cp13-state="error"]').getByRole("button", { name: "Retry" }).click();
  await expect(rows(page)).toHaveCount(2);
  await openFirst(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
  await expect(dialog.getByText("Source evidence could not be loaded for this warehouse.")).toBeVisible();
  await expect(dialog.getByText("RES-9001")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Retry" }).click();
  await expect(dialog.getByText("RES-9001")).toBeVisible();
  // A real modal blocks background pointer events; close it before refreshing.
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await stock(page).locator(".live-stock-context-refresh").click();
  await openFirst(page);
  await expect(page.getByRole("dialog").getByText("RES-9001")).toHaveCount(0);
  noUnexpected(state);
});

test("capability revocation and same-tab session switch hide prior warehouse evidence", async ({ page }) => {
  const state = await installLiveStockApi(page);
  await seedLiveStock(page, "en");
  await loadList(page);
  await expect(rows(page)).toHaveCount(2);
  state.denyAccess = true;
  await page.evaluate(() => window.dispatchEvent(new Event("inventory-permission-denied")));
  await expect(rows(page)).toHaveCount(0);
  await expect(stock(page)).toHaveCount(0); // denied access unmounts the entire Live Stock surface
  // A principal/company change cannot reuse the prior session's warmed inventory.
  await page.evaluate(() => {
    localStorage.setItem("company_id", "2");
    window.dispatchEvent(new StorageEvent("storage", {
      key: "company_id", oldValue: "1", newValue: "2",
    }));
  });
  await expect(rows(page)).toHaveCount(0);
  await expect(stock(page).getByText("Stock Item 0000")).toHaveCount(0);
  noUnexpected(state);
});
