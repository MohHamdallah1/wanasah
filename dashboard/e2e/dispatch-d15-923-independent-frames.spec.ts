/**
 * WANASAH #923 - independent per-paint Launch visual/security witness.
 * All data, sessions and roles originate in real isolated PG16/FastAPI.
 * Delays affect the original GET transport only, never payloads or grants.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";
const fixture=JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!,"utf8"));
const origin="http://127.0.0.1:4173";
const before=process.env.D15_923_PHASE==="before";
const folder="node_modules/.cache/d15-923-independent-"+(before?"before":"after");
test.use({browserName:"chromium",trace:"retain-on-failure"});
test.describe.configure({mode:"serial"});
type Frame={ms:number;path:string;panel:boolean;selected:boolean;gold:string;goldMatches:boolean;
  selectedCount:number;tabs:number;tabDisabled:boolean;tabText:string;
  panelIdentity:boolean;settingsIdentity:boolean;productIdentity:boolean;fieldIdentity:boolean;
  fieldNames:string[];fieldValues:string[];fieldDisabled:boolean[];inert:boolean;
  checkText:boolean;checkContent:string;readinessBusy:string|null;readinessHeight:number;
  settingsHeight:number;settingsTop:number;productTop:number;scrollTop:number;
  activeAnimations:number;rootOverflow:number;privateRows:number;launchDisabled:boolean;
  transientAccess:boolean;};
type Reference={panel:Element;config:Element;product:Element;fields:Element[];gold:string;
  height:number;top:number;productTop:number;scrollTop:number;initialLabels:string[];};
const findLaunch=(page:Page)=>page.getByTestId("dispatch-launch-workspace");
async function signIn(page:Page,language:"ar"|"en") {
  await page.goto(origin+"/");
  await page.evaluate(lang=>{localStorage.clear();localStorage.setItem("wanasah.language",lang)},language);
  await page.goto(origin+"/login");await page.reload();
  const a=fixture.credentials.owner;
  await page.locator("#company-code").fill(a.code);
  await page.locator("#username").fill(a.username);
  await page.locator("#password").fill(a.password);
  await Promise.all([page.waitForURL(u=>u.pathname!=="/login",{timeout:30000}),
    page.locator('button[type="submit"]').click()]);
}
async function go(page:Page,where:"dispatch"|"products"|"inventory",mobile:boolean) {
  if(mobile)await page.locator(".dashboard-mobile-menu").click();
  const index=where==="dispatch"?1:where==="inventory"?2:4;
  await page.locator(".operations-nav button").nth(index).click();
  await expect(page).toHaveURL(new RegExp("/"+where+"$"),{timeout:30000});
}
async function selectFour(page:Page) {
  const fields=page.locator(".dispatch-launch-config > div.relative.mt-2");
  await expect(fields).toHaveCount(4);
  let selected=0;
  for(const index of [3,0,1,2]){
    const field=fields.nth(index),button=field.locator(":scope > div.relative > button");
    await expect(button).toBeVisible();
    if(await button.isDisabled()) continue;
    await button.click();
    const opt=field.locator("div.absolute.top-full button");
    if(await opt.count()){await opt.first().click();selected++}else await button.click();
  }
  return selected;
}
async function prepare(page:Page) {
  await page.goto(origin+"/dispatch");
  await expect(page.getByRole("tab").nth(1)).toBeEnabled({timeout:35000});
  await page.getByRole("tab").nth(1).click();
  await expect(findLaunch(page)).toBeVisible({timeout:30000});
  await expect(findLaunch(page)).not.toHaveAttribute("inert","",{timeout:30000});
  const selected=await selectFour(page);
  await expect(page.locator(".dispatch-launch-config")).toBeVisible();
  await expect(page.getByTestId("d11-commercial-preflight")).toBeVisible();
  await page.waitForTimeout(350);
  return selected;
}
async function attachReference(page:Page) {
  await page.evaluate(()=>{
    const w=window as any;
    const panel=document.querySelector('[data-testid="dispatch-launch-workspace"]')!;
    const config=panel.querySelector(".dispatch-launch-config")!;
    const product=config.nextElementSibling!;
    const fields=[...config.querySelectorAll("div.relative.mt-2 > div.relative > button")];
    const tab=document.querySelectorAll('.dispatch-tab-list [role="tab"]')[1]!;
    const cr=config.getBoundingClientRect(),pr=product.getBoundingClientRect();
    const labels=[...config.querySelectorAll(":scope > div.relative.mt-2 > span")].map(x=>x.textContent?.trim()||"");
    w.__indRef={panel,config,product,fields,gold:getComputedStyle(tab).backgroundColor,
      height:cr.height,top:cr.top,productTop:pr.top,scrollTop:(panel as HTMLElement).scrollTop,initialLabels:labels};
  });
}
async function arm(page:Page,label:string) {
  await page.evaluate(label=>{
    const w=window as any;
    w.__indFrames=[];w.__indStop=true;
    const ref=w.__indRef as Reference;
    const begin=performance.now();
    const observe=()=>{
      if(w.__indRunToken!==label)return;
      if(location.pathname==="/dispatch"){
        const panel=document.querySelector('[data-testid="dispatch-launch-workspace"]') as HTMLElement|null;
        if(panel&&panel.getClientRects().length>0&&panel.getBoundingClientRect().height>0){
          const config=panel.querySelector(".dispatch-launch-config") as HTMLElement|null;
          const product=config?.nextElementSibling as HTMLElement|null;
          const fields=config?[...config.querySelectorAll("div.relative.mt-2 > div.relative > button")] as HTMLButtonElement[]:[];
          const tabs=[...document.querySelectorAll('.dispatch-tab-list [role="tab"]')] as HTMLButtonElement[];
          const tab=tabs[1];
          const ready=config?.querySelector('[data-testid="d11-commercial-preflight"]') as HTMLElement|null;
          const settingsRect=config?.getBoundingClientRect(),productRect=product?.getBoundingClientRect();
          const vals=fields.map(x=>x.querySelector("span")?.textContent?.trim()||x.textContent?.trim()||"");
          const names=config?[...config.querySelectorAll(":scope > div.relative.mt-2 > span")].map(x=>x.textContent?.trim()||""):[];
          const launch=panel.querySelector('.sticky.bottom-0 button') as HTMLButtonElement|null;
          const text=ready?.textContent||"";
          const statusEl=document.querySelector(".dashboard-access-state");
          const f:Frame={
            ms:Math.round(performance.now()-begin),path:location.pathname,panel:true,
            selected:tab?.getAttribute("aria-selected")==="true",
            gold:tab?getComputedStyle(tab).backgroundColor:"none",
            goldMatches:tab?getComputedStyle(tab).backgroundColor===ref.gold:false,
            selectedCount:tabs.filter(t=>t.getAttribute("aria-selected")==="true").length,
            tabs:tabs.length,tabDisabled:!!tab?.disabled,tabText:tab?.textContent?.trim()||"",
            panelIdentity:panel===ref.panel,settingsIdentity:config===ref.config,
            productIdentity:product===ref.product,
            fieldIdentity:fields.length===4&&fields.every((e,i)=>e===ref.fields[i]),
            fieldNames:names,fieldValues:vals,fieldDisabled:fields.map(x=>x.disabled),
            inert:panel.hasAttribute("inert"),checkText:/جاري التحقق من الإعدادات الحالية|Checking current company|Checking current settings/i.test(text),
            checkContent:text.slice(0,260),readinessBusy:ready?.getAttribute("aria-busy")||null,
            readinessHeight:ready?.getBoundingClientRect().height||0,
            settingsHeight:settingsRect?.height||-1,settingsTop:settingsRect?.top||-1,
            productTop:productRect?.top||-1,scrollTop:panel.scrollTop,
            activeAnimations:[...panel.getAnimations({subtree:true})].filter(x=>x.playState==="running").length,
            rootOverflow:Math.max(0,document.documentElement.scrollWidth-innerWidth),
            privateRows:[...panel.querySelectorAll(".dispatch-shop-table tbody tr")].length,
            launchDisabled:launch?launch.disabled:true,transientAccess:!!statusEl
          };
          w.__indFrames.push(f);
        }
      }
      if(performance.now()-begin<2250)requestAnimationFrame(observe);
    };
    w.__indRunToken=label;requestAnimationFrame(observe);
  },label);
}
async function snapshot(page:Page,label:string, chosen:number, pendingRequests:string[]){
  await page.waitForTimeout(2300);
  const data=await page.evaluate(()=>(window as any).__indFrames as Frame[]);
  const reference=await page.evaluate(()=>{
    const r=(window as any).__indRef as Reference;
    return {height:r.height,top:r.top,productTop:r.productTop,scrollTop:r.scrollTop,
      gold:r.gold,labels:r.initialLabels};
  });
  const bad=data.filter(f=>!f.selected||!f.goldMatches||f.selectedCount!==1);
  const preflight=data.filter(f=>f.checkText);
  const shift=data.map(f=>Math.abs(f.productTop-reference.productTop));
  const height=data.map(f=>Math.abs(f.settingsHeight-reference.height));
  const tops=data.map(f=>Math.abs(f.settingsTop-reference.top));
  const scrolls=data.map(f=>Math.abs(f.scrollTop-reference.scrollTop));
  const remount=data.filter(f=>!f.panelIdentity||!f.settingsIdentity||!f.productIdentity||!f.fieldIdentity);
  const locked=data.filter(f=>f.inert);
  const enabledPending=locked.filter(f=>!f.tabDisabled||f.fieldDisabled.some(d=>!d)||!f.launchDisabled);
  const valueKeys=[...new Set(data.map(f=>f.fieldValues.join(" / ")))];
  const selectedColors=[...new Set(data.map(f=>f.gold))];
  const summary={label,chosen,frames:data.length,goldLost:bad.length,checkingFrames:preflight.length,
    checkingText:preflight[0]?.checkContent||"",goldColors:selectedColors,
    maxProductTopShift:Math.max(0,...shift),maxSettingsHeightShift:Math.max(0,...height),
    maxSettingsTopShift:Math.max(0,...tops),maxScrollShift:Math.max(0,...scrolls),
    remount:remount.length,controlsCountInvalid:data.filter(f=>f.fieldValues.length!==4).length,
    selectorLabelInvalid:data.filter(f=>f.fieldNames.join("|")!==reference.labels.join("|")).length,
    selectorValueVariants:valueKeys.length,firstValues:data[0]?.fieldValues,
    lastValues:data.at(-1)?.fieldValues,pendingRaf:locked.length,
    pendingUnauthorized:enabledPending.length,visibleAccessFrames:data.filter(f=>f.transientAccess).length,
    anomalousReady:locked.filter(f=>!f.launchDisabled).length,
    overflowRaf:data.filter(f=>f.rootOverflow>0).length,
    animationRaf:data.filter(f=>f.activeAnimations>0).length,requests:pendingRequests};
  mkdirSync(folder,{recursive:true});
  writeFileSync(folder+"/"+label+".json",JSON.stringify({summary,reference,frames:data},null,2));
  await page.screenshot({path:folder+"/"+label+"-settled.png",fullPage:true});
  console.log("D15_923_INDEPENDENT_FRAME="+JSON.stringify(summary));
  expect(summary.frames).toBeGreaterThan(10);
  expect(summary.chosen).toBe(4);
  if(before){
    expect(summary.goldLost+summary.checkingFrames+Number(summary.maxProductTopShift>2),
      "BEFORE must reproduce at least one owner-reported issue").toBeGreaterThan(0);
  }else{
    expect(summary.goldLost,"gold launch selected tab flicker").toBe(0);
    expect(summary.checkingFrames,"transient commercial verification sentence").toBe(0);
    expect(summary.maxSettingsHeightShift,"config height jump").toBeLessThanOrEqual(2);
    expect(summary.maxSettingsTopShift,"config top jump").toBeLessThanOrEqual(2);
    expect(summary.maxProductTopShift,"product panel vertical jump").toBeLessThanOrEqual(2);
    expect(summary.maxScrollShift,"scroll jump").toBeLessThanOrEqual(2);
    expect(summary.remount,"workspace/forms/field DOM remount").toBe(0);
    expect(summary.controlsCountInvalid).toBe(0);
    expect(summary.selectorLabelInvalid).toBe(0);
    expect(summary.pendingUnauthorized).toBe(0);
    expect(summary.overflowRaf).toBe(0);
    expect(summary.animationRaf).toBe(0);
  }
  return summary;
}
for(const language of ["ar","en"] as const)for(const width of [1440,390] as const){
  test("independent #923 Launch colored tab, readiness and four fields "+language+" "+width,async({page})=>{
    test.setTimeout(180000);
    mkdirSync(folder,{recursive:true});
    await page.setViewportSize({width,height:900});await signIn(page,language);
    const selected=await prepare(page);
    await attachReference(page);
    const requests:string[]=[];
    let holding=false;
    const routeHold=async(route:any,kind:string,ms:number)=>{
      if(holding){requests.push(kind);await page.waitForTimeout(ms)}
      await route.continue();
    };
    await page.route("**/inventory/access/me",r=>routeHold(r,"access",350));
    await page.route("**/dispatch/init",r=>routeHold(r,"init",510));
    for(const dest of ["products","inventory"] as const){
      await go(page,dest,width===390);
      holding=true;
      const label=language+"-"+width+"-from-"+dest;
      await arm(page,label);
      await go(page,"dispatch",width===390);
      await page.waitForTimeout(200);
      await page.screenshot({path:folder+"/"+label+"-pending.png",fullPage:true});
      await snapshot(page,label,selected,[...requests]);
      await attachReference(page);
      holding=false;
    }
    await page.goBack();await expect(page).toHaveURL(/\/inventory$/);
    holding=true;
    const label=language+"-"+width+"-history";
    await arm(page,label);
    await page.goForward();await expect(page).toHaveURL(/\/dispatch$/);
    await snapshot(page,label,selected,[...requests]);
    holding=false;
    await page.evaluate(()=>{
      const w=window as any;w.__indHiddenEvents=[];
      document.addEventListener("visibilitychange",()=>w.__indHiddenEvents.push(document.visibilityState));
    });
    const second=await page.context().newPage();await second.goto("about:blank");
    await second.bringToFront();await page.waitForTimeout(180);
    const hidden=await page.evaluate(()=>document.visibilityState);
    await page.bringToFront();await second.close();
    const events=await page.evaluate(()=>(window as any).__indHiddenEvents);
    console.log("D15_923_NATIVE_FOCUS="+JSON.stringify({language,width,hidden,events}));
  });
}
test("independent #923 first Products and Inventory JS requests",async({browser})=>{
  const context=await browser.newContext();const page=await context.newPage();
  await signIn(page,"ar");const state=await context.storageState();await context.close();
  for(const route of ["products","inventory"]){
    const ctx=await browser.newContext({storageState:state});const p=await ctx.newPage();
    const scripts:string[]=[];p.on("request",r=>{const u=new URL(r.url());if(/\.js$/.test(u.pathname))scripts.push(u.pathname)});
    await p.goto(origin+"/"+route,{waitUntil:"domcontentloaded"});
    await expect(p).toHaveURL(new RegExp("/"+route+"$"));
    await p.waitForLoadState("networkidle",{timeout:25000});
    const loaded=scripts.filter(x=>/\/DispatchBoard-[^/]+\.js$/.test(x));
    console.log("D15_923_FIRST_ROUTE="+JSON.stringify({route,scriptCount:scripts.length,dispatchCount:loaded.length}));
    expect(loaded).toHaveLength(0);await ctx.close();
  }
});
