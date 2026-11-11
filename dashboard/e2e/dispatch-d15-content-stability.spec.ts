/**
 * Issue #919 — INDEPENDENT visual witness, distinct from Worker1 #918 implementation.
 * Genuine disposable PostgreSQL16, real signed FastAPI, production Vite, headed Chromium.
 * Inspect ACTUAL panel type every requestAnimationFrame, not just topbar/blank.
 * Delayed transport CONTINUES the real signed /dispatch/init GET; no fake response/grant.
 */
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

type Tab = "routes" | "launch" | "zones";
type Frame = {
  ms: number; path: string; target: Tab; tab: string; visibleOld: boolean;
  board: boolean; topbar: boolean; tabs: number; fake: boolean;
  fakeTable: boolean; fakeLoading: boolean; fakePills: boolean;
  real: boolean; wrong: boolean; panelKind: string; panelNode: number | null;
  inert: boolean; protectedCount: number; forbiddenA2: boolean; forbiddenUnassigned: boolean;
  moneyA2: boolean; animated: number; docOverflow: number; shell: boolean;
  viewportCenter: string; 
};
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const API = new Set(["/inventory/access/me", "/dispatch/init", "/dispatch/shops", "/dispatch/shortages", "/dispatch/active_routes"]);
const testDir = "node_modules/.cache/dispatch-d15-independent-content";
const labels: Record<Tab,RegExp> = {
  routes: /الخطوط النشطة|Active routes/,
  launch: /إطلاق خط جديد|Launch route/,
  zones: /هيكلة المناطق|Zones & shops/,
};
const refs = { routes: 1, inventory: 2, products: 4 } as const;
test.use({browserName:"chromium",trace:"retain-on-failure",screenshot:"only-on-failure"});
test.describe.configure({mode:"serial"});

async function login(page:Page,lang:"ar"|"en") {
  await page.goto("http://127.0.0.1:4173/");
  await page.evaluate(l=>{localStorage.clear();localStorage.setItem("wanasah.language",l)},lang);
  await page.goto("http://127.0.0.1:4173/login");
  await page.reload();
  const a=state.credentials.owner;
  await page.locator("#company-code").fill(a.code);
  await page.locator("#username").fill(a.username);
  await page.locator("#password").fill(a.password);
  await Promise.all([
    page.waitForURL(u=>u.pathname!=="/login",{timeout:30000}),
    page.locator('button[type="submit"]').click(),
  ]);
}
async function navigate(page:Page,dest:"products"|"inventory"|"routes",mobile:boolean) {
  if(mobile)await page.locator(".dashboard-mobile-menu").click();
  await page.locator(".operations-nav button").nth(refs[dest]).click();
  const path=dest==="routes"?"dispatch":dest;
  await expect(page).toHaveURL(new RegExp("/"+path+"$"),{timeout:30000});
}
async function tabClick(page:Page,target:Tab) {
  const node=page.getByRole("tab",{name:labels[target]});
  await expect(node).toBeVisible({timeout:40000});
  await expect(node).toBeEnabled({timeout:45000});
  await node.click();
  await expect(node).toHaveAttribute("aria-selected","true");
}

function witness({tab,a2,unassigned}:{tab:Tab;a2:string;unassigned:string}) {
  const w=window as any;
  w.__d15ContentStop?.();
  const nodes=new WeakMap<Element,number>();
  let id=0,stop=false;
  const frames:Frame[]=[];
  const began=performance.now();
  const nodeId=(node:Element|null)=>{
    if(!node)return null;
    if(!nodes.has(node))nodes.set(node,++id);
    return nodes.get(node)!;
  };
  const visible=(el:Element|null):boolean=>{
    if(!el||el.closest('[aria-hidden="true"]'))return false;
    const rect=el.getBoundingClientRect(),c=getComputedStyle(el);
    if(c.display==="none"||c.visibility==="hidden"||Number(c.opacity)===0)return false;
    if(rect.width<2||rect.height<2)return false;
    for(let p=el.parentElement;p;p=p.parentElement){
      const css=getComputedStyle(p);
      if(css.display==="none"||css.visibility==="hidden"||Number(css.opacity)===0)return false;
    }
    return true;
  };
  const first=(selectors:string)=>[...document.querySelectorAll(selectors)].find(visible)||null;
  const poll=()=>{
    if(stop)return;
    const board=first(".dispatch-board");
    const old=Boolean(first(".products-a11y-scope, .inventory-workspace, .inventory-data-panel, [data-inventory-pending-surface]"));
    const top=first('[data-testid="dispatch-shared-topbar"]');
    const tabs=top?[...top.querySelectorAll('[role="tab"]')].filter(visible):[];
    const fakeTable=Boolean(first('[aria-label="هيكل جدول التوزيع"], [aria-label="Dispatch table structure"]'));
    const fakeLoading=Boolean(first('[data-testid="dispatch-quiet-loading"],[data-testid="dispatch-structural-workspace"],[data-testid-workspace="dispatch-structure"]'));
    const fakePills=Boolean(first('[data-testid-workspace="dispatch-structure"] .grid.grid-cols-2,[data-testid-workspace="dispatch-structure"] .grid.grid-cols-4'));
    const fake=fakeTable||fakeLoading||fakePills;
    const routePanel=first(".dispatch-route-list");
    const launchPanel=first(".dispatch-launch-config");
    const launchSelects=launchPanel?[...launchPanel.querySelectorAll("button")].filter(visible).length:0;
    const zonesPanel=first(".dispatch-zones-workbench");
    const zonesTable=first(".dispatch-shop-table");
    const realRoutes=Boolean(board&&routePanel&&!fakeTable);
    const realLaunch=Boolean(board&&launchPanel&&launchSelects>=4&&
      launchPanel.querySelector('[data-testid="dispatch-launch-readiness"]')&&
      first(".dispatch-launch-config ~ table, .dispatch-launch-config ~ div table, .dispatch-content table"));
    const realZones=Boolean(board&&zonesPanel&&zonesTable);
    const detected=realRoutes?"routes":realLaunch?"launch":realZones?"zones":fake?"fabricated":"none";
    const real=detected===tab;
    const wrong=Boolean(board&&!old&&!fake&&!real);
    const panel=tab==="routes"?routePanel:tab==="launch"?launchPanel:zonesPanel;
    const forbiddenTxt=[...document.querySelectorAll(".dispatch-shop-table tbody tr")]
      .filter(visible).map(n=>n.textContent||"").join(" ");
    const countPrivate=[...document.querySelectorAll(".dispatch-shop-table tbody tr,.dispatch-route-row")]
      .filter(visible).length;
    const money=forbiddenTxt.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-0x660))
      .replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-0x6f0)).replace(/٫/g,".");
    const active=board?[...board.getAnimations({subtree:true})].filter(a=>a.playState==="running").length:0;
    const center=document.elementFromPoint(innerWidth/2,innerHeight/2);
    frames.push({
      ms:Math.round(performance.now()-began),path:location.pathname,target:tab,
      tab:[...tabs].find(t=>t.getAttribute("aria-selected")==="true")?.textContent?.trim()||"",
      visibleOld:old,board:Boolean(board),topbar:Boolean(top),tabs:tabs.length,
      fake,fakeTable,fakeLoading,fakePills,real,wrong,panelKind:detected,
      panelNode:visible(panel)?nodeId(panel):null,
      inert:Boolean(panel?.closest("[inert]")),
      protectedCount:countPrivate,forbiddenA2:forbiddenTxt.includes(a2),
      forbiddenUnassigned:forbiddenTxt.includes(unassigned),
      moneyA2:money.includes("901.125"),animated:active,
      docOverflow:Math.max(0,document.documentElement.scrollWidth-innerWidth),
      shell:Boolean(first(".dashboard-shell")),
      viewportCenter:center?.tagName.toLowerCase()||"none",
    });
    if(performance.now()-began<1900)requestAnimationFrame(poll);
  };
  w.__d15ContentFrames=frames;
  w.__d15ContentStop=()=>{stop=true};
  requestAnimationFrame(poll);
}

async function capture(page:Page,lang:string,width:number,target:Tab,label:string,
  action:()=>Promise<void>,network:string[],enforce:boolean,delayed:boolean) {
  await page.evaluate(witness,{tab:target,a2:state.shops.a2.name,unassigned:state.shops.unassigned.name});
  const marker=network.length;
  await action();
  await page.waitForTimeout(1940);
  const frames=await page.evaluate(()=>(window as any).__d15ContentFrames as Frame[]);
  const sample=frames.filter(f=>f.path==="/dispatch"&&!f.visibleOld);
  const realFrames=sample.filter(f=>f.real);
  const fakeFrames=sample.filter(f=>f.fake);
  const wrongFrames=sample.filter(f=>f.wrong);
  const panelIds=[...new Set(realFrames.map(f=>f.panelNode).filter((x):x is number=>x!==null))];
  const frameSample=sample.filter((f,i)=>f.fake||f.wrong||(i>0&&sample[i-1]?.panelKind!==f.panelKind))
    .slice(0,15).map(f=>({ms:f.ms,kind:f.panelKind,fakeTable:f.fakeTable,
      fakeLoading:f.fakeLoading,fakePills:f.fakePills,old:f.visibleOld,tabs:f.tabs,
      board:f.board,inert:f.inert,private:f.protectedCount}));
  const byPath:Object=Object.fromEntries([...API].map(p=>[p,network.slice(marker).filter(x=>x===p).length]));
  const summary={label,lang,width,target,delayed,frameTotal:frames.length,
    dispatchSample:sample.length,realFrames:realFrames.length,
    fakeFrames:fakeFrames.length,wrongFrames:wrongFrames.length,
    fakeByKind:Object.fromEntries(["fakeTable","fakeLoading","fakePills"].map(k=>[
      k,sample.filter(f=>(f as any)[k]).length])),
    nodeCount:panelIds.length,
    switchedAfterReal:(()=>{let reached=false,changes=0;for(const f of sample){if(f.real)reached=true;else if(reached)changes++}return changes})(),
    missingTabsAfterSeen:(()=>{let saw=false,n=0;for(const f of sample){if(f.tabs>0)saw=true;else if(saw)n++}return n})(),
    noShell:sample.filter(f=>!f.shell).length,
    motionFrames:sample.filter(f=>f.animated>0).length,
    overflowMax:Math.max(0,...sample.map(f=>f.docOverflow)),
    oldVisibleAfterRoute:frames.filter(f=>f.path==="/dispatch"&&f.visibleOld).length,
    firstRealAt:realFrames[0]?.ms??null,
    signedNetwork:byPath,frameSample
  };
  console.log("D15_INDEPENDENT_VISUAL="+JSON.stringify(summary));
  mkdirSync(testDir,{recursive:true});
  const prefix=lang+"-"+width+"-"+label;
  writeFileSync(testDir+"/"+prefix+".json",JSON.stringify({summary,frames},null,2));
  await page.screenshot({path:testDir+"/"+prefix+"-settled.png",fullPage:true});
  if(enforce) {
    expect(fakeFrames.length,label+": fabricated table or grey form visible even ONE frame").toBe(0);
    expect(wrongFrames.length,label+": a visible unrelated panel replaced the true design").toBe(0);
    expect(realFrames.length,label+": actual selected tab never rendered").toBeGreaterThan(0);
    expect(panelIds.length,label+": panel changed DOM identity while awaiting genuine PG16 read").toBe(1);
    expect(summary.switchedAfterReal,label+": returned to placeholder after showing real panel").toBe(0);
    expect(summary.missingTabsAfterSeen,label+": toolbar buttons disappeared after paint").toBe(0);
    expect(summary.motionFrames,label+": active CSS motion").toBe(0);
    expect(summary.overflowMax,label+": document horizontal overflow").toBe(0);
  }
  return summary;
}

for(const lang of ["ar","en"] as const)for(const width of [1440,390] as const){
  test("D15 #919 genuinely correct visual panel every rAF "+lang+" "+width,async({page})=>{
    test.setTimeout(240000);
    await page.setViewportSize({width,height:900});
    await login(page,lang);
    await page.goto("http://127.0.0.1:4173/products");
    await expect(page.locator(".workspace-top-bar-frame")).toBeVisible({timeout:45000});
    const network:string[]=[];
    page.on("request",r=>{let path=new URL(r.url()).pathname;if(API.has(path))network.push(path)});
    const enforce=process.env.D15_CONTENT_ENFORCE==="1";
    let pendingShot:string|null=null;
    // Bounded network hold uses same real signed server and response bytes.
    await page.route("**/dispatch/init",async route=>{
      if(pendingShot){
        const screenshotName=pendingShot;
        pendingShot=null;
        await page.waitForTimeout(480);
        await page.screenshot({path:testDir+"/"+lang+"-"+width+"-"+screenshotName+"-real-pending.png",fullPage:true});
      }
      await route.continue();
    });
    mkdirSync(testDir,{recursive:true});
    const seen:Record<Tab,number>={routes:0,launch:0,zones:0};
    pendingShot="cold-routes";
    const cold=await capture(page,lang,width,"routes","cold",
      ()=>navigate(page,"routes",width===390),network,enforce,true);
    seen.routes+=cold.fakeFrames;
    await expect(page.getByRole("tab",{name:labels.routes})).toBeEnabled({timeout:45000});
    for(const tab of ["routes","launch","zones"] as const){
      await tabClick(page,tab);
      const switched=await capture(page,lang,width,tab,"tab-"+tab,
        async()=>{await page.getByRole("tab",{name:labels[tab]}).focus()},network,enforce,false);
      seen[tab]+=switched.fakeFrames;
      for(const from of ["products","inventory"] as const){
        await navigate(page,from,width===390);
        pendingShot=tab+"-from-"+from;
        const result=await capture(page,lang,width,tab,tab+"-from-"+from,
          ()=>navigate(page,"routes",width===390),network,enforce,true);
        seen[tab]+=result.fakeFrames;
        // Real selected tab should be preserved through the page navigation.
        await expect(page.getByRole("tab",{name:labels[tab]})).toHaveAttribute("aria-selected","true");
      }
    }
    // Browser actual Back / Forward, distinct from SPA side navigation.
    await navigate(page,"products",width===390);
    const history=await capture(page,lang,width,"zones","history-back",
      async()=>{await page.goBack();await expect(page).toHaveURL(/\/dispatch$/)},network,enforce,false);
    seen.zones+=history.fakeFrames;
    await page.goForward(); await expect(page).toHaveURL(/\/products$/);
    const forwardBack=await capture(page,lang,width,"zones","history-forward-back",
      async()=>{await page.goBack();await expect(page).toHaveURL(/\/dispatch$/)},network,enforce,false);
    seen.zones+=forwardBack.fakeFrames;

    const events=await page.evaluate(()=>{
      (window as any).__d15NativeEvents=[];
      document.addEventListener("visibilitychange",()=> (window as any).__d15NativeEvents.push(document.visibilityState));
      return document.visibilityState;
    });
    const second=await page.context().newPage();
    await second.goto("about:blank");
    await second.bringToFront();
    await page.waitForTimeout(250);
    const hidden=await page.evaluate(()=>document.visibilityState);
    const focused=await capture(page,lang,width,"zones","browser-refocus",
      async()=>{await page.bringToFront();await second.close()},network,enforce,false);
    seen.zones+=focused.fakeFrames;
    const native=await page.evaluate(()=>(window as any).__d15NativeEvents);
    console.log("D15_INDEPENDENT_NATIVE="+JSON.stringify({lang,width,beforeState:events,hiddenState:hidden,nativeEvents:native,nativeHiddenObserved:native.includes("hidden")}));
    console.log("D15_INDEPENDENT_TOTAL="+JSON.stringify({lang,width,byTab:seen,totalFake:Object.values(seen).reduce((a,b)=>a+b,0),scope:process.env.D15_CONTENT_ENFORCE==="1"?"AFTER":"BEFORE"}));
    if(!enforce)expect(seen.routes+seen.launch+seen.zones,"baseline should expose original user-reported fake panels").toBeGreaterThan(0);
  });
}
