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

async function startProbe(page: Page) {
  await page.evaluate(({ assigned, unassigned, a2 }) => {
    const host = window as any;
    host.__d15FirstPaint?.stop?.();
    const probe: any = { start: performance.now(), frames: [], shifts: 0, stopped: false };
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
      const root = document.documentElement;
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
        a2: rowText.includes(a2), moneyA2: rowText.includes("901.125") ||
          rowText.includes("٩٠١٫١٢٥") || rowText.includes("۹۰۱٫۱۲۵"),
        docWidth: root.scrollWidth, clientWidth: root.clientWidth,
      } as Frame);
      if (performance.now() - probe.start < 2800) requestAnimationFrame(capture);
      else observer.disconnect();
    };
    probe.stop = () => { probe.stopped = true; observer.disconnect(); };
    requestAnimationFrame(capture);
  }, { assigned: state.shops.assigned.name,
    unassigned: state.shops.unassigned.name, a2: state.shops.a2.name });
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
    maxRootOverflow: Math.max(0,...routeFrames.map(x => x.docWidth - x.clientWidth)),
  };
}

async function record(page: Page, label: string, action: () => Promise<void>,
  network: RequestEntry[], info: any) {
  await startProbe(page);
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
      await go(page,pageName,mobile);
      await expect(page.locator(".dashboard-content")).toBeVisible();
      evidence.push(await record(page,lang+"-"+width+"-back-"+pageName,
        () => go(page,"dispatch",mobile),network,info));
    }
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
      await expect(page.locator(".dispatch-shop-table tbody tr")
        .filter({hasText:state.shops.a2.name}).first()).toContainText("901", {timeout:20000});
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
      const firstReturned=revoked.frames.findIndex((x:Frame)=>x.route==="/dispatch"&&x.rows>0);
      if(firstReturned>=0) expect(revoked.frames.slice(firstReturned)
        .every((x:Frame)=>!x.moneyA2)).toBe(true);
      expect(await page.evaluate(()=>localStorage.getItem("admin_token"))).toBe(token);

      await signIn(page,"foreign",lang);
      const foreign=await record(page,lang+"-"+width+"-foreign-first-paint",
        async()=>{await page.goto("/dispatch");await shopsTab(page,state.zones.a1).catch(()=>{});},
        network,info);
      expect(foreign.frames.every((x:Frame)=>!x.assigned&&!x.unassigned&&!x.a2),
        "Company B cannot inherit Shop rows from company A").toBe(true);
      toggle("reset");
  });
}
