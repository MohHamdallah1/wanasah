import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page, type TestInfo } from "playwright/test";

// Real built Dashboard -> authorized FastAPI -> disposable PostgreSQL16.
// No page.route() fake success and no test.skip / test.fixme / xfail.
const API = "http://127.0.0.1:4174";
const data = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_P0_WIRE_STATE!, "utf8"));
const locale = (info: TestInfo) => info.project.name.split("-")[0] as "ar" | "en";
const unique = () => "D838-" + Math.random().toString(36).slice(2, 11);
type Wire = {status:number;body:any;bytes:number};

async function login(page: Page, info: TestInfo, credentials=data.credentials) {
  await page.goto("/login");
  await page.evaluate(value => localStorage.setItem("wanasah.language", value), locale(info));
  await page.reload();
  await page.locator("#company-code").fill(credentials.code);
  await page.locator("#username").fill(credentials.username);
  await page.locator("#password").fill(credentials.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", {timeout:25_000}),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.goto("/dispatch");
  await expect(page.locator(".dispatch-content")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", locale(info) === "ar" ? "rtl" : "ltr");
}

async function api(page: Page, method:string,path:string,body?:unknown):Promise<Wire> {
  const token = await page.evaluate(() => localStorage.getItem("admin_token"));
  expect(token, "Real user login must provide bearer").toBeTruthy();
  const res = await page.request.fetch(API+path,{
    method, headers:{Authorization:"Bearer "+token}, data:body,
    failOnStatusCode:false,
  });
  const raw=await res.text();
  let parsed:any;
  try{parsed=JSON.parse(raw)}catch{parsed=raw}
  return {status:res.status(),body:parsed,bytes:Buffer.byteLength(raw)};
}
async function addZone(page:Page,name:string){
  const r=await api(page,"POST","/dispatch/zones",{name});
  expect(r.status,JSON.stringify(r)).toBe(201);
  return String(r.body.zone_id ?? r.body.id);
}
async function addShop(page:Page,zoneId:string,name:string,amount=0,mapLink=""){
  const r=await api(page,"POST","/dispatch/shops",{
    name,owner:"Synthetic only",phone:"",mapLink,zoneId,initialDebt:amount,maxDebtLimit:1000,
  });
  expect(r.status,JSON.stringify(r)).toBe(201);
  return String(r.body.shop_id ?? r.body.id);
}
function dbProbe(mode:"snapshot"|"balance80",shopId?:string){
  const args=[resolve("../wa_backend/tests/dispatch_v1_browser_audit_fixture.py"),mode];
  if(shopId)args.push(shopId);
  const out=execFileSync(process.env.PYTHON||"python",args,{encoding:"utf8",env:process.env});
  if(mode==="snapshot"){
    const line=out.split("\n").find(x=>x.startsWith("DISPATCH_V1_DEEP_SNAPSHOT="));
    expect(line).toBeTruthy();
    return JSON.parse(line!.split("=",2)[1]) as any;
  }
  expect(out).toContain("DISPATCH_V1_DEEP_CONCURRENT_BALANCE=80");
  return null;
}
async function selectTab(page:Page, tab:"routes"|"launch"|"zones"){
  await page.locator(`button.dispatch-tab`).filter({hasText:tab==="routes"?"الخطوط النشطة":tab==="launch"?"إطلاق خط جديد":"هيكلة المناطق"}).click();
}
async function observe(page:Page,info:TestInfo){
  const records:{method:string;path:string;status:number;bytes:number}[]=[];
  page.on("response",r=>{
    if(!r.url().startsWith(API))return;
    records.push({method:r.request().method(),path:new URL(r.url()).pathname,
      status:r.status(),bytes:Number(r.headers()["content-length"]||0)});
  });
  return async () => {
    await info.attach("real-http-statuses.json",{body:Buffer.from(JSON.stringify(records,null,2)),contentType:"application/json"});
    await page.screenshot({path:info.outputPath("actual-ui-"+info.project.name+".png"),fullPage:true});
  };
}

test("real owner login → all three tabs / launch selectors / modal availability",async({page},info)=>{
  const finish=await observe(page,info);
  await login(page,info);
  await expect(page.locator(".dispatch-route-row").first()).toBeVisible();
  await selectTab(page,"launch");
  await expect(page.locator(".dispatch-content")).toBeVisible();
  await expect(page.getByText("اختر السيارة").first()).toBeVisible();
  await selectTab(page,"zones");
  await expect(page.locator(".dispatch-zones-workbench")).toBeVisible();
  await expect(page.getByText(data.initialShopName,{exact:true}).first()).toBeVisible();
  await selectTab(page,"routes");
  await expect(page.getByRole("button",{name:/طلبات ونواقص/})).toBeVisible();
  await finish();
});

test("N1: postponed representative selection abandoned on close preserves committed identity",async({page},info)=>{
  const finish=await observe(page,info);
  await login(page,info);
  const reset=await api(page,"PUT",`/dispatch/route/${data.routeId}/status`,{status:"waiting"});
  expect(reset.status).toBe(200);
  const postpone=await api(page,"PUT",`/dispatch/route/${data.routeId}/status`,{status:"postponed"});
  expect(postpone.status).toBe(200);
  await page.reload();
  await page.getByRole("button",{name:/عرض المؤجل/}).click();
  const modal=page.getByRole("dialog");
  await expect(modal).toBeVisible();
  const chooser=modal.locator("select").first();
  await expect(chooser).toHaveValue(String(data.driverId));
  await chooser.selectOption(String(data.secondDriverId));
  expect(dbProbe("snapshot").routes.find((x:any)=>x.id===String(data.routeId)).driverId)
    .toBe(String(data.driverId)); // actual server unchanged
  await page.keyboard.press("Escape");
  await expect(modal).not.toBeVisible();
  await page.getByRole("button",{name:/عرض المؤجل/}).click();
  await expect(page.getByRole("dialog").locator("select").first()).toHaveValue(String(data.driverId));
  await finish();
});
