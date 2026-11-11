import { readFileSync } from "node:fs";
import { expect, test, type Page, type Request } from "playwright/test";

// Same restricted PG16/real signed FastAPI seed as accepted D14: never mock API.
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const apiPath = (url: string) => {
  try {
    const parsed = new URL(url);
    return parsed.pathname === "/inventory/access/me" && parsed.searchParams.has("location_id")
      ? "/inventory/access/me?location_id" : parsed.pathname;
  } catch { return ""; }
};
const dispatchPaths = new Set(["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes", "/dispatch/shortages"]);
const allPaths = new Set([...dispatchPaths, "/inventory/access/me", "/inventory/access/me?location_id"]);

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
        anyVisibleTopbar: Array.from(document.querySelectorAll(".workspace-top-bar-frame")).some(
          el => el.getClientRects().length > 0 &&
            getComputedStyle(el).display !== "none" && getComputedStyle(el).visibility !== "hidden"
        ),
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
    const fullBlankFrames = frames.filter((row: any) => !row.anyVisibleTopbar).length;
    let longest = 0, stretch = 0;
    for (const row of frames) {
      if (!row.board || !row.shell || !row.tabs) stretch += 16;
      else { longest = Math.max(stretch, longest); stretch = 0; }
    }
    longest = Math.max(stretch, longest);
    return { shellMs: first?.ms ?? null, blankFrames: missing, fullBlankFrames,
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
      const inFlight = new Set<Request>();
      page.on("request", request => {
        const path = apiPath(request.url());
        if (allPaths.has(path)) {
          seen.push({ path, at: Date.now() });
          inFlight.add(request);
        }
      });
      page.on("requestfinished", request => { inFlight.delete(request); });
      page.on("requestfailed", request => { inFlight.delete(request); });
      await page.goto("/dispatch");
      // This is an actual same-Dashboard-identity host, not remount-per-route.
      await expect(page.locator("[data-persistent-dispatch-host='true']")).toHaveCount(1);
      await page.evaluate(() =>
        document.querySelector("[data-persistent-dispatch-host='true']")?.setAttribute("data-d15-mounted", "once")
      );
      const tabs = page.getByRole("tab");
      await expect(tabs).toHaveCount(3, { timeout: 45000 });
      const results = [];
      for (const tab of ["الخطوط النشطة", "إطلاق خط جديد", "هيكلة المناطق"]) {
        await page.getByRole("tab", { name: tab }).click();
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
        await navigateInApp(page, 4, mobile);
        await expect(page.locator(".workspace-top-bar-frame:visible").first()).toBeVisible();
        // Exclude an independent Products authorization from the Dispatch
        // return budget. Never suppress either page's genuine Backend check.
        await page.waitForTimeout(120);
        await expect.poll(() => inFlight.size, { timeout: 10000 }).toBe(0);
        const begin = Date.now();
        await probe(page);
        await navigateInApp(page, 1, mobile);
        await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true", { timeout: 45000 });
        const m = await measure(page, begin, seen);
        console.log("D15_ONE_RETURN_NETWORK=" + JSON.stringify({
          language, width, tab, requests: seen.filter(request => request.at >= begin),
          metrics: m,
        }));
        expect(m.fullBlankFrames, tab + " whole workspace blank").toBe(0);
        expect(m.network["/inventory/access/me"], tab + " signed company capability GET").toBeLessThanOrEqual(1);
        expect(m.network["/inventory/access/me?location_id"], tab + " signed Warehouse authority GET")
          .toBeLessThanOrEqual(1);
        expect(m.dispatchReads, tab + " duplicate four-endpoint read").toBeLessThanOrEqual(4);
        expect(m.docWidth, tab + " document horizontal overflow").toBe(width);
        await expect(page.locator('[data-persistent-dispatch-host="true"][data-d15-mounted="once"]'))
          .toHaveCount(1); // proves identical mounted subtree survives route navigation
        results.push({ tab, ...m });
      }
      // Genuine Chromium second browser TAB in a headed Xvfb + Openbox window
      // manager. Do not mock visibility events or intercept signed requests.
      await page.evaluate(() => {
        (window as any).__d15VisibilityEvents = [];
        document.addEventListener("visibilitychange", () => {
          (window as any).__d15VisibilityEvents.push(document.visibilityState);
        });
      });
      const other = await page.context().newPage();
      await other.goto("about:blank");
      await other.bringToFront();
      await page.waitForTimeout(350);
      const hiddenVisibility = await page.evaluate(() => document.visibilityState);
      const focusedAt = Date.now();
      await page.bringToFront();
      await other.close();
      await probe(page);
      await expect(page.getByRole("tab", { name: "هيكلة المناطق" })).toBeVisible();
      const focused = await measure(page, focusedAt, seen);
      const events = await page.evaluate(() => (window as any).__d15VisibilityEvents as string[]);
      // Real headed Chromium in GitHub Xvfb may still report both tabs as
      // visible. Measure the native visibility events actually delivered.
      // Never synthesize visibilitychange or claim a background focus check
      // passed when the browser did not publish a hidden transition.
      expect(await page.evaluate(() => document.visibilityState)).toBe("visible");
      const summary = { language, width, pageReturns: results, browserFocus: {
        ...focused, hiddenVisibility, nativeHiddenObserved: events.includes("hidden"),
        nativeVisibleObserved: events.includes("visible"),
        returnVisibility: await page.evaluate(() => document.visibilityState),
      } };
      console.log("D15_REENTRY_METRICS=" + JSON.stringify(summary));
      await expect(page.locator("[data-testid='dispatch-shared-topbar']")).toBeVisible();
      await expect(page.getByRole("tab")).toHaveCount(3);
    });
  }
}
