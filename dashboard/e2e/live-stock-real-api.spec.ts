import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "playwright/test";

type CompanyAState = {
  id: number;
  code: string;
  ownerUsername: string;
  ownerPassword: string;
  readerUsername: string;
  readerPassword: string;
  warehouseA1: number;
  warehouseA2: number;
  variantId: number;
  batchId: number;
  productName: string;
  lot: string;
  expectedInbound: string;
  expectedMove: string;
  expectedRemaining: string;
  expectedCost: string;
};

type CompanyBState = {
  id: number;
  code: string;
  ownerUsername: string;
  ownerPassword: string;
  warehouse: number;
  variantId: number;
  batchId: number;
  productName: string;
  lot: string;
  expectedQuantity: string;
  expectedCost: string;
};

type GateState = { companyA: CompanyAState; companyB: CompanyBState };
type BrowserFetchResult = { status: number; body: unknown };

const statePath = process.env.WANASAH_REAL_BROWSER_STATE;
if (!statePath) throw new Error("WANASAH_REAL_BROWSER_STATE is required");
const state = JSON.parse(readFileSync(statePath, "utf8")) as GateState;

const API = "http://127.0.0.1:4174";
const helper = resolve(process.cwd(), "../wa_backend/tests/live_stock_real_browser_support.py");

const stock = (page: Page) => page.locator('[data-cp13-surface="live-stock"]');
const rowFor = (page: Page, name: string) =>
  page.locator(".live-stock-row").filter({ hasText: name });
const cardFor = (page: Page, name: string) =>
  page.locator("[data-cp13-stock-card]").filter({ hasText: name });

const expectedDecimal = (value: string) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`Invalid expected decimal: ${value}`);
  return parsed;
};

const quantityPattern = (value: string) => {
  const integer = String(Math.trunc(expectedDecimal(value)));
  return new RegExp(`(^|\\D)${integer}(?:\\.0+)?(?:\\D|$)`);
};

const costPattern = (value: string) =>
  new RegExp(String(expectedDecimal(value)).replace(".", "\\."));

async function setLocale(page: Page, locale: "ar" | "en") {
  await page.evaluate((language) => {
    localStorage.setItem("wanasah.language", language);
  }, locale);
}

async function login(
  page: Page,
  credentials: { code: string; username: string; password: string },
  locale: "ar" | "en" = "en",
) {
  await page.goto("/login");
  await setLocale(page, locale);
  await page.reload();
  await page.locator("#company-code").fill(credentials.code);
  await page.locator("#username").fill(credentials.username);
  await page.locator("#password").fill(credentials.password);
  await Promise.all([
    page.waitForURL((url) => url.pathname !== "/login"),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.goto("/inventory");
  await expect(stock(page)).toBeVisible();
}

async function browserFetch(page: Page, path: string): Promise<BrowserFetchResult> {
  return page.evaluate(async ({ api, route }) => {
    const token = localStorage.getItem("admin_token");
    if (!token) throw new Error("No authenticated browser token");
    const response = await fetch(api + route, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const text = await response.text();
    return {
      status: response.status,
      body: text ? JSON.parse(text) : null,
    };
  }, { api: API, route: path });
}

async function expectDesktopStock(
  page: Page,
  company: CompanyAState,
  quantity: string,
) {
  const row = rowFor(page, company.productName);
  await expect(row).toHaveCount(1);
  await expect(row.locator('[data-cp13-quantity="on-hand"]')).toContainText(
    quantityPattern(quantity),
  );

  const purchase = row.locator("td").nth(8).locator("div");
  const average = row.locator("td").nth(9).locator("div");
  const displayedCost = expectedDecimal(company.expectedCost).toFixed(3);
  await expect(purchase).toContainText("JOD");
  await expect(average).toContainText("JOD");
  await expect(purchase).toContainText(displayedCost);
  await expect(average).toContainText(displayedCost);
  await expect(purchase).toHaveAttribute("title", costPattern(company.expectedCost));
  await expect(average).toHaveAttribute("title", costPattern(company.expectedCost));
  await expect(purchase).toHaveAttribute("title", /per Unit/);
  await expect(average).toHaveAttribute("title", /per Unit/);
}

async function openBatchAndReadEvidence(
  page: Page,
  company: CompanyAState,
  expectedQuantity: string,
) {
  const batchResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "GET"
    && response.url().includes(`/warehouse/inventory/${company.variantId}/batches?`)
    && response.status() === 200,
  );
  await page.locator(`[data-live-stock-product-open="${company.variantId}"]`).click();
  const batchResponse = await batchResponsePromise;
  const batchPayload = await batchResponse.json() as {
    currency_code: string;
    batches: Array<{
      batch_id: number;
      batch_number: string | null;
      on_hand_quantity: string;
      latest_purchase_cost: string | null;
      latest_purchase_uom_code: string | null;
      purchase_event_count: number;
    }>;
  };

  expect(batchPayload.currency_code).toBe("JOD");
  const batch = batchPayload.batches.find((entry) => entry.batch_id === company.batchId);
  expect(batch).toBeTruthy();
  expect(Number(batch!.on_hand_quantity)).toBe(expectedDecimal(expectedQuantity));
  expect(batch!.latest_purchase_cost).toBe(company.expectedCost);
  expect(batch!.latest_purchase_uom_code).toBe("EACH");
  expect(batch!.purchase_event_count).toBe(1);

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(company.lot);

  const sourceButton = dialog.getByRole("button", { name: "Stock source and reservations" });
  const sourceResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "GET"
    && response.url().includes(
      `/warehouse/inventory/${company.variantId}/batches/${company.batchId}/source?`,
    )
    && response.status() === 200,
  );
  await sourceButton.click();
  const sourceResponse = await sourceResponsePromise;
  const sourcePayload = await sourceResponse.json() as {
    location_id: number;
    product_variant_id: number;
    batch_id: number;
    base_uom_code: string;
    statuses: Array<{
      stock_status: string;
      on_hand_quantity: string;
      movable_quantity: string;
    }>;
  };
  expect(sourcePayload.location_id).toBe(company.warehouseA1);
  expect(sourcePayload.product_variant_id).toBe(company.variantId);
  expect(sourcePayload.batch_id).toBe(company.batchId);
  expect(sourcePayload.base_uom_code).toBe("EACH");
  const available = sourcePayload.statuses.find((entry) => entry.stock_status === "AVAILABLE");
  expect(available).toBeTruthy();
  expect(Number(available!.on_hand_quantity)).toBe(expectedDecimal(expectedQuantity));
  expect(Number(available!.movable_quantity)).toBe(expectedDecimal(expectedQuantity));
  await expect(sourceButton).toHaveAttribute("aria-expanded", "true");

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
}

function runHelper(command: "move" | "revoke-a2") {
  return execFileSync(
    process.env.PYTHON || "python",
    [helper, command],
    { encoding: "utf8", env: process.env },
  );
}

test("real FastAPI/PostgreSQL browser journey preserves stock, cost, scope and fresh evidence", async ({ page }) => {
  test.setTimeout(120_000);
  const a = state.companyA;
  const b = state.companyB;

  // Independent fixed expectations are loaded from the seed contract before
  // any browser request. Their arithmetic is asserted again here.
  expect(expectedDecimal(a.expectedInbound)).toBe(800);
  expect(expectedDecimal(a.expectedMove)).toBe(125);
  expect(expectedDecimal(a.expectedRemaining)).toBe(675);
  expect(expectedDecimal(a.expectedCost)).toBe(1.25);
  expect(expectedDecimal(a.expectedInbound) - expectedDecimal(a.expectedMove))
    .toBe(expectedDecimal(a.expectedRemaining));

  await page.setViewportSize({ width: 1360, height: 900 });
  await login(page, {
    code: a.code,
    username: a.readerUsername,
    password: a.readerPassword,
  }, "en");

  await expect.poll(() => page.evaluate(() => document.documentElement.dir)).toBe("ltr");
  await expectDesktopStock(page, a, a.expectedInbound);
  await openBatchAndReadEvidence(page, a, a.expectedInbound);

  const moveOutput = runHelper("move");
  expect(moveOutput).toContain("REAL_BROWSER_MOVE=PASS");

  await stock(page).locator(".live-stock-context-refresh").click();
  await expectDesktopStock(page, a, a.expectedRemaining);
  await openBatchAndReadEvidence(page, a, a.expectedRemaining);

  // Warm A2 through the SAME real restricted principal before revocation.
  const selector = stock(page).locator(".live-stock-context-select");
  await selector.selectOption(String(a.warehouseA2));
  const a2Row = rowFor(page, a.productName);
  await expect(a2Row).toHaveCount(1);
  await expect(a2Row.locator('[data-cp13-quantity="on-hand"]')).toContainText(
    quantityPattern(a.expectedMove),
  );
  const warmA2 = await browserFetch(
    page,
    `/warehouse/inventory/cursor?location_id=${a.warehouseA2}&limit=50`,
  );
  expect(warmA2.status).toBe(200);

  const revokeOutput = runHelper("revoke-a2");
  expect(revokeOutput).toContain("REAL_BROWSER_REVOKE_A2=PASS");

  // Same bearer token, same browser tab, and an A2 UI/cache already warmed.
  // The real 403 causes the production permission-denied path to hide it.
  await stock(page).locator(".live-stock-context-refresh").click();
  await expect(stock(page)).toHaveCount(0);
  await expect(page.getByText(a.productName)).toHaveCount(0);

  const revokedA2 = await browserFetch(
    page,
    `/warehouse/inventory/cursor?location_id=${a.warehouseA2}&limit=50`,
  );
  expect(revokedA2.status).toBe(403);
  expect(JSON.stringify(revokedA2.body)).not.toContain(a.expectedMove);

  const foreignDenied = await browserFetch(
    page,
    `/warehouse/inventory/cursor?location_id=${b.warehouse}&limit=50`,
  );
  expect(foreignDenied.status).toBe(404);
  expect(JSON.stringify(foreignDenied.body)).not.toContain(b.expectedCost);

  // Reload under the unchanged token. Discovery must discard the saved A2
  // selection and recover only the still-authorized A1.
  await page.reload();
  await expect(stock(page)).toBeVisible();
  await expectDesktopStock(page, a, a.expectedRemaining);
  const allowedValues = await stock(page).locator(".live-stock-context-select option")
    .evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value));
  expect(allowedValues).toContain(String(a.warehouseA1));
  expect(allowedValues).not.toContain(String(a.warehouseA2));

  // Exercise Arabic + mobile on the same genuine API-backed session.
  await page.setViewportSize({ width: 390, height: 780 });
  await setLocale(page, "ar");
  await page.reload();
  await expect.poll(() => page.evaluate(() => document.documentElement.dir)).toBe("rtl");
  const card = cardFor(page, a.productName);
  await expect(card).toHaveCount(1);
  await expect(card.locator('[data-cp13-quantity="on-hand"]')).toContainText(
    quantityPattern(a.expectedRemaining),
  );
  const mobilePurchase = card.locator('[data-live-stock-mobile-cost="last-purchase"]');
  const mobileAverage = card.locator('[data-live-stock-mobile-cost="average"]');
  await expect(mobilePurchase).toContainText("د.أ.");
  await expect(mobileAverage).toContainText("د.أ.");
  await expect(mobilePurchase).toContainText("لكل حبة");
  await expect(mobileAverage).toContainText("لكل حبة");
  await expect(mobilePurchase).toContainText(
    expectedDecimal(a.expectedCost).toFixed(3),
  );
  await expect(mobileAverage).toContainText(
    expectedDecimal(a.expectedCost).toFixed(3),
  );
  await expect(mobilePurchase.locator("[title]").first())
    .toHaveAttribute("title", costPattern(a.expectedCost));
  await expect(mobileAverage.locator("[title]").first())
    .toHaveAttribute("title", costPattern(a.expectedCost));

  // A different company logs in through the real login form and sees only its
  // own independent inbound/cost evidence. Company A is not queryable by ID.
  await page.evaluate(() => {
    localStorage.removeItem("admin_token");
    localStorage.removeItem("refresh_token");
    localStorage.removeItem("principal_id");
    localStorage.removeItem("backoffice_user_id");
  });
  await page.goto("/login");
  await setLocale(page, "en");
  await page.reload();
  await page.locator("#company-code").fill(b.code);
  await page.locator("#username").fill(b.ownerUsername);
  await page.locator("#password").fill(b.ownerPassword);
  await Promise.all([
    page.waitForURL((url) => url.pathname !== "/login"),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto("/inventory");
  await expect(stock(page)).toBeVisible();
  const foreignRow = rowFor(page, b.productName);
  await expect(foreignRow).toHaveCount(1);
  await expect(foreignRow.locator('[data-cp13-quantity="on-hand"]')).toContainText(
    quantityPattern(b.expectedQuantity),
  );
  const foreignPurchase = foreignRow.locator("td").nth(8).locator("div");
  await expect(foreignPurchase).toContainText(
    expectedDecimal(b.expectedCost).toFixed(3),
  );
  await expect(foreignPurchase)
    .toHaveAttribute("title", costPattern(b.expectedCost));
  await expect(page.getByText(a.productName)).toHaveCount(0);

  const companyBCrossTenant = await browserFetch(
    page,
    `/warehouse/inventory/cursor?location_id=${a.warehouseA1}&limit=50`,
  );
  expect(companyBCrossTenant.status).toBe(404);
  expect(JSON.stringify(companyBCrossTenant.body)).not.toContain(a.expectedCost);
});
