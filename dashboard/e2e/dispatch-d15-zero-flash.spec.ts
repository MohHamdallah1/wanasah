import { mkdirSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

const fixture = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const paths = new Set(["/inventory/access/me", "/dispatch/init", "/dispatch/shops", "/dispatch/shortages", "/dispatch/active_routes"]);
type Frame = { ms: number; shell: boolean; tabs: number; visibleTabs: number; neutral: boolean; structural: boolean; pending: boolean; pageReady: boolean; animations: number; bodyPresent: boolean; mainStage: boolean; priorRouteVisible: boolean; visibleMainBlank: boolean; preReactDocument: boolean; realPanel: boolean; fakePanel: boolean; wrongPanel: boolean; workspaceNode: number | null };
async function signIn(page: Page, language: "ar" | "en") {
  await page.goto("http://127.0.0.1:4173/");
  await page.evaluate(lang => { localStorage.clear(); localStorage.setItem("wanasah.language", lang); }, language);
  await page.goto("http://127.0.0.1:4173/login");
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
function beginProbe() {
    const w = window as any;
    w.__d15ZeroFrames = [];
    w.__d15ZeroStart = performance.now();
    const nodes = new WeakMap<Element, number>();
    let nextNode = 0;
    const visible = (node: Element | null | undefined) =>
      Boolean(node && (node as HTMLElement).getClientRects().length > 0 &&
        (node as HTMLElement).getBoundingClientRect().height > 0);
    const loop = () => {
      if (location.pathname === "/dispatch") {
        const board = document.querySelector(".dispatch-board");
        const shell = board?.querySelector('[data-testid="dispatch-shared-topbar"]');
        const tabs = shell?.querySelectorAll('[role="tab"]');
        // Persistent Dispatch remains mounted but CSS-hidden while Products
        // still owns the visible route frame. Never count that hidden ancestor
        // as a flashing *visible* toolbar while React commits navigation.
        const visibleShell = Boolean(shell && (shell as HTMLElement).getClientRects().length > 0);
        const visibleTabs = [...(tabs ?? [])].filter(el => (el as HTMLElement).getClientRects().length > 0).length;
        const activeAnimations = board ? [...board.getAnimations({ subtree: true })].filter(a => a.playState === "running").length : 0;
        const stage = document.querySelector(".dashboard-main-stage");
        const main = document.querySelector(".dashboard-content");
        const priorRouteVisible = Boolean(main && [...main.children].some(child =>
          !child.contains(board) && (child as HTMLElement).getClientRects().length > 0 &&
          (child as HTMLElement).getBoundingClientRect().height > 0));
        const preReactDocument = !document.querySelector(".dashboard-shell");
        const targetTab = w.__d15TargetTab ?? "routes";
        const workspace = board?.querySelector(`[data-testid="dispatch-${targetTab}-workspace"]`) ?? null;
        const workspaceVisible = visible(workspace);
        const realPanel = workspaceVisible && (targetTab === "routes"
          ? visible(workspace?.querySelector(".dispatch-route-list"))
          : targetTab === "launch"
            ? visible(workspace?.querySelector(".dispatch-launch-config")) &&
              visible(workspace?.querySelector('[data-testid="dispatch-launch-readiness"]')) &&
              Boolean(workspace?.querySelector("table th"))
            : visible(workspace?.querySelector(".dispatch-shop-table")) &&
              visible(workspace?.querySelector(".dispatch-zones-workbench") ?? workspace));
        const fakePanel = ["[data-testid=dispatch-quiet-loading]",
          '[aria-label="هيكل جدول التوزيع"]', '[aria-label="Dispatch table structure"]']
          .some(selector => visible(document.querySelector(selector)));
        let workspaceNode: number | null = null;
        if (workspaceVisible && workspace) {
          if (!nodes.has(workspace)) nodes.set(workspace, ++nextNode);
          workspaceNode = nodes.get(workspace)!;
        }
        const visibleMainBlank = Boolean(stage && !visibleShell && !priorRouteVisible &&
          !stage.querySelector('[role="status"]') &&
          !stage.querySelector(".dashboard-access-state"));
        w.__d15ZeroFrames.push({
          ms: Math.round(performance.now() - w.__d15ZeroStart),
          shell: visibleShell, tabs: visibleShell ? tabs?.length ?? 0 : 0, visibleTabs,
          neutral: Boolean(shell?.querySelector('[data-testid="dispatch-neutral-topbar"]')),
          structural: Boolean(board?.querySelector('[data-testid="dispatch-structural-workspace"]')),
          pending: Boolean(board?.querySelector('[data-testid="dispatch-quiet-loading"]')),
          pageReady: Boolean(board && shell), animations: activeAnimations,
          bodyPresent: Boolean(document.querySelector(".dispatch-content")),
          mainStage: Boolean(stage), priorRouteVisible, visibleMainBlank, preReactDocument,
          realPanel, fakePanel, wrongPanel: workspaceVisible && !realPanel, workspaceNode,
        });
      }
      if (performance.now() - w.__d15ZeroStart < 1700) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
}
async function armFrames(page: Page, tab: "routes" | "launch" | "zones" = "routes") {
  await page.evaluate(value => {
    (window as any).__d15TargetTab = value;
    beginProbe();
  }, tab);
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
      preReactDocumentFrames: frames.filter(x => x.preReactDocument).length,
      priorRouteFrames: frames.filter(x => x.priorRouteVisible && !x.shell).length,
      genuineEmptyMainFrames: frames.filter(x => x.visibleMainBlank).length,
      missingShellSamples: frames.filter(x => !x.shell).slice(0, 8).map(x => ({
        ms: x.ms, preReact: x.preReactDocument, prior: x.priorRouteVisible,
        empty: x.visibleMainBlank, main: x.mainStage,
      })),
      structuralFrames: frames.filter(x => x.structural).length,
      fakePanelFrames: frames.filter(x => x.fakePanel).length,
      wrongRealPanelFrames: frames.filter(x => x.wrongPanel).length,
      actualPanelFrames: frames.filter(x => x.realPanel).length,
      workspaceNodeCount: new Set(frames.map(x => x.workspaceNode).filter(x => x !== null)).size,
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
    expect(data.genuineEmptyMainFrames, label + ": dashboard main must never be visibly empty").toBe(0);
    expect(data.fakePanelFrames, label + ": never show fabricated tables or skeletons").toBe(0);
    expect(data.wrongRealPanelFrames, label + ": actual selected-tab panel must be structurally correct").toBe(0);
    expect(data.actualPanelFrames, label + ": real workspace must paint").toBeGreaterThan(0);
    expect(data.workspaceNodeCount, label + ": actual workspace node must not remount during admission").toBe(1);
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
    const imageDir = `node_modules/.cache/dispatch-d15-zero-flash-${enforce ? "after" : "before"}`;
    mkdirSync(imageDir, { recursive: true });
    let pendingImage: string | null = null;
    // Test-only delay of a genuine signed PG16 read: no response or grant is mocked.
    // Capture the exact intermediate panel the owner saw, then continue real HTTP.
    await page.route("**/dispatch/init", async route => {
      if (pendingImage) {
        const name = pendingImage; pendingImage = null;
        await page.waitForTimeout(420);
        await page.screenshot({ path: `${imageDir}/${language}-${width}-${name}-pending.png` });
      }
      await route.continue();
    });
    // Document-start instrumentation captures cold component import and first
    // actual Dashboard render, rather than starting after the toolbar appears.
    await page.addInitScript(beginProbe);
    await page.goto("http://127.0.0.1:4173/dispatch");
    await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible({ timeout: 35000 });
    await capture(page, network, 0, "cold:" + language + ":" + width, enforce);
    await page.screenshot({ path: `${imageDir}/${language}-${width}-cold-ready.png` });
    const routes = page.getByRole("tab", { name: "الخطوط النشطة" });
    const launch = page.getByRole("tab", { name: "إطلاق خط جديد" });
    const zones = page.getByRole("tab", { name: "هيكلة المناطق" });
    await expect(routes).toBeVisible();
    const permanentToolbar = await page.getByTestId("dispatch-shared-topbar").elementHandle();
    expect(permanentToolbar).not.toBeNull();
    for (const [tab,name] of [[routes,"routes"],[launch,"launch"],[zones,"zones"]] as const) {
      for (const [destination, navIndex] of [["products",4],["inventory",2]] as const) {
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        if (enforce) {
          const node = page.getByTestId(`dispatch-${name}-workspace`);
          await expect(node).toBeVisible();
          await expect(node).not.toHaveAttribute("inert", "");
        }
        const originalPanel = enforce
          ? await page.getByTestId(`dispatch-${name}-workspace`).elementHandle()
          : null;
        if (width === 390) await page.locator(".dashboard-mobile-menu").click();
        await page.locator(".operations-nav button").nth(navIndex).click();
        await expect(page).toHaveURL(new RegExp("/" + destination + "$"));
        const mark = network.length;
        await armFrames(page, name);
        pendingImage = name + "-" + destination;
        if (width === 390) await page.locator(".dashboard-mobile-menu").click();
        await page.locator(".operations-nav button").nth(1).click();
        await expect(page).toHaveURL(/\\/dispatch$/);
        await capture(page, network, mark, "return:" + name + ":" + destination + ":" + language + ":" + width, enforce);
        await page.screenshot({ path: `${imageDir}/${language}-${width}-${name}-${destination}-ready.png` });
        expect(await page.evaluate(node =>
          node === document.querySelector('[data-testid="dispatch-shared-topbar"]'), permanentToolbar)).toBe(true);
        if (enforce) {
          expect(await page.evaluate(({ node, tabName }) =>
            node === document.querySelector(`[data-testid="dispatch-${tabName}-workspace"]`),
            { node: originalPanel, tabName: name })).toBe(true);
        }
        await expect(page.getByRole("tab", { name: tab === routes ? "الخطوط النشطة" : tab === launch ? "إطلاق خط جديد" : "هيكلة المناطق" })).toBeVisible();
      }
    }
    // Real tab switching, not artificial visibilitychange events. Browser may
    // not produce a native hidden event in headless/Xvfb; disclose that case.
    await page.evaluate(() => {
      (window as any).__d15HiddenEvents = 0;
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") (window as any).__d15HiddenEvents++;
      });
    });
    const otherTab = await page.context().newPage();
    await otherTab.goto("about:blank");
    await armFrames(page, "zones");
    await otherTab.bringToFront();
    await page.bringToFront();
    await capture(page, network, network.length, "native-refocus:" + language + ":" + width, enforce);
    const hiddenEvents = await page.evaluate(() => (window as any).__d15HiddenEvents || 0);
    console.log("D15_NATIVE_FOCUS=" + JSON.stringify({
      language, width, nativeHiddenObserved: hiddenEvents > 0, hiddenEvents,
    }));
    await otherTab.close();  });
}
