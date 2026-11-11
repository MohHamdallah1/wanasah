/**
 * #914 — Independent first-paint and security witness.
 * REAL isolated PG16/D14 fixture + signed FastAPI + production Vite + headed
 * Chromium/Openbox. No fetch interception, fake backend, synthetic focus,
 * application source or persisted browser session modifications.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page, type Request } from "playwright/test";

type Language = "ar" | "en";
type Identity = "owner" | "reader" | "limited" | "foreign";
type Tab = "routes" | "launch" | "zones";
type Frame = {
  ms: number; route: string; board: boolean; host: boolean; topbar: boolean;
  tabs: number; enabledTabs: number; actions: number; skeleton: boolean;
  fallback: boolean; workspace: boolean; surface: boolean; rows: number;
  assigned: boolean; unassigned: boolean; a2: boolean; moneyA2: boolean;
  docWidth: number; clientWidth: number;
  shell: boolean; stage: boolean; mainStage: boolean;
  priorProducts: boolean; priorInventory: boolean; priorHeader: boolean;
  layoutFallback: boolean; accessFallback: boolean; previousVisible: boolean;
  dispatchNeutral: boolean; structuralPlaceholder: boolean;
  contentVisible: boolean; visibleBlank: boolean; source: string;
  topbarDomId: number | null; boardDomId: number | null;
  foregroundTarget: string;
};
type RequestEntry = { path: string; at: number; ms?: number; status?: number; failed?: boolean };
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const apiPaths = new Set([
  "/inventory/access/me", "/dispatch/init", "/dispatch/shops",
  "/dispatch/active_routes", "/dispatch/shortages", "/dispatch/zones",
  "/inventory/access/locations/capabilities",
]);
const tabLabels: Record<Tab, RegExp> = {
  routes: /الخطوط النشطة|Active routes/,
  launch: /إطلاق خط جديد|Launch route/,
  zones: /هيكلة المناطق|Zones & shops/,
};
const navPaths = { dispatch: 1, inventory: 2, products: 4 } as const;
test.use({ baseURL: "http://127.0.0.1:4173", browserName: "chromium",
  trace: "retain-on-failure", screenshot: "only-on-failure" });
test.describe.configure({ mode: "serial" });

async function signIn(page: Page, who: Identity, lang: Language) {
  await page.goto("/");
  await page.evaluate(language => {
    localStorage.clear();
    localStorage.setItem("wanasah.language", language);
  }, lang);
  await page.goto("/login");
  await page.reload();
  const user = state.credentials[who];
  await page.locator("#company-code").fill(user.code);
  await page.locator("#username").fill(user.username);
  await page.locator("#password").fill(user.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function go(page: Page, path: keyof typeof navPaths, mobile: boolean) {
  if (mobile) await page.locator(".dashboard-mobile-menu").click();
  await page.locator(".operations-nav button").nth(navPaths[path]).click();
  await expect(page).toHaveURL(new RegExp("/" + path + "$"), { timeout: 30000 });
}

function traceNetwork(page: Page) {
  const all: RequestEntry[] = [];
  const inFlight = new Map<Request, RequestEntry>();
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (!apiPaths.has(path)) return;
    const entry: RequestEntry = { path, at: Date.now() };
    all.push(entry);
    inFlight.set(request, entry);
  });
  page.on("response", response => {
    const entry = inFlight.get(response.request());
    if (entry) { entry.ms = Date.now() - entry.at; entry.status = response.status(); }
  });
  page.on("requestfailed", request => {
    const entry = inFlight.get(request);
    if (entry) { entry.failed = true; inFlight.delete(request); }
  });
  page.on("requestfinished", request => { inFlight.delete(request); });
  return all;
}

function installFirstPaintProbe({ assigned, unassigned, a2 }:
  { assigned: string; unassigned: string; a2: string }) {
    const host = window as any;
    host.__d15FirstPaint?.stop?.();
    const probe: any = { start: performance.now(), frames: [], shifts: 0, stopped: false };
    const identities = new WeakMap<Element, number>();
    let nextId = 1;
    const nodeId = (el: Element | null): number | null => {
      if (!el) return null;
      if (!identities.has(el)) identities.set(el, nextId++);
      return identities.get(el)!;
    };
    host.__d15FirstPaint = probe;
    const visible = (el: Element | null): el is Element => {
      if (!el || el.closest('[aria-hidden="true"]')) return false;
      const css = getComputedStyle(el), rect = el.getBoundingClientRect();
      return css.display !== "none" && css.visibility !== "hidden" &&
        rect.width > 1 && rect.height > 1;
    };
    const observer = new PerformanceObserver(list => {
      for (const item of list.getEntries() as any[]) {
        if (!item.hadRecentInput) probe.shifts += item.value || 0;
      }
    });
    try { observer.observe({ type: "layout-shift", buffered: false } as any); }
    catch { /* unsupported environment is explicit in output */ }
    const capture = () => {
      if (probe.stopped) return;
      const board = document.querySelector(".dispatch-board");
      const top = document.querySelector('[data-testid="dispatch-shared-topbar"]');
      const tabs = [...document.querySelectorAll(".dispatch-board [role=tab]")].filter(visible);
      const topButtons = top ? [...top.querySelectorAll("button")].filter(visible) : [];
      const shopRows = [...document.querySelectorAll(".dispatch-shop-table tbody tr")]
        .filter(visible).map(el => el.textContent || "");
      const rowText = shopRows.join(" ");
      const latinMoney = rowText.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-0x660))
        .replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-0x6f0))
        .replace(/٫/g,".").replace(/٬/g,",");
      const root = document.documentElement;
      const shell = visible(document.querySelector(".dashboard-shell"));
      const stage = visible(document.querySelector(".dashboard-main-stage"));
      const mainStage = visible(document.querySelector(".dashboard-content"));
      const priorProducts = visible(document.querySelector(".products-a11y-scope"));
      const priorInventory = visible(document.querySelector(".inventory-workspace")) ||
        visible(document.querySelector(".inventory-data-panel")) ||
        visible(document.querySelector("[data-inventory-pending-surface]"));
      const priorHeader = priorProducts &&
        visible(document.querySelector(".products-a11y-scope .workspace-top-bar-frame"));
      const layoutFallback = visible(document.querySelector(".dashboard-content > [role=status]"));
      const accessFallback = visible(document.querySelector(".dashboard-access-state"));
      const dispatchNeutral = visible(document.querySelector("[data-testid=dispatch-neutral-topbar]"));
      const structuralPlaceholder = visible(document.querySelector(
        "[data-testid=dispatch-structural-workspace]")) ||
        visible(document.querySelector('[data-testid-workspace="dispatch-structure"]'));
      const previousVisible = priorProducts || priorInventory;
      // Content visibility is stricter than the existence of the unpainted main container.
      // Do not misclassify a route change as blank while old Products or Inventory still paints.
      const contentVisible = previousVisible || visible(top) || visible(document.querySelector(".dispatch-content")) ||
        structuralPlaceholder || layoutFallback || accessFallback;
      const visibleBlank = !contentVisible;
      const source = previousVisible ? priorProducts ? "previous-products-visible" : "previous-inventory-visible"
        : visible(top) ? tabs.length > 0 ? "dispatch-live-tabs" : dispatchNeutral ? "dispatch-neutral-topbar" : "dispatch-topbar-no-tabs"
        : layoutFallback ? "layout-suspense-fallback"
        : accessFallback ? "layout-access-fallback"
        : structuralPlaceholder ? "dispatch-cold-structure"
        : visible(document.querySelector(".dispatch-content")) ? "dispatch-content-without-topbar"
        : stage && mainStage ? "empty-dashboard-main-stage"
        : shell ? "dashboard-shell-no-main-content"
        : "root-route-suspense-null-or-no-dashboard-shell";
      const center = document.elementFromPoint(window.innerWidth/2, window.innerHeight/2);
      probe.frames.push({
        ms: Math.round(performance.now() - probe.start),
        route: location.pathname,
        board: visible(board), host: visible(document.querySelector('[data-persistent-dispatch-host="true"]')) ||
          Boolean(document.querySelector('[data-persistent-dispatch-host="true"]:not([aria-hidden="true"])')),
        topbar: visible(top), tabs: tabs.length,
        enabledTabs: tabs.filter(el => !(el as HTMLButtonElement).disabled).length,
        actions: topButtons.filter(el => el.getAttribute("role") !== "tab").length,
        skeleton: visible(document.querySelector('[data-testid="dispatch-quiet-loading"]')),
        fallback: visible(document.querySelector(".dashboard-content > [role=status]")),
        workspace: visible(document.querySelector(".dispatch-content")),
        surface: visible(document.querySelector(".dispatch-surface")) ||
          visible(document.querySelector(".dispatch-launch-config")) ||
          visible(document.querySelector(".dispatch-zones-workbench")),
        rows: shopRows.length,
        assigned: rowText.includes(assigned), unassigned: rowText.includes(unassigned),
        a2: rowText.includes(a2), moneyA2: latinMoney.includes("901.125"),
        docWidth: root.scrollWidth, clientWidth: root.clientWidth,
        shell, stage, mainStage,
        priorProducts, priorInventory, priorHeader,
        layoutFallback, accessFallback, previousVisible,
        dispatchNeutral, structuralPlaceholder,
        contentVisible, visibleBlank, source,
        topbarDomId: visible(top) ? nodeId(top) : null,
        boardDomId: visible(board) ? nodeId(board) : null,
        foregroundTarget: center ? center.tagName.toLowerCase() +
          "." + [...center.classList].slice(0,2).join(".") : "none",
      } as Frame);
      if (performance.now() - probe.start < 2800) requestAnimationFrame(capture);
      else observer.disconnect();
    };
    probe.stop = () => { probe.stopped = true; observer.disconnect(); };
    requestAnimationFrame(capture);
}
const sampleIdentity = { assigned: state.shops.assigned.name,
  unassigned: state.shops.unassigned.name, a2: state.shops.a2.name };
async function startProbe(page: Page) {
  await page.evaluate(installFirstPaintProbe, sampleIdentity);
}

async function readProbe(page: Page) {
  return page.evaluate(() => {
    const probe = (window as any).__d15FirstPaint;
    return { frames: probe?.frames as Frame[] || [],
      shifts: probe?.shifts as number || 0 };
  });
}
async function cssMotion(page: Page) {
  return page.evaluate(() => {
    const active = [...document.querySelectorAll(".dispatch-board *")]
      .filter(node => node.getClientRects().length > 0 &&
        !node.closest('[aria-hidden="true"]'));
    const findings: Array<{ element: string; animation: string; duration: string;
      transition: string; transitionDuration: string }> = [];
    for (const el of active) {
      const c = getComputedStyle(el);
      const animated = c.animationName !== "none" &&
        c.animationDuration.split(",").some(x => parseFloat(x) > 0);
      const transitioning = c.transitionProperty !== "none" &&
        c.transitionDuration.split(",").some(x => parseFloat(x) > 0);
      if (animated || transitioning) findings.push({
        element: el.tagName.toLowerCase() + "." + [...el.classList].slice(0,3).join("."),
        animation: c.animationName, duration: c.animationDuration,
        transition: c.transitionProperty, transitionDuration: c.transitionDuration,
      });
    }
    return findings.slice(0,40);
  });
}
function summarize(frames: Frame[]) {
  const routeFrames = frames.filter(x => x.route === "/dispatch");
  const first = (f: (x: Frame) => boolean) => routeFrames.find(f)?.ms ?? null;
  const firstTabs = routeFrames.findIndex(x => x.tabs > 0);
  const removedAfterPresent = firstTabs < 0 ? 0 :
    routeFrames.slice(firstTabs + 1).filter(x => x.tabs === 0).length;
  const firstStable = routeFrames.findIndex((_, index) =>
    routeFrames.slice(index, index + 4).length === 4 &&
    routeFrames.slice(index, index + 4).every(x => x.topbar && x.tabs > 0 && x.workspace && x.surface));
  const totalBlank = routeFrames.filter(x => !x.topbar && !x.workspace).length;
  const stageBlank = routeFrames.filter(x => x.visibleBlank);
  const emptyStage = routeFrames.filter(x => x.source === "empty-dashboard-main-stage");
  const firstDispatch = routeFrames[0]?.ms ?? null;
  const labelsBefore = frames.filter(x => x.route !== "/dispatch" &&
    (x.priorProducts || x.priorInventory)).length;
  const topbarIds = [...new Set(routeFrames.map(x => x.topbarDomId).filter((x):x is number => x !== null))];
  const bySource: Record<string, number> = {};
  for (const x of routeFrames) bySource[x.source] = (bySource[x.source] || 0) + 1;
  return {
    frames: frames.length, dispatchFrames: routeFrames.length,
    firstDispatchFrameMs: routeFrames[0]?.ms ?? null,
    firstBoardMs: first(x => x.board), firstTopbarMs: first(x => x.topbar),
    firstTabsMs: first(x => x.tabs > 0), firstActionsMs: first(x => x.actions > 0),
    firstWorkspaceMs: first(x => x.workspace), firstSurfaceMs: first(x => x.surface),
    firstStableMs: firstStable >= 0 ? routeFrames[firstStable].ms : null,
    missingTabsFrames: routeFrames.filter(x => x.tabs === 0).length,
    missingWorkspaceFrames: routeFrames.filter(x => !x.workspace).length,
    neutralSkeletonFrames: routeFrames.filter(x => x.skeleton).length,
    fullBlankFrames: totalBlank,
    removedTabsAfterFirstSeen: removedAfterPresent,
    visibleBlankFrames: stageBlank.length, emptyMainStageFrames: emptyStage.length,
    previousRouteVisibleAfterPathCommit: routeFrames.filter(x => x.previousVisible).length,
    layoutFallbackFrames: routeFrames.filter(x => x.layoutFallback).length,
    accessFallbackFrames: routeFrames.filter(x => x.accessFallback).length,
    neutralTopbarFrames: routeFrames.filter(x => x.dispatchNeutral).length,
    structuralPlaceholderFrames: routeFrames.filter(x => x.structuralPlaceholder).length,
    priorPagePaintFrames: labelsBefore, firstDispatch,
    topbarMountIds: topbarIds, topbarRemounts: Math.max(0,topbarIds.length - 1),
    rootNoShellFrames: stageBlank.filter(x => !x.shell).length,
    sourceCounts: bySource,
    firstBlankFrames: stageBlank.slice(0,10).map(x => ({
      ms:x.ms, source:x.source, stage:x.stage, shell:x.shell,
      priorProducts:x.priorProducts, priorInventory:x.priorInventory,
      mainStage:x.mainStage, foregroundTarget:x.foregroundTarget
    })),
    maxRootOverflow: Math.max(0,...routeFrames.map(x => x.docWidth - x.clientWidth)),
  };
}

async function record(page: Page, label: string, action: () => Promise<void>,
  network: RequestEntry[], info: any, initAlready = false) {
  if (!initAlready) await startProbe(page);
  const started = Date.now();
  await action();
  await page.waitForTimeout(2850);
  const { frames, shifts } = await readProbe(page);
  const since = network.filter(x => x.at >= started);
  const counts: Record<string, number> = {};
  for (const x of since) counts[x.path] = (counts[x.path] || 0) + 1;
  const result = { label, ...summarize(frames), shifts,
    requests: counts, apiTotal: since.length,
    apiDurations: since.filter(x => x.ms != null).map(x => ({
      path: x.path, ms: x.ms, status: x.status, failed: x.failed,
    })),
    frames, motion: await cssMotion(page),
  };
  console.log("D15_FIRST_PAINT_EVIDENCE=" + JSON.stringify({
    label, ...summarize(frames), shifts, requests: counts, apiTotal: since.length,
    motion: result.motion,
  }));
  await page.screenshot({ path: info.outputPath("d15-" + label + ".png"), fullPage: true });
  if (process.env.D15_INDEPENDENT_ENFORCE === "1" &&
      /(cold|back-products|back-inventory|hard-reload)/.test(label)) {
    expect(result.visibleBlankFrames, label + " has physically empty visible frames").toBe(0);
    expect(result.removedTabsAfterFirstSeen, label + " tabs disappeared after showing").toBe(0);
    expect(result.motion.length, label + " active Dispatch motion remains").toBe(0);
    expect(result.maxRootOverflow, label + " exterior page overflow").toBe(0);
  }
  writeFileSync(info.outputPath("d15-" + label + ".json"), JSON.stringify(result,null,2));
  return result;
}

async function selectTab(page: Page, tab: Tab) {
  const b = page.getByRole("tab", { name: tabLabels[tab] });
  await expect(b).toBeVisible({ timeout: 40000 });
  await b.click();
  await expect(b).toHaveAttribute("aria-selected", "true");
}
async function shopsTab(page: Page, zone: string) {
  await selectTab(page, "zones");
  const choose = page.locator(".dispatch-zones-workbench > div").first()
    .getByText(zone, { exact: true }).first();
  await expect(choose).toBeVisible({ timeout: 30000 });
  await choose.click();
  await expect(page.locator(".dispatch-shop-table")).toBeVisible();
}
function toggle(kind: "reader" | "limited" | "reset", mode?: "on" | "off") {
  const args = ["-m", "tests.test_dispatch_d14_browser_fixture", kind];
  if(mode) args.push(mode);
  execFileSync("python", args, { cwd: resolve(process.cwd(),"../wa_backend"),
    stdio: "pipe", timeout: 25000 });
}

for (const lang of ["ar","en"] as const) for (const width of [1440,390]) {
  test("D15 independent first-paint real PG16 " + lang + " " + width, async ({page}, info) => {
    test.setTimeout(240000);
    const mobile = width === 390, network = traceNetwork(page);
    await page.setViewportSize({width,height:900});
    await signIn(page,"owner",lang);
    await page.goto("/products");
    await expect(page.locator(".workspace-top-bar-frame")).toBeVisible({timeout:45000});
    const evidence: any[] = [];
    evidence.push(await record(page,lang+"-"+width+"-cold",
      () => go(page,"dispatch",mobile),network,info));
    await expect(page.getByRole("tab")).toHaveCount(3,{timeout:45000});
    for(const tab of ["routes","launch","zones"] as const) {
      evidence.push(await record(page,lang+"-"+width+"-tab-"+tab,
        () => selectTab(page,tab),network,info));
    }
    for(const pageName of ["products","inventory"] as const) {
      evidence.push(await record(page,lang+"-"+width+"-dispatch-to-"+pageName,
        () => go(page,pageName,mobile),network,info));
      await expect(page.locator(".dashboard-content")).toBeVisible();
      evidence.push(await record(page,lang+"-"+width+"-back-"+pageName,
        () => go(page,"dispatch",mobile),network,info));
    }
    // Unlike SPA cold, this exercises App.tsx global Suspense during an actual
    // hard document navigation. The witness is installed before any app bundle.
    await page.addInitScript(installFirstPaintProbe, sampleIdentity);
    evidence.push(await record(page,lang+"-"+width+"-hard-reload",
      async () => { await page.reload({waitUntil:"domcontentloaded"});
        await expect(page).toHaveURL(/\/dispatch$/); },network,info,true));
    await page.evaluate(() => {
      (window as any).__d15NativeVisibility = [];
      document.addEventListener("visibilitychange",()=>
        (window as any).__d15NativeVisibility.push(document.visibilityState));
    });
    const other = await page.context().newPage();
    await other.goto("about:blank");
    await other.bringToFront();
    await page.waitForTimeout(260);
    const hiddenState = await page.evaluate(()=>document.visibilityState);
    evidence.push(await record(page,lang+"-"+width+"-native-focus",
      async()=>{ await page.bringToFront(); await other.close(); },
      network,info));
    const nativeEvents = await page.evaluate(
      ()=>(window as any).__d15NativeVisibility as string[]);
    console.log("D15_NATIVE_FOCUS=" + JSON.stringify({lang,width,hiddenState,
      nativeEvents,nativeHiddenObserved:nativeEvents.includes("hidden")}));
    writeFileSync(info.outputPath("d15-"+lang+"-"+width+"-all.json"),
      JSON.stringify({lang,width,commit:process.env.GITHUB_SHA||"local",
        native:{hiddenState,nativeEvents},evidence},null,2));
  });
}

for(const [lang,width] of [["ar",390],["en",1440]] as const) {
  test("D15 independent no-private-frame real PG16 " + lang + " " + width,
    async ({page},info)=>{
      test.setTimeout(240000);
      const network=traceNetwork(page);
      await page.setViewportSize({width,height:900});
      toggle("reset");
      await signIn(page,"limited",lang);
      await page.goto("/dispatch");
      await shopsTab(page,state.zones.a1);
      await expect(page.locator(".dispatch-shop-table tbody tr")
        .filter({hasText:state.shops.assigned.name})).toHaveCount(1);
      const limited=await record(page,lang+"-"+width+"-limited-reentry",
        async()=>{await selectTab(page,"routes");await shopsTab(page,state.zones.a1);},
        network,info);
      const l=limited.frames.filter((x:Frame)=>x.route==="/dispatch");
      expect(l.every((x:Frame)=>!x.a2&&!x.unassigned&&!x.moneyA2),
        "A1-only must never reveal A2 or unassigned Shops").toBe(true);

      await signIn(page,"reader",lang);
      await page.goto("/dispatch");
      await shopsTab(page,state.zones.a2);
      await expect(page.locator(".dispatch-shop-table tbody tr")
        .filter({hasText:state.shops.a2.name})).toHaveCount(1);
      const reader=await record(page,lang+"-"+width+"-reader-no-finance",
        async()=>{await selectTab(page,"routes");await shopsTab(page,state.zones.a2);},
        network,info);
      expect(reader.frames.every((x:Frame)=>!x.moneyA2),
        "Company directory reader must not see finance").toBe(true);

      const token=await page.evaluate(()=>localStorage.getItem("admin_token"));
      toggle("reader","on");
      await selectTab(page,"routes"); await shopsTab(page,state.zones.a2);
      await expect.poll(async() => {
        const text = await page.locator(".dispatch-shop-table tbody tr")
          .filter({hasText:state.shops.a2.name}).first().innerText();
        return text.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-0x660))
          .replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-0x6f0))
          .replace(/٫/g,".");
      },{timeout:20000}).toContain("901.125");
      expect(await page.evaluate(()=>localStorage.getItem("admin_token"))).toBe(token);
      toggle("reader","off");
      const revoked=await record(page,lang+"-"+width+"-revoke-same-token",
        async()=>{await selectTab(page,"routes");await shopsTab(page,state.zones.a2);},
        network,info);
      const unauthorized=revoked.frames.filter((x:Frame)=>x.route==="/dispatch"&&x.moneyA2);
      console.log("D15_REVOKED_MONEY_FRAMES="+JSON.stringify({lang,width,frames:unauthorized.map(
        (x:Frame)=>({ms:x.ms,tabs:x.tabs,rows:x.rows}))}));
      // Record the exact pre- and post-refresh frames; fail on any old money
      // after the route has returned to its Zones workspace.
      // Ignore the deliberate pre-click snapshot of the old active tab.
      // Assert after the first Route-tab frame (Shop table unmounted).
      const firstLeftZones=revoked.frames.findIndex((x:Frame,i:number)=>
        i>0&&x.route==="/dispatch"&&x.rows===0);
      expect(firstLeftZones,"route tab must mount before re-entering Zones").toBeGreaterThanOrEqual(0);
      expect(revoked.frames.slice(firstLeftZones)
        .every((x:Frame)=>!x.moneyA2),
        "no revoked finance value may appear after leaving previous Zones view").toBe(true);
      expect(await page.evaluate(()=>localStorage.getItem("admin_token"))).toBe(token);

      await signIn(page,"foreign",lang);
      await page.goto("/products");
      await expect(page.locator(".workspace-top-bar-frame")).toBeVisible({timeout:45000});
      const foreign=await record(page,lang+"-"+width+"-foreign-first-paint",
        async()=>{await go(page,"dispatch",width===390);await selectTab(page,"zones");},
        network,info);
      expect(foreign.frames.every((x:Frame)=>!x.assigned&&!x.unassigned&&!x.a2),
        "Company B cannot inherit Shop rows from company A").toBe(true);
      toggle("reset");
  });
}
