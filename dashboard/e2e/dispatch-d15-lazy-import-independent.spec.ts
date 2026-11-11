/**
 * #919 Final independent exact-HEAD gate. Test-only delay of genuine Vite JS,
 * no production changes, no fake API/auth/data, real PG16/FastAPI/Chromium.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Browser, type Page } from "playwright/test";

const fixture=JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!,"utf8"));
const root="node_modules/.cache/d15-919-lazy-final";
const origin="http://127.0.0.1:4173";
const dispatchJS=/\/assets\/DispatchBoard-[^/]+\.js(?:\?.*)?$/;
type Language="ar"|"en";
type Tab="routes"|"launch"|"zones";
type Frame={ms:number;kind:string;page:string;tabs:number;selected:string;
  rootVisible:boolean;fallback:boolean;realRoutes:boolean;realLaunch:boolean;realZones:boolean;
  fakeOld:boolean;contentNode:number|null;routeListNode:number|null;
  disabledActions:boolean;routeLabel:string;box:{x:number;y:number;w:number;h:number}|null;
  animated:number;overflow:number;privateRows:number};
const tabLabels:Record<Tab,RegExp>={
  routes:/الخطوط النشطة|Active routes/,
  launch:/إطلاق خط جديد|Launch route/,
  zones:/هيكلة المناطق|Zones & shops/,
};
test.use({browserName:"chromium",trace:"retain-on-failure"});
test.describe.configure({mode:"serial"});

async function ownerState(browser:Browser, lang:Language) {
  const c=await browser.newContext({viewport:{width:1440,height:900}});
  const page=await c.newPage();
  await page.goto(origin+"/");
  await page.evaluate(language=>{
    localStorage.clear();localStorage.setItem("wanasah.language",language);
  },lang);
  await page.goto(origin+"/login");await page.reload();
  const a=fixture.credentials.owner;
  await page.locator("#company-code").fill(a.code);
  await page.locator("#username").fill(a.username);
  await page.locator("#password").fill(a.password);
  await Promise.all([page.waitForURL(u=>u.pathname!=="/login",{timeout:30000}),
    page.locator('button[type="submit"]').click()]);
  const state=await c.storageState();
  await c.close();return state;
}
function scriptEntries(page:Page) {
  return page.evaluate(()=>{
    return performance.getEntriesByType("resource")
      .filter((e:any)=>e.initiatorType==="script"||/\.js(?:\?|$)/.test(e.name))
      .map((e:any)=>({url:new URL(e.name).pathname,initiator:e.initiatorType,
        encoded:e.encodedBodySize,transfer:e.transferSize,decoded:e.decodedBodySize}));
  });
}
function probe() {
  // Playwright serializes this function separately into the browser realm.
  // Keep every visual helper inside the injected function itself.
  const visible=(el:Element|null):boolean=>{
    if(!el||el.closest('[aria-hidden="true"]'))return false;
    const c=getComputedStyle(el),r=el.getBoundingClientRect();
    if(c.display==="none"||c.visibility==="hidden"||+c.opacity===0||r.width<2||r.height<2)return false;
    for(let p=el.parentElement;p;p=p.parentElement){
      const st=getComputedStyle(p);
      if(st.display==="none"||st.visibility==="hidden"||+st.opacity===0)return false;
    }
    return true;
  };
  const w=window as any;
  const frames:Frame[]=[];const nodes=new WeakMap<Element,number>();let next=0,stopped=false;
  const began=performance.now();
  const nodeId=(x:Element|null)=>{if(!x)return null;if(!nodes.has(x))nodes.set(x,++next);return nodes.get(x)!};
  const find=(q:string,root:ParentNode=document)=>
    [...root.querySelectorAll(q)].find(visible)||null;
  const tick=()=>{
    if(stopped)return;
    if(location.pathname==="/dispatch"){
      const host=find(".dispatch-board"),rootVisible=!!host;
      const chrome=host?find('[data-testid="dispatch-shared-topbar"]',host):null;
      const buttons=chrome?[...chrome.querySelectorAll('[role="tab"]')].filter(visible):[];
      const selected=buttons.find(x=>x.getAttribute("aria-selected")==="true")?.textContent?.trim()||"";
      const content=host?find(".dispatch-content",host):null;
      const realRoutes=!!(host&&find('[data-testid="dispatch-routes-workspace"]',host));
      const realLaunch=!!(host&&find('[data-testid="dispatch-launch-workspace"]',host)&&find(".dispatch-launch-config",host));
      const realZones=!!(host&&find('[data-testid="dispatch-zones-workspace"]',host)&&find(".dispatch-shop-table",host));
      const fallback=!!(host&&find('.dispatch-content[aria-busy="true"]',host)&&
        !realRoutes&&!realLaunch&&!realZones);
      const routeList=host?find(".dispatch-route-list",host):null;
      const fakeOld=!!find('[aria-label="هيكل جدول التوزيع"],[aria-label="Dispatch table structure"],[data-testid="dispatch-quiet-loading"]');
      const kind=fallback?"IMPORT_PENDING_ROUTES":realRoutes?"REAL_ROUTES":
        realLaunch?"REAL_LAUNCH":realZones?"REAL_ZONES":rootVisible?"NO_REAL_PANEL":"NO_CHROME";
      const r=content?.getBoundingClientRect();
      const pendingActions=host?[...host.querySelectorAll("button")].filter(visible):[];
      const routeLabel=find(".dispatch-panel-label",host??document)?.textContent?.trim()||"";
      const animations=host?[...host.getAnimations({subtree:true})].filter(a=>a.playState==="running").length:0;
      const privateRows=host?[...host.querySelectorAll(".dispatch-shop-table tbody tr,.dispatch-route-row")].filter(visible).length:0;
      frames.push({ms:Math.round(performance.now()-began),kind,page:location.pathname,tabs:buttons.length,
        selected,rootVisible,fallback,realRoutes,realLaunch,realZones,fakeOld,
        contentNode:nodeId(content),routeListNode:nodeId(routeList),
        disabledActions:pendingActions.every(b=>(b as HTMLButtonElement).disabled),
        routeLabel,box:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null,
        animated:animations,overflow:Math.max(0,document.documentElement.scrollWidth-innerWidth),
        privateRows});
    }
    if(performance.now()-began<5400)requestAnimationFrame(tick);
  };
  w.__d15LazyFrames=frames;w.__d15LazyStop=()=>{stopped=true};
  requestAnimationFrame(tick);
}
async function save(page:Page,label:string) {
  const frames=await page.evaluate(()=>(window as any).__d15LazyFrames as Frame[]);
  const fallback=frames.filter(f=>f.fallback),real=frames.filter(f=>f.realRoutes||f.realLaunch||f.realZones);
  const panelSequence=[...new Set(frames.map(f=>f.kind))];
  const contentIDs=[...new Set(frames.map(f=>f.contentNode).filter((x):x is number=>x!==null))];
  const routeIDs=[...new Set(frames.map(f=>f.routeListNode).filter((x):x is number=>x!==null))];
  const result={label,frames:frames.length,sequence:panelSequence,
    importPendingFrames:fallback.length,firstPendingAt:fallback[0]?.ms??null,
    firstRealAt:real[0]?.ms??null,contentNodes:contentIDs,routeListNodes:routeIDs,
    firstPendingSample:fallback[0]??null,firstRealSample:real[0]??null,
    wrongOld:frames.filter(f=>f.fakeOld).length,
    maxOuterOverflow:Math.max(0,...frames.map(f=>f.overflow)),
    animations:frames.filter(f=>f.animated>0).length};
  mkdirSync(root,{recursive:true});
  writeFileSync(root+"/"+label+".json",JSON.stringify({result,frames},null,2));
  console.log("D15_919_LAZY_FRAME="+JSON.stringify(result));
  return result;
}
test("independent exact-final Products and Inventory startup JS critical path",async({browser})=>{
  test.setTimeout(180000);
  const state=await ownerState(browser,"ar");
  for(const target of ["products","inventory"] as const){
    const ctx=await browser.newContext({viewport:{width:1440,height:900},storageState:state});
    const page=await ctx.newPage(),network:{url:string;kind:string}[]=[];
    page.on("request",r=>{
      const u=new URL(r.url());
      if(u.origin===origin && /\.(?:js|css)$/.test(u.pathname))
        network.push({url:u.pathname,kind:r.resourceType()});
    });
    await page.goto(origin+"/"+target,{waitUntil:"domcontentloaded"});
    await expect(page.locator(".dashboard-shell")).toBeVisible({timeout:40000});
    await page.waitForLoadState("networkidle",{timeout:25000});
    await page.waitForTimeout(450);
    const scripts=await scriptEntries(page);
    const lazy=network.filter(x=>dispatchJS.test(x.url));
    const result={target,path:new URL(page.url()).pathname,scriptCount:scripts.length,
      entry:network.filter(x=>/\/index-[^/]+\.js$/.test(x.url)),
      dispatchJS:lazy,network,scripts};
    mkdirSync(root,{recursive:true});
    writeFileSync(root+"/startup-"+target+".json",JSON.stringify(result,null,2));
    console.log("D15_919_STARTUP="+JSON.stringify(result));
    expect(result.path,"authorized owner must remain on requested route").toBe("/"+target);
    expect(lazy,"non-Dispatch startup must NOT download deferred DispatchBoard JS").toHaveLength(0);
    await ctx.close();
  }
});
for(const language of ["ar","en"] as const)for(const width of [1440,390] as const){
  test("independent exact-final deferred DispatchBoard JS import paint "+language+" "+width,
    async({browser})=>{
      test.setTimeout(180000);
      const state=await ownerState(browser,language);
      // New browser context prevents cached module code from bypassing genuine hold.
      const ctx=await browser.newContext({viewport:{width,height:900},storageState:state});
      const page=await ctx.newPage();
      let delayed=0;const fetched:string[]=[];
      page.on("request",r=>{if(dispatchJS.test(new URL(r.url()).pathname))fetched.push(r.url())});
      await page.addInitScript(probe);
      await page.route(dispatchJS,async route=>{
        delayed++;
        await page.waitForTimeout(1500);
        mkdirSync(root,{recursive:true});
        await page.screenshot({path:root+"/import-held-"+language+"-"+width+".png",fullPage:true});
        await route.continue(); // ORIGINAL REAL JS RESPONSE — no substitution.
      });
      await page.goto(origin+"/dispatch",{waitUntil:"domcontentloaded"});
      await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible({timeout:30000});
      await expect(page.getByTestId("dispatch-routes-workspace")).toBeVisible({timeout:30000});
      await page.waitForTimeout(1750);
      const label="lazy-"+language+"-"+width;
      const result=await save(page,label);
      await page.screenshot({path:root+"/import-resolved-"+language+"-"+width+".png",fullPage:true});
      console.log("D15_919_LAZY_IMPORT="+JSON.stringify({label,heldRequests:delayed,fetched}));
      expect(delayed,"TEST MUST ACTUALLY HOLD REAL DispatchBoard chunk").toBeGreaterThan(0);
      expect(fetched.length).toBeGreaterThan(0);
      expect(result.firstRealAt).not.toBeNull();
      // Strict final acceptance: a different temporary full workspace / DOM
      // replacement must fail, even if legacy synthetic-table marker is absent.
      expect(result.importPendingFrames,"Visible alternate Routes pane during JS import").toBe(0);
      expect(result.contentNodes.length,"Canonical content DOM was fully replaced").toBe(1);
      expect(result.routeListNodes.length,"Canonical route list remounted after import").toBe(1);
      expect(result.wrongOld).toBe(0);
      expect(result.maxOuterOverflow).toBe(0);
      await ctx.close();
    });
}
