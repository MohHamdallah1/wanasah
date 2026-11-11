import { readFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

const fixture = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const paths = new Set(["/inventory/access/me", "/dispatch/init", "/dispatch/shops", "/dispatch/shortages", "/dispatch/active_routes"]);
type Frame = { ms: number; shell: boolean; tabs: number; visibleTabs: number; neutral: boolean; structural: boolean; pending: boolean; pageReady: boolean; animations: number; bodyPresent: boolean };
async function signIn(page: Page, language: "ar" | "en") {
  await page.goto("/");
  await page.evaluate(lang => { localStorage.clear(); localStorage.setItem("wanasah.language", lang); }, language);
  await page.goto("/login");
  await page.reload();
  const owner = fixture.credentials.owner;
  await page.locator("#company-code").fill(owner.code);
  await page.locator("#username").fill(owner.username);
  await page.locator("#password").fill(owner.password);
  await Promise.all([
    page.waitForURL(u => u.pathname !== "/login", { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}
async function armFrames(page: Page) {
  await page.evaluate(() => {
    const w = window as any;
    w.__d15ZeroFrames = [];
    w.__d15ZeroStart = performance.now();
    const loop = () => {
      if (location.pathname === "/dispatch") {
        const board = document.querySelector(".dispatch-board");
        const shell = board?.querySelector('[data-testid="dispatch-shared-topbar"]');
        const tabs = shell?.querySelectorAll('[role="tab"]');
        const visibleTabs = [...(tabs ?? [])].filter(el => (el as HTMLElement).getClientRects().length > 0).length;
        const activeAnimations = board ? [...board.getAnimations({ subtree: true })].filter(a => a.playState === "running").length : 0;
        w.__d15ZeroFrames.push({
          ms: Math.round(performance.now() - w.__d15ZeroStart),
          shell: Boolean(shell), tabs: tabs?.length ?? 0, visibleTabs,
          neutral: Boolean(shell?.querySelector('[data-testid="dispatch-neutral-topbar"]')),
          structural: Boolean(board?.querySelector('[data-testid="dispatch-structural-workspace"]')),
          pending: Boolean(board?.querySelector('[data-testid="dispatch-quiet-loading"]')),
          pageReady: Boolean(board && shell), animations: activeAnimations,
          bodyPresent: Boolean(document.querySelector(".dispatch-content")),
        });
      }
      if (performance.now() - w.__d15ZeroStart < 1700) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  });
}
async function capture(page: Page, network: string[], marker: number, label: string, enforce: boolean) {
  await page.waitForTimeout(1750);
  const data = await page.evaluate(() => {
    const frames = ((window as any).__d15ZeroFrames || []) as Frame[];
    const firstShell = frames.find(x => x.shell);
    const firstTabs = frames.find(x => x.visibleTabs > 0);
    const missing = frames.filter(x => x.shell && x.visibleTabs === 0);
    const flicker = (() => {
      let ever = false, count = 0;
      for (const x of frames) {
        if (x.visibleTabs > 0) ever = true;
        else if (ever && x.shell) count++;
      }
      return count;
    })();
    return { frameCount: frames.length, firstChromeMs: firstShell?.ms ?? null, firstTabsMs: firstTabs?.ms ?? null,
      neutralFrames: frames.filter(x => x.neutral).length,
      tabsMissingWhileShell: missing.length, disappearedAfterShown: flicker,
      fullShellMissing: frames.filter(x => !x.shell).length,
      structuralFrames: frames.filter(x => x.structural).length,
      animationFrames: frames.filter(x => x.animations > 0).length,
      blankWorkspaceFrames: frames.filter(x => x.shell && !x.bodyPresent).length,
      viewport: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
      tabsAtEnd: frames.at(-1)?.tabs ?? 0 };
  });
  const observed = network.slice(marker).filter(p => paths.has(p));
  const byPath = Object.fromEntries([...paths].map(p => [p, observed.filter(x => x === p).length]));
  const result = { label, ...data, network: byPath };
  console.log("D15_ZERO_FLASH=" + JSON.stringify(result));
  if (enforce) {
    expect(data.tabsMissingWhileShell, label + ": tabs must exist while server reads").toBe(0);
    expect(data.disappearedAfterShown, label + ": header cannot blink after display").toBe(0);
    expect(data.blankWorkspaceFrames, label + ": permanent layout must remain").toBe(0);
    expect(data.animationFrames, label + ": no dispatch animation").toBe(0);
    expect(data.documentWidth, label + ": zero outer overflow").toBe(data.viewport);
  }
  return result;
}
for (const language of ["ar", "en"] as const) for (const width of [1440, 390] as const) {
  test("D15 zero-flash first/open/return " + language + " " + width, async ({ page }) => {
    test.setTimeout(180000);
    await page.setViewportSize({ width, height: 900 });
    await signIn(page, language);
    const network: string[] = [];
    page.on("request", r => { const p = new URL(r.url()).pathname; if (paths.has(p)) network.push(p); });
    const enforce = process.env.D15_ZERO_FLASH_ENFORCE === "1";
    await page.goto("/dispatch");
    await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible({ timeout: 35000 });
    await armFrames(page);
    await capture(page, network, 0, "cold:" + language + ":" + width, enforce);
    const routes = page.getByRole("tab", { name: "الخطوط النشطة" });
    const launch = page.getByRole("tab", { name: "إطلاق خط جديد" });
    const zones = page.getByRole("tab", { name: "هيكلة المناطق" });
    await expect(routes).toBeVisible();
    for (const [tab,name] of [[routes,"routes"],[launch,"launch"],[zones,"zones"]] as const) {
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected","true");
      if (width === 390) await page.locator(".dashboard-mobile-menu").click();
      await page.locator(".operations-nav button").nth(4).click();
      await expect(page).toHaveURL(/\/products$/);
      const mark = network.length;
      await armFrames(page);
      if (width === 390) await page.locator(".dashboard-mobile-menu").click();
      await page.locator(".operations-nav button").nth(1).click();
      await expect(page).toHaveURL(/\/dispatch$/);
      await capture(page, network, mark, "return:" + name + ":" + language + ":" + width, enforce);
      await expect(page.getByRole("tab", { name: tab === routes ? "الخطوط النشطة" : tab === launch ? "إطلاق خط جديد" : "هيكلة المناطق" })).toBeVisible();
    }
  });
}
