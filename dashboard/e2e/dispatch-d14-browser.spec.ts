import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page, type TestInfo } from "playwright/test";

const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const api = "http://127.0.0.1:4174";
const labels = {
  ar: "الرصيد غير متاح حسب الصلاحيات",
  en: "Balance unavailable with your permissions",
};
type Language = keyof typeof labels;
const dispatchTabs = {
  ar: { routes: "الخطوط النشطة", launch: "إطلاق خط جديد", zones: "هيكلة المناطق" },
  en: { routes: "Active routes", launch: "Launch new route", zones: "Zone structure" },
} as const;
type Identity = "owner" | "reader" | "limited" | "foreign";
type Credential = { code: string; username: string; password: string };
const actor = (who: Identity): Credential => state.credentials[who];
const shopTable = (page: Page) => page.locator(".dispatch-shop-table");
const shopRow = (page: Page, name: string) =>
  shopTable(page).locator("tbody tr").filter({ hasText: name });
const moneyCell = (page: Page, name: string) => shopRow(page, name).locator("td").nth(4);

function toggle(kind: "reader" | "limited" | "reset", value?: "on" | "off") {
  const args = ["-m", "tests.test_dispatch_d14_browser_fixture", kind];
  if (value) args.push(value);
  // Fixture-scoped SQL permissions only. Actual UI/network still uses signed tokens.
  execFileSync("python", args, {
    cwd: resolve(process.cwd(), "../wa_backend"),
    stdio: "pipe", timeout: 25000,
  });
}

async function signIn(page: Page, who: Identity, language: Language) {
  // Clear the previous true Dashboard session before navigating to Login.
  await page.goto("/");
  await page.evaluate((lang) => {
    localStorage.clear();
    localStorage.setItem("wanasah.language", lang);
  }, language);
  await page.goto("/login");
  await page.reload();
  const credentials = actor(who);
  await page.locator("#company-code").fill(credentials.code);
  await page.locator("#username").fill(credentials.username);
  await page.locator("#password").fill(credentials.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 25000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function shopsTab(page: Page, zone: string, language: Language) {
  await page.goto("/dispatch");
  const tab = page.getByRole("tab", { name: dispatchTabs[language].zones, exact: true });
  await expect(tab).toBeVisible({ timeout: 45000 });
  // D15: visible static tab is disabled until the real PG16 signed reads pass.
  await expect(tab).toBeEnabled({ timeout: 45000 });
  await tab.focus();
  await page.keyboard.press("Enter");
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(shopTable(page)).toBeVisible();
  const zonePanel = page.locator(".dispatch-zones-workbench > div").first();
  const pick = zonePanel.getByText(zone, { exact: true }).first();
  await expect(pick).toBeVisible({ timeout: 25000 });
  await pick.click();
}

async function ownScopedRows(page: Page) {
  await expect(shopRow(page, state.shops.assigned.name)).toHaveCount(1);
  await expect(shopRow(page, state.shops.unassigned.name)).toHaveCount(0);
  await expect(shopRow(page, state.shops.a2.name)).toHaveCount(0);
}

function latinDigits(s: string) {
  return s.replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 0x660))
    .replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 0x6f0))
    .replace(/٫/g, ".").replace(/٬/g, ",");
}

async function visibleMoney(page: Page, shop: string, amount: string, language: Language) {
  const cell = moneyCell(page, shop);
  await expect(cell).toBeVisible();
  await expect.poll(async () => latinDigits((await cell.innerText()) || ""), {
    timeout: 15000,
  }).toContain(amount);
  await expect(cell).not.toContainText(labels[language]);
}
async function unavailable(page: Page, shop: string, language: Language) {
  await expect(moneyCell(page, shop)).toContainText(labels[language], { timeout: 20000 });
}

async function revisitRealBrowserTab(page: Page, selectedZone: string, language: Language) {
  // Real Chromium browser tab away/return and real Dashboard navigation.
  // Do not emulate visibilitychange or intercept any authenticated requests.
  const elsewhere = await page.context().newPage();
  await elsewhere.goto("about:blank");
  await elsewhere.bringToFront();
  await page.bringToFront();
  await elsewhere.close();
  const routes = page.getByRole("tab", { name: dispatchTabs[language].routes, exact: true });
  const zones = page.getByRole("tab", { name: dispatchTabs[language].zones, exact: true });
  await routes.click();
  await zones.click();
  await expect(zones).toHaveAttribute("aria-selected", "true");
  await expect(shopTable(page)).toBeVisible({ timeout: 25000 });
  await page.locator(".dispatch-zones-workbench > div").first()
    .getByText(selectedZone, { exact: true }).first().click();
}

async function browserApi<T>(page: Page, path: string): Promise<{ status: number; data: T }> {
  return page.evaluate(async ({ api, path }) => {
    const token = localStorage.getItem("admin_token");
    const response = await fetch(api + path, {
      headers: { Authorization: "Bearer " + token },
      cache: "no-store",
    });
    return { status: response.status, data: await response.json() };
  }, { api, path });
}

for (const language of ["ar", "en"] as const) {
  for (const width of [1440, 390]) {
    test(`D14 real PG16 signed Chromium ${language} ${width}px Shop finance, scope, revoke and identity`,
      async ({ page }, info: TestInfo) => {
        test.setTimeout(240000);
        await page.setViewportSize({ width, height: 900 });
        toggle("reset");
        const requests: { path: string; status: number }[] = [];
        page.on("response", r => {
          const path = new URL(r.url()).pathname;
          if (["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes"].includes(path)) {
            requests.push({ path, status: r.status() });
          }
        });

        // D15 1A: real fresh login, same physical shared Products topbar
        // frame, no verbose permissions banner and no old separate card.
        // These are real built-Dashboard DOM checks; no mocked endpoints.
        await signIn(page, "owner", language);
        await page.goto("/dispatch", { waitUntil: "domcontentloaded" });
        const bar = page.getByTestId("dispatch-shared-topbar");
        await expect(bar).toBeVisible({ timeout: 45000 });
        await expect(bar.locator(".workspace-top-bar--page")).toBeVisible();
        await expect(page.locator(".dispatch-command-bar")).toHaveCount(0);
        await expect(page.getByText(/جارٍ التحقق من صلاحيات الوصول|Checking access permissions/)).toHaveCount(0);
        const dispatchFrame = await bar.boundingBox();
        expect(dispatchFrame).not.toBeNull();
        await page.goto("/products");
        const productFrame = page.locator(".workspace-top-bar-frame");
        await expect(productFrame).toBeVisible({ timeout: 45000 });
        const productsBox = await productFrame.boundingBox();
        expect(productsBox).not.toBeNull();
        expect(Math.abs(dispatchFrame!.x - productsBox!.x)).toBeLessThanOrEqual(2);
        expect(Math.abs(dispatchFrame!.width - productsBox!.width)).toBeLessThanOrEqual(2);
        await page.goto("/dispatch");
        const launch = page.getByRole("tab", { name: dispatchTabs[language].launch, exact: true });
        await expect(launch).toBeVisible({ timeout: 45000 });
        await launch.click();
        // D15 compact component intentionally renders NOTHING while selectors
        // are incomplete. Its owned in-grid mount remains, but a zero-height
        // wrapper is not required to be visibly painted before selection.
        await expect(page.locator(".dispatch-launch-config [data-testid='dispatch-launch-readiness']")).toHaveCount(1);
        await expect(page.locator(".dispatch-launch-config")).toBeVisible();
        await expect(page.getByText("تتم حركة الفرق تلقائيًا عبر المستودع المختار")).toHaveCount(0);
        // The real final launch verification path is untouched.
        await shopsTab(page, state.zones.a1, language);
        await visibleMoney(page, state.shops.assigned.name, "181.125", language);
        await shopsTab(page, state.zones.a2, language);
        await visibleMoney(page, state.shops.a2.name, "901.125", language);
        const ownerApi = await browserApi<any[]>(page, "/dispatch/shops");
        expect(ownerApi.status).toBe(200);
        expect(ownerApi.data.find(x => x.name === state.shops.a2.name)?.financeRedacted).toBe(false);

        // 2. Company-wide *Backoffice* basic directory, no inherited money.
        await signIn(page, "reader", language);
        await shopsTab(page, state.zones.a1, language);
        await expect(shopRow(page, state.shops.unassigned.name)).toHaveCount(1);
        await unavailable(page, state.shops.assigned.name, language);
        await shopsTab(page, state.zones.a2, language);
        await expect(shopRow(page, state.shops.a2.name)).toHaveCount(1);
        await unavailable(page, state.shops.a2.name, language);
        const readerApi = await browserApi<any[]>(page, "/dispatch/shops");
        expect(readerApi.status).toBe(200);
        expect(readerApi.data.every(s => s.financeRedacted === true &&
               s.initialDebt === null && s.maxDebtLimit === null)).toBe(true);

        // 3. Only explicit COMPANY finance permission changes displayed money.
        const originalReaderToken = await page.evaluate(() => localStorage.getItem("admin_token"));
        toggle("reader", "on");
        const grantedReader = await browserApi<any[]>(page, "/dispatch/shops");
        const grantedRow = grantedReader.data.find(s => s.name === state.shops.a2.name);
        expect(grantedReader.status).toBe(200);
        expect(grantedRow?.financeRedacted).toBe(false);
        expect(Number(grantedRow?.initialDebt)).toBe(901.125);
        console.log("D14_READER_FINANCE_HTTP_AFTER_GRANT=PASS");
        await revisitRealBrowserTab(page, state.zones.a2, language);
        await visibleMoney(page, state.shops.a2.name, "901.125", language);
        expect(await page.evaluate(() => localStorage.getItem("admin_token")))
          .toBe(originalReaderToken);
        toggle("reader", "off");
        await revisitRealBrowserTab(page, state.zones.a2, language);
        await unavailable(page, state.shops.a2.name, language);
        // The old full-page auth notice never flashes during real tab reentry.
        await expect(page.getByText(/جارٍ التحقق من صلاحيات الوصول|Checking access permissions/)).toHaveCount(0);

        // 4. A1 warehouse-restricted *Backoffice*, active Visit only.
        await signIn(page, "limited", language);
        await shopsTab(page, state.zones.a1, language);
        await ownScopedRows(page);
        await unavailable(page, state.shops.assigned.name, language);
        await expect(page.getByRole("status")
          .filter({ hasText: language === "ar" ? "المسارات المصرح" : "authorized" })
          .first()).toBeVisible();
        const a1 = await browserApi<any[]>(page, "/dispatch/shops");
        expect(a1.status).toBe(200);
        expect(a1.data.map(s => s.name)).toEqual([state.shops.assigned.name]);
        const initialLimitedToken = await page.evaluate(() => localStorage.getItem("admin_token"));
        toggle("limited", "on");
        const grantedA1 = await browserApi<any[]>(page, "/dispatch/shops");
        expect(grantedA1.status).toBe(200);
        expect(grantedA1.data.map(s => s.name)).toEqual([state.shops.assigned.name]);
        expect(Number(grantedA1.data[0].initialDebt)).toBe(181.125);
        await revisitRealBrowserTab(page, state.zones.a1, language);
        await visibleMoney(page, state.shops.assigned.name, "181.125", language);
        await ownScopedRows(page); // Finance grant never confers A2/whole directory.
        toggle("limited", "off");
        await revisitRealBrowserTab(page, state.zones.a1, language);
        await unavailable(page, state.shops.assigned.name, language);
        expect(await page.evaluate(() => localStorage.getItem("admin_token")))
          .toBe(initialLimitedToken);

        // 5. Company/account switch: rendered A1 Shop must vanish in foreign B.
        await signIn(page, "foreign", language);
        await page.goto("/dispatch");
        await expect(page.getByRole("tab", { name: dispatchTabs[language].zones, exact: true })).toBeVisible();
        await page.getByRole("tab", { name: dispatchTabs[language].zones, exact: true }).click();
        await expect(shopRow(page, state.shops.assigned.name)).toHaveCount(0);
        await expect(shopRow(page, state.shops.a2.name)).toHaveCount(0);
        const foreign = await browserApi<any[]>(page, "/dispatch/shops");
        expect(foreign.status).toBe(200);
        expect(foreign.data.every(s => s.name !== state.shops.assigned.name &&
               s.name !== state.shops.a2.name)).toBe(true);

        // 6. Flutter FIELD credential never authenticates as a Dashboard principal.
        const field = state.credentials.field;
        const fieldLogin = await page.request.post(api + "/driver/login", { data: {
          company_code: field.code, username: field.username, password: field.password,
        } });
        expect(fieldLogin.status()).toBe(200);
        const fieldToken = (await fieldLogin.json()).token;
        const adminLogin = await page.request.post(api + "/login", { data: {
          company_code: field.code, username: field.username, password: field.password,
        } });
        expect(adminLogin.status()).toBe(401);
        for (const p of ["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes"]) {
          const rejected = await page.request.get(api + p, {
            headers: { Authorization: "Bearer " + fieldToken },
          });
          expect([401, 403]).toContain(rejected.status());
        }

        const size = await page.evaluate(() => ({
          width: window.innerWidth,
          docWidth: document.documentElement.scrollWidth,
          shopContainerOverflow: document.querySelector(".dispatch-shop-table")?.scrollWidth || 0,
          lang: localStorage.getItem("wanasah.language"),
        }));
        expect(size.docWidth, "Whole Dashboard must not horizontally overflow").toBeLessThanOrEqual(width);
        expect(requests.some(x => x.path === "/dispatch/shops" && x.status === 200)).toBe(true);
        await page.screenshot({ path: info.outputPath(`d14-real-${language}-${width}.png`), fullPage: true });
        console.log("D14_REAL_SIGNED_CHROMIUM_PASS=" + JSON.stringify({
          language, width, pg16: true, roles: ["owner", "company-reader", "a1-only", "foreign", "field-denied"],
          moneyRedaction: true, sameTokenRevoke: true, tabFocusRefresh: true, accountSwitch: true,
          crossCompanyDenied: true, docWidth: size.docWidth, successfulShopRequests: requests.filter(x =>
            x.path === "/dispatch/shops" && x.status === 200).length,
        }));
      });
  }
}
