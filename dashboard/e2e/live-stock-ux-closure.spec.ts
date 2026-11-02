import { expect, test, type Page, type TestInfo } from "playwright/test";
import {
  installUxApi,
  visualCases,
  seedUx,
  type UxFixture,
} from "./live-stock-ux-closure.fixtures";

const stock = (page: Page) => page.locator('[data-cp13-surface="live-stock"]');
const rows = (page: Page) => page.locator(".live-stock-row");
const cards = (page: Page) => page.locator("[data-cp13-stock-card]");
const list = (page: Page) => stock(page).locator("[data-cp13-stock-list]");
const sentinel = (page: Page) => stock(page).locator('[data-cp13-continuation="cursor"]');

const openProduct = async (page: Page, id = 118) => {
  const button = page.locator(`[data-live-stock-product-open="${id}"]`);
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.getByRole("dialog")).toBeVisible();
};

const loadLive = async (page: Page) => {
  await page.goto("/inventory");
  await expect(stock(page)).toBeVisible();
  await expect(rows(page).first().or(cards(page).first())).toBeVisible();
};

const assertNoUnexpected = (state: UxFixture) =>
  expect(state.unexpected, "unmocked API or mutation").toEqual([]);

const capture = async (page: Page, testInfo: TestInfo, name: string) => {
  await page.screenshot({
    path: testInfo.outputPath(`${name}.png`),
    fullPage: true,
  });
};


// Real Chromium verifies the geometry, not merely the logical source string.
for (const locale of ["ar", "en"] as const) {
  for (const mobile of [false, true]) {
    test("commercial quantity visual order " + locale + (mobile ? " mobile" : " desktop"), async ({ page }) => {
      await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
      const state = await installUxApi(page, 12);
      await seedUx(page, locale);
      await loadLive(page);
      const cell = mobile
        ? cards(page).first().locator('[data-cp13-quantity="on-hand"]')
        : rows(page).first().locator('[data-cp13-quantity="on-hand"]');
      const qty = cell.locator("[data-commercial-quantity]");
      await expect(qty).toHaveAttribute("dir", locale === "ar" ? "rtl" : "ltr");
      await expect(qty.locator("[data-quantity-part]")).toHaveCount(2);
      await expect(qty.locator("[data-quantity-number]").first()).toHaveText("3");
      await expect(qty.locator("[data-quantity-number]").last()).toHaveText("2");
      const positions = await qty.evaluate((element) => {
        const center = (node: Element) => {
          const rect = node.getBoundingClientRect();
          return rect.left + rect.width / 2;
        };
        const part = [...element.querySelectorAll("[data-quantity-part]")];
        const numbers = [...element.querySelectorAll("[data-quantity-number]")];
        const units = [...element.querySelectorAll("[data-quantity-unit]")];
        const join = element.querySelector("[data-quantity-join]");
        if (part.length !== 2 || numbers.length !== 2 || units.length !== 2 || !join) return null;
        return [center(part[0]), center(join), center(part[1]), center(numbers[0]), center(units[0]), center(numbers[1]), center(units[1])];
      });
      expect(positions).not.toBeNull();
      const [first, plus, second, n0, u0, n1, u1] = positions!;
      if (locale === "ar") {
        expect(first).toBeGreaterThan(plus);
        expect(plus).toBeGreaterThan(second);
        expect(n0).toBeGreaterThan(u0);
        expect(n1).toBeGreaterThan(u1);
      } else {
        expect(first).toBeLessThan(plus);
        expect(plus).toBeLessThan(second);
        expect(n0).toBeLessThan(u0);
        expect(n1).toBeLessThan(u1);
      }
      assertNoUnexpected(state);
    });
  }
}

for (const entry of visualCases) {
  test(`visual/accessibility ${entry.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: entry.width, height: entry.height });
    const state = await installUxApi(page, 90);
    await seedUx(page, entry.locale, entry.theme);
    await loadLive(page);
    // The Dashboard uses Tailwind's class-based dark contract. Apply the
    // existing root theme contract after the app has mounted, then capture the
    // actual built UI under that mode.
    await page.evaluate((theme) => {
      document.documentElement.classList.toggle("dark", theme === "dark");
    }, entry.theme);

    await expect.poll(() => page.evaluate(() => document.documentElement.dir))
      .toBe(entry.locale === "ar" ? "rtl" : "ltr");
    if (entry.theme === "dark") {
      await expect(page.locator("html")).toHaveClass(/dark/);
    } else {
      await expect(page.locator("html")).not.toHaveClass(/dark/);
    }

    const search = stock(page).getByRole("searchbox").first();
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute("aria-label", /.+/);
    await expect(stock(page).locator(".live-stock-filter-button")).toHaveAttribute("aria-label", /.+/);
    await expect(stock(page).locator(".live-stock-family-button")).toHaveAttribute("aria-label", /.+/);
    await expect(stock(page).locator(".live-stock-context-select")).toHaveAttribute("aria-label", /.+/);

    // The initial-only verification message is deliberately not visible;
    // authorization and warm-cache protections are tested independently.
    await expect(page.locator('[data-live-authority="loadingVerification"]')).toHaveCount(0);

    if (entry.mobile) {
      await expect(cards(page).first()).not.toContainText("SKU-118");
      await expect(cards(page).first()).toBeVisible();
      await expect(page.locator(".live-stock-table")).toHaveCount(0);
      expect(await cards(page).count()).toBeLessThanOrEqual(40);
    } else {
      await expect(page.locator(".live-stock-table")).toBeVisible();
      await expect(rows(page).first()).not.toContainText("SKU-118");
      await expect(rows(page).first().locator(".live-family-name")).toHaveCSS("text-align", "center");
      const widths = await page.locator(".live-product-heading, .live-family-heading").evaluateAll(
        (nodes) => nodes.map((node) => node.getBoundingClientRect().width),
      );
      expect(widths[0]).toBeGreaterThan(widths[1]);
      expect(await rows(page).count()).toBeLessThanOrEqual(40);
    }

    await search.focus();
    await expect(search).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");

    if (entry.name === "tablet-en-light") {
      await page.evaluate(() => {
        document.body.style.zoom = "2";
      });
      await expect(search).toBeVisible();
      await stock(page).locator(".live-stock-filter-button").focus();
      await expect(stock(page).locator(".live-stock-filter-button")).toBeFocused();
      await page.evaluate(() => {
        document.body.style.zoom = "";
      });
    }

    await capture(page, testInfo, entry.name);
    assertNoUnexpected(state);
  });
}

for (const locale of ["en", "ar"] as const) {
  test(`G06 stable shell on first admission and delayed Live Stock query (${locale})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const state = await installUxApi(page, 30);
    state.accessDelayMs = 900;
    state.cursorDelayMs = 1200;
    await seedUx(page, locale);
    await page.goto("/inventory");

    // The first frame preserves the same dock and list region without showing
    // unauthorized data or a full-page technical spinner.
    await expect(page.locator(".workspace-top-bar-frame")).toBeVisible();
    await expect(page.locator("[data-inventory-dock-loading]")).toBeVisible();
    const pending = page.locator("[data-inventory-pending-surface]");
    await expect(pending).toBeVisible();
    await expect(rows(page)).toHaveCount(0);

    // Authorization may finish while the stock cursor is still in flight.
    // The real table header is already in place; rows must come from the new read.
    await expect(stock(page)).toBeVisible();
    await expect(stock(page).locator(".live-stock-table")).toBeVisible();
    await expect(stock(page).locator(".live-stock-table thead th").first()).toBeVisible();
    expect(await rows(page).count()).toBe(0);
    await expect(rows(page).first()).toBeVisible();
    await expect(page.locator("[data-inventory-pending-surface]")).toHaveCount(0);
    await expect(page.locator('[data-live-authority="warmUnverified"]')).toHaveCount(0);
    assertNoUnexpected(state);
  });
}

test("one search/filter/family experience resets coherently and keeps accessible selection", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 850 });
  const state = await installUxApi(page, 160);
  await seedUx(page, "en");
  await loadLive(page);

  const search = stock(page).getByRole("searchbox").first();
  await search.fill("Stock Item 0002");
  await expect(rows(page)).toHaveCount(1);

  const familyTrigger = stock(page).locator(".live-stock-family-button");
  await familyTrigger.focus();
  await page.keyboard.press("Enter");
  const snacks = page.locator(".live-stock-family-option").filter({ hasText: "Snacks" });
  await expect(snacks).toBeVisible();
  await snacks.focus();
  await page.keyboard.press("Enter");
  await expect(familyTrigger).toHaveAttribute("aria-label", /Snacks/);

  const filterTrigger = stock(page).locator(".live-stock-filter-button");
  await filterTrigger.click();
  const reserved = page.locator(".live-stock-filter-chip").first();
  await reserved.focus();
  await page.keyboard.press("Enter");
  await expect(reserved).toHaveAttribute("aria-pressed", "true");

  await expect(filterTrigger.locator(".live-stock-filter-count")).toHaveText("3");
  await page.locator(".live-stock-filter-reset").click();

  await expect(search).toHaveValue("");
  await expect(familyTrigger).not.toHaveClass(/--active/);
  await expect(filterTrigger.locator(".live-stock-filter-count")).toHaveCount(0);
  await expect(page.locator(".live-stock-filter-chip[data-active=true]")).toHaveCount(0);
  await expect(page.locator(".live-stock-pagination")).toHaveCount(0);
  await expect.poll(() =>
    state.requests.some((request) =>
      request.path.startsWith("/warehouse/inventory/cursor") &&
      !request.path.includes("search=") &&
      !request.path.includes("family_id=")),
  ).toBe(true);
  assertNoUnexpected(state);
});

test("2050 variable-height rows keep stable cursor continuation, selected family and bounded DOM", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 860 });
  const state = await installUxApi(page, 2050);
  await seedUx(page, "en");
  await loadLive(page);

  const familyTrigger = stock(page).locator(".live-stock-family-button");
  await familyTrigger.click();
  const snacks = page.locator(".live-stock-family-option").filter({ hasText: "Snacks" });
  await snacks.click();
  await expect(familyTrigger).toHaveAttribute("aria-label", /Snacks/);
  await expect.poll(() =>
    state.requests.some((request) =>
      request.path.startsWith("/warehouse/inventory/cursor") &&
      request.path.includes("family_id=21")),
  ).toBe(true);
  // Wait for the first filtered response to be applied. The request is
  // observable before React receives next_cursor, so checking the sentinel
  // closes that race without weakening cursor assertions.
  await expect(sentinel(page)).toHaveAttribute("aria-hidden", "false");

  const familyCursorRequests = () => state.requests.filter((request) =>
    request.path.startsWith("/warehouse/inventory/cursor") &&
    request.path.includes("family_id=21"));

  // 2050 fixture rows contain 1025 Snacks variants. At 50 rows/page that is
  // exactly 21 filtered requests (initial + 20 continuations).
  const expectedFamilyRequestCount = 21;
  let guard = 0;
  while (familyCursorRequests().length < expectedFamilyRequestCount) {
    guard += 1;
    expect(guard, "cursor continuation must terminate").toBeLessThan(30);
    const beforeFamilyReads = familyCursorRequests().length;
    await list(page).evaluate((node) => {
      node.scrollTop = 0;
      node.dispatchEvent(new Event("scroll"));
    });
    await page.waitForTimeout(20);
    await list(page).evaluate((node) => {
      node.scrollTop = node.scrollHeight;
      node.dispatchEvent(new Event("scroll"));
    });
    await expect.poll(
      () => familyCursorRequests().length,
      { timeout: 10000 },
    ).toBeGreaterThan(beforeFamilyReads);
  }
  await expect(sentinel(page)).toHaveAttribute("aria-hidden", "true");

  const familyRequests = familyCursorRequests();
  const cursors = familyRequests.map((request) =>
    new URL(request.path, "http://fixture").searchParams.get("cursor"));
  expect(cursors[0]).toBeNull();
  expect(cursors.slice(1)).toEqual(
    Array.from({ length: 20 }, (_, index) => String((index + 1) * 50)),
  );
  expect(new Set(cursors.slice(1)).size).toBe(cursors.length - 1);

  const mounted = await rows(page).count();
  expect(mounted).toBeGreaterThan(0);
  expect(mounted).toBeLessThanOrEqual(45);
  const heights = await rows(page).evaluateAll((nodes) =>
    nodes.map((node) => Math.round(node.getBoundingClientRect().height)));
  expect(new Set(heights).size, "actual Chromium rows must have variable heights").toBeGreaterThan(1);

  const ariaRows = await rows(page).evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("aria-rowindex")));
  expect(new Set(ariaRows).size).toBe(ariaRows.length);
  const visibleNumbers = await rows(page).locator(".live-stock-row-number").allTextContents();
  expect(Number(visibleNumbers[0].replace(/,/g, ""))).toBeGreaterThan(1);
  await expect(familyTrigger).toHaveAttribute("aria-label", /Snacks/);
  assertNoUnexpected(state);
});

test("multi-batch source evidence alternates, retries, revalidates and invalidates on refresh", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 860 });
  const state = await installUxApi(page, 80);
  state.sourceDelayMs = 120;
  state.failSourceBatchOnce.add(72);
  await seedUx(page, "en");
  await loadLive(page);
  await openProduct(page);

  const dialog = page.getByRole("dialog");
  const articles = dialog.locator("article");
  await expect(articles).toHaveCount(2);
  await expect(articles.nth(0)).toContainText("LOT-71");
  await expect(articles.nth(1)).toContainText("LOT-72");

  await articles.nth(0).getByRole("button", { name: "Additional stock and reservation details" }).click();
  const source71 = articles.nth(0).getByRole("button", { name: "Stock and reservation details", exact: true });
  await source71.focus();
  await page.keyboard.press("Enter");
  await expect(articles.nth(0).getByRole("status")).toContainText("Loading source evidence");
  await expect(articles.nth(0).getByText("Reservation evidence partial")).toBeVisible();
  await expect(articles.nth(0).getByText("Not reserved")).toBeVisible();
  await expect(articles.nth(0).getByText(/Unattributed reserved quantity:/)).toBeVisible();

  await articles.nth(1).getByRole("button", { name: "Additional stock and reservation details" }).click();
  const source72 = articles.nth(1).getByRole("button", { name: "Stock and reservation details", exact: true });
  await source72.click();
  await expect(articles.nth(0).getByText("RES-9001")).toHaveCount(0);
  await expect(articles.nth(1).getByRole("alert")).toContainText(
    "Source evidence could not be loaded",
  );
  await articles.nth(1).getByRole("button", { name: "Retry" }).click();
  await expect(articles.nth(1).getByText("RES-9010")).toBeVisible();
  await expect(articles.nth(1).getByText("Not reserved")).toBeVisible();

  await source71.click();
  await expect(articles.nth(0).getByText("RES-9001")).toBeVisible();
  expect(state.sourceReads[71]).toBe(2);
  expect(state.sourceReads[72]).toBe(2);

  // Refresh through the real user path: close the modal, refresh the list,
  // reopen bounded batch detail, then reopen source evidence. This proves no
  // previously opened source is presented as freshly verified after refresh.
  const batchReadsBeforeRefresh = state.batchReads;
  const source71ReadsBeforeRefresh = state.sourceReads[71] ?? 0;
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const cursorReadsBeforeRefresh = state.cursorReads;
  await stock(page).locator(".live-stock-context-refresh").click();
  await expect.poll(() => state.cursorReads).toBeGreaterThan(cursorReadsBeforeRefresh);

  await openProduct(page);
  await expect.poll(() => state.batchReads).toBeGreaterThan(batchReadsBeforeRefresh);
  const refreshedDialog = page.getByRole("dialog");
  await expect(refreshedDialog.locator("article")).toHaveCount(2);
  await expect(refreshedDialog.getByText("RES-9001")).toHaveCount(0);
  await expect(refreshedDialog.getByText("RES-9010")).toHaveCount(0);

  await refreshedDialog.locator("article").nth(0)
    .getByRole("button", { name: "Additional stock and reservation details" }).click();
  const refreshedSource71 = refreshedDialog
    .locator("article")
    .nth(0)
    .getByRole("button", { name: "Stock and reservation details", exact: true });
  await refreshedSource71.click();
  await expect.poll(() => state.sourceReads[71] ?? 0)
    .toBeGreaterThan(source71ReadsBeforeRefresh);
  await expect(refreshedDialog.getByText("RES-9001")).toBeVisible();
  assertNoUnexpected(state);
});

test("summary and continuation failures stay local; retry preserves rows; revocation clears disclosure", async ({ page }) => {
  await page.setViewportSize({ width: 1360, height: 860 });
  const state = await installUxApi(page, 130);
  state.failSummaryOnce = true;
  state.failCursorAt.add(50);
  await seedUx(page, "en");
  await page.goto("/inventory");

  await expect(stock(page)).toBeVisible();
  await expect(rows(page).first()).toBeVisible();
  await expect(stock(page).locator('[data-cp13-state="summary-unavailable"]')).toBeVisible();
  const initialMounted = await rows(page).count();
  expect(initialMounted).toBeGreaterThan(0);

  const before = state.cursorReads;
  await list(page).evaluate((node) => {
    node.scrollTop = node.scrollHeight;
    node.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(() => state.cursorReads).toBeGreaterThan(before);
  await expect(stock(page).locator('[data-cp13-state="stale"]')).toBeVisible();
  expect(await rows(page).count()).toBeGreaterThan(0);

  const cursor50Before = state.requests.filter((request) =>
    request.path.includes("/warehouse/inventory/cursor") &&
    request.path.includes("cursor=50")).length;
  await stock(page).locator('[data-cp13-state="stale"]').getByRole("button", { name: "Retry" }).click();
  await expect.poll(() =>
    state.requests.filter((request) =>
      request.path.includes("/warehouse/inventory/cursor") &&
      request.path.includes("cursor=50")).length,
  ).toBe(cursor50Before + 1);
  await expect(stock(page).locator('[data-cp13-state="stale"]')).toHaveCount(0);

  state.denyAccess = true;
  await page.evaluate(() =>
    window.dispatchEvent(new Event("inventory-permission-denied")));
  await expect(stock(page)).toHaveCount(0);
  await expect(page.getByText(/Stock Item 0000/)).toHaveCount(0);
  assertNoUnexpected(state);
});

test("entering another inventory tab performs zero Live Stock list summary or family reads", async ({ page }) => {
  const state = await installUxApi(page, 100, { allowOtherInventoryReads: true });
  await seedUx(page, "en", "light", "batches");
  await page.goto("/inventory");
  await page.waitForTimeout(1000);

  expect(state.cursorReads).toBe(0);
  expect(state.summaryReads).toBe(0);
  expect(state.familyReads).toBe(0);
  console.log(
    `LIVE_STOCK_OTHER_TAB_REQUESTS=PASS cursor=${state.cursorReads} summary=${state.summaryReads} family=${state.familyReads}`,
  );
});
