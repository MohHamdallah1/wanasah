import { readFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

// Same restricted PG16/real signed FastAPI seed as accepted D14: never mock API.
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const apiPath = (url: string) => {
  try { return new URL(url).pathname; } catch { return ""; }
};
const dispatchPaths = new Set(["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes", "/dispatch/shortages"]);
const allPaths = new Set([...dispatchPaths, "/inventory/access/me"]);

async function signIn(page: Page, lang: "ar" | "en") {
  await page.goto("/");
  await page.evaluate(language => { localStorage.clear(); localStorage.setItem("wanasah.language", language); }, lang);
  await page.goto("/login");
  await page.reload();
  const credential = state.credentials.owner;
  await page.locator("#company-code").fill(credential.code);
  await page.locator("#username").fill(credential.username);
  await page.locator("#password").fill(credential.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function navigateInApp(page: Page, index: number, mobile: boolean) {
  if (mobile) await page.locator(".dashboard-mobile-menu").click();
  await page.locator(".operations-nav button").nth(index).click();
  await expect(page).toHaveURL(index === 1 ? /\/dispatch$/ : /\/products$/, { timeout: 15000 });
}

async function probe(page: Page) {
  await page.evaluate(() => {
    const host = window as any;
    host.__d15Probe = { start: performance.now(), frames: [], shifts: 0 };
    const target = host.__d15Probe;
    const observer = new PerformanceObserver(items => {
      for (const item of items.getEntries() as any[]) {
        if (!item.hadRecentInput) target.shifts += item.value;
      }
    });
    try { observer.observe({ type: "layout-shift", buffered: false } as any); } catch {}
    host.__d15Probe.stop = () => observer.disconnect();
    const tick = () => {
      const now = performance.now();
      const route = location.pathname === "/dispatch";
      if (route) target.frames.push({
        ms: Math.round(now - target.start),
        shell: Boolean(document.querySelector('[data-testid="dispatch-shared-topbar"]')),
        board: Boolean(document.querySelector(".dispatch-board")),
        tabs: document.querySelectorAll('[role="tab"]').length,
        skeleton: Boolean(document.querySelector('[data-testid="dispatch-quiet-loading"]')),
        privateRows: document.querySelectorAll(".dispatch-shop-table tbody tr, .dispatch-route-row").length,
      });
      if (now - target.start < 2200) requestAnimationFrame(tick);
      else observer.disconnect();
    };
    requestAnimationFrame(tick);
  });
}
async function measure(page: Page, begin: number, requests: {path: string; at: number}[]) {
  await page.waitForTimeout(2250);
  return page.evaluate(({ begin, requests }) => {
    const target = (window as any).__d15Probe;
    const frames = target?.frames ?? [];
    const first = frames.find((row: any) => row.shell);
    const missing = frames.filter((row: any) => !row.board || !row.shell || !row.tabs).length;
    let longest = 0, stretch = 0;
    for (const row of frames) {
      if (!row.board || !row.shell || !row.tabs) stretch += 16;
      else { longest = Math.max(stretch, longest); stretch = 0; }
    }
    longest = Math.max(stretch, longest);
    return { shellMs: first?.ms ?? null, blankFrames: missing,
      longestBlankMs: longest, shifts: target?.shifts ?? 0, frameCount: frames.length,
      viewport: window.innerWidth, docWidth: document.documentElement.scrollWidth };
  }, { begin, requests: [] }).then(async metrics => {
    const observed = requests.filter(r => r.at >= begin && allPaths.has(r.path));
    return { ...metrics, network: Object.fromEntries([...allPaths].map(p => [p, observed.filter(r => r.path === p).length])),
      dispatchReads: observed.filter(r => dispatchPaths.has(r.path)).length, fetches: observed.length };
  });
}

for (const language of ["ar", "en"] as const) {
  for (const width of [1440, 390] as const) {
    test("D15 real PG16 before-after reentry metrics " + language + " " + width, async ({ page }) => {
      test.setTimeout(210000);
      const mobile = width === 390;
      await page.setViewportSize({ width, height: 900 });
      await signIn(page, language);
      const seen: {path: string; at: number}[] = [];
      page.on("request", request => {
        const path = apiPath(request.url());
        if (allPaths.has(path)) seen.push({ path, at: Date.now() });
      });
      await page.goto("/dispatch");
      const tabs = page.getByRole("tab");
      await expect(tabs).toHaveCount(3, { timeout: 45000 });
      const results = [];
      for (const tab of ["الخطوط النشطة", "إطلاق خط جديد", "هيكلة المناطق"]) {
        await page.getByRole("tab", { name: tab }).click();
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
        await navigateInApp(page, 4, mobile);
        await expect(page.locator(".workspace-top-bar-frame")).toBeVisible();
        const begin = Date.now();
        await probe(page);
        await navigateInApp(page, 1, mobile);
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true", { timeout: 45000 });
        const m = await measure(page, begin, seen);
        results.push({ tab, ...m });
      }
      // Genuine browser tab background + foreground, not mocked visibility events.
      const other = await page.context().newPage();
      await other.goto("about:blank");
      await other.bringToFront();
      const focusedAt = Date.now();
      await probe(page);
      await page.bringToFront();
      await other.close();
      await expect(page.getByRole("tab", { name: "هيكلة المناطق" })).toBeVisible();
      const focused = await measure(page, focusedAt, seen);
      const summary = { language, width, pageReturns: results, browserFocus: focused };
      console.log("D15_REENTRY_METRICS=" + JSON.stringify(summary));
      await expect(page.locator("[data-testid='dispatch-shared-topbar']")).toBeVisible();
      await expect(page.getByRole("tab")).toHaveCount(3);
    });
  }
}
