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
  try {
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
  } finally {
    // Every locale/project shares this disposable route. A deliberately RED
    // assertion must not contaminate subsequent tests.
    const cleanup=await api(page,"PUT",`/dispatch/route/${data.routeId}/status`,{status:"waiting"});
    await info.attach("N1-reset.json",{body:Buffer.from(JSON.stringify(cleanup)),contentType:"application/json"});
    expect(cleanup.status).toBe(200);
    await finish();
  }
});

test("N2: cross-zone searched shop reorder sends the selected shop in real PUT",async({page},info)=>{
  await login(page,info);
  const tag=unique(), aName=tag+" A", bName=tag+" B", sa=tag+" Shop A", sb=tag+" Shop B";
  const a=await addZone(page,aName), b=await addZone(page,bName);
  await addShop(page,a,sa);
  const target=await addShop(page,b,sb);
  await page.reload();
  await selectTab(page,"zones");
  await page.getByText(aName,{exact:true}).first().click();
  await page.locator('input[placeholder="بحث..."]').fill(sb);
  const row=page.locator(".dispatch-shop-table tbody tr").filter({hasText:sb});
  await expect(row).toHaveCount(1);
  await page.getByRole("button",{name:"تعديل",exact:true}).click();
  const sequence=row.locator('input[type="number"]').first();
  await expect(sequence).toBeVisible();
  await sequence.fill("1");
  await sequence.press("Enter");
  const pending=page.waitForResponse(r=>new URL(r.url()).pathname==="/dispatch/shops/bulk_update"&&r.request().method()==="PUT");
  await page.getByRole("button",{name:/حفظ/,exact:false}).first().click();
  const answer=await pending;
  const payload=answer.request().postDataJSON();
  await info.attach("N2-bulk-update.json",{body:Buffer.from(JSON.stringify({status:answer.status(),payload,target,db:dbProbe("snapshot")},null,2)),contentType:"application/json"});
  expect(answer.status()).toBe(200);
  expect(payload.some((item:{id:string})=>String(item.id)===target),
    "A searched Zone B shop must not cause a success toast with only Zone A saved").toBe(true);
});

test("N5: Shop map link must be http(s) before browser receives an active anchor",async({page},info)=>{
  await login(page,info);
  const name=unique()+" Unsafe link",zoneName=unique()+" Map zone";
  const zone=await addZone(page,zoneName);
  const response=await api(page,"POST","/dispatch/shops",{
    name,owner:"Synthetic test",phone:"",mapLink:"javascript:alert(838)",
    zoneId:zone,initialDebt:0,maxDebtLimit:0,
  });
  await info.attach("N5-server-map-url.json",{body:Buffer.from(JSON.stringify(response)),contentType:"application/json"});
  if(response.status===422) return; // Server correctly rejects unsafe scheme.
  expect(response.status).toBe(201);
  await page.reload();
  await selectTab(page,"zones");
  await page.locator('input[placeholder="بحث..."]').fill(name);
  const row=page.locator(".dispatch-shop-table tbody tr").filter({hasText:name});
  const link=row.getByRole("link",{name:"عرض الموقع"});
  if(await link.count()===0) {
    // Removing unsafe clickable content entirely is a safe outcome.
    expect(await row.locator('a[href^="javascript:"]').count()).toBe(0);
    return;
  }
  await expect(link).toBeVisible();
  const href=await link.getAttribute("href");
  expect(href).toMatch(/^https?:\/\//i); // Do not click unsafe link: CSP may block navigation.
  await expect(link).toHaveAttribute("rel",/noreferrer/);
});

test("P1 finance: metadata-only UI save must preserve concurrent PG16 receivable",async({page},info)=>{
  await login(page,info);
  const zoneName=unique()+" Finance zone", original=unique()+" Finance shop";
  const zone=await addZone(page,zoneName);
  const shopId=await addShop(page,zone,original,100);
  await page.reload();
  await selectTab(page,"zones");
  await page.locator('input[placeholder="بحث..."]').fill(original);
  await page.getByRole("button",{name:"تعديل",exact:true}).click();
  const row=page.locator(".dispatch-shop-table tbody tr").filter({hasText:original});
  await row.locator("button").first().click();
  const modal=page.getByRole("dialog").last();
  await expect(modal).toBeVisible();
  await expect(modal.locator('input[type="number"]').last()).toHaveValue("100");
  dbProbe("balance80",shopId); // DISPOSABLE PG16 only, not a real collection journey.
  await modal.locator('input[type="text"]').first().fill(original+" Updated");
  const pending=page.waitForResponse(r=>new URL(r.url()).pathname==="/dispatch/shops/"+shopId&&r.request().method()==="PUT");
  await modal.getByRole("button",{name:"حفظ البيانات"}).click();
  const response=await pending;
  const after=dbProbe("snapshot");
  const balance=after.shops.find((s:any)=>s.id===shopId)?.currentBalance;
  await info.attach("P1-finance-wire-db.json",{body:Buffer.from(JSON.stringify({status:response.status(),body:response.request().postDataJSON(),balance},null,2)),contentType:"application/json"});
  expect(response.status()).toBe(200);
  expect(Number(balance),"An unrelated name change must never undo the concurrent balance change 100→80").toBe(80);
});

async function makeShortage(page:Page){
  const tag=unique(),zone=await addZone(page,tag+" shortage zone");
  const shopName=tag+" shortage shop", shop=await addShop(page,zone,shopName);
  const response=await api(page,"POST","/dispatch/shortages",[{
    zoneId:zone,shopId:shop,driverId:String(data.driverId),
    productId:String(data.variantId),quantity:2,
  }]);
  expect(response.status,JSON.stringify(response)).toBe(201);
  return {shopName,shop};
}
test("P1 shortage: group Edit uses registered transactional backend API",async({page},info)=>{
  await login(page,info);
  const group=await makeShortage(page);
  await page.reload();
  await page.getByRole("button",{name:/طلبات ونواقص/}).click();
  const modal=page.getByRole("dialog").first();
  const card=modal.locator(".rounded-2xl.border.overflow-hidden").filter({hasText:group.shopName}).first();
  await expect(card).toBeVisible();
  await card.getByRole("button",{name:"تعديل",exact:true}).click();
  const draft=modal.locator("table tbody tr").first();
  await expect(draft).toBeVisible();
  await draft.locator("button").nth(1).click(); // +1 base demand: 2 → 3
  const pending=page.waitForResponse(r=>new URL(r.url()).pathname==="/dispatch/shortages/group"&&r.request().method()==="PUT");
  await modal.getByRole("button",{name:/حفظ التعديلات \(/}).click();
  const response=await pending;
  await info.attach("P1-shortage-edit-http.json",{body:Buffer.from(JSON.stringify({
    status:response.status(),payload:response.request().postDataJSON(),server:await response.text(),db:dbProbe("snapshot"),
  },null,2)),contentType:"application/json"});
  expect(response.status(),"The visible Edit workflow requires a real registered atomic endpoint").toBe(200);
  const saved=await api(page,"GET","/dispatch/shortages");
  expect(saved.status).toBe(200);
  expect(saved.body.some((row:any)=>String(row.shopId)===group.shop && Number(row.quantity)===3))
    .toBe(true); // server committed the edited demand, not merely a 200
});

test("P1 shortage: Delete All must be atomic and actually delete pending rows",async({page},info)=>{
  await login(page,info);
  const group=await makeShortage(page);
  await page.reload();
  await page.getByRole("button",{name:/طلبات ونواقص/}).click();
  const modal=page.getByRole("dialog").first();
  const card=modal.locator(".rounded-2xl.border.overflow-hidden").filter({hasText:group.shopName}).first();
  await expect(card).toBeVisible();
  await card.getByRole("button",{name:/حذف الكل/}).click();
  const confirmation=page.getByRole("dialog").last();
  await expect(confirmation).toBeVisible();
  const pending=page.waitForResponse(r=>new URL(r.url()).pathname==="/dispatch/shortages/group"&&r.request().method()==="PUT");
  await confirmation.getByRole("button",{name:"تأكيد",exact:true}).click();
  const result=await pending;
  const raw=await api(page,"GET","/dispatch/shortages");
  await info.attach("P1-shortage-delete-all.json",{body:Buffer.from(JSON.stringify({
    status:result.status(),payload:result.request().postDataJSON(),pending:raw.body,
  },null,2)),contentType:"application/json"});
  expect(result.status(),"Delete All must be a real single atomic server command").toBe(200);
  expect(raw.body.some((s:any)=>String(s.shopId)===group.shop)).toBe(false);
});


test("Company B real owner cannot read or mutate Company A route/shop data",async({page},info)=>{
  await login(page,info,data.companyB.credentials);
  const own=await api(page,"GET","/dispatch/shops");
  expect(own.status).toBe(200);
  expect(own.body.map((row:any)=>row.name)).not.toContain(data.initialShopName);
  const otherRoute=await api(page,"GET",`/dispatch/active_routes?route_id=${data.routeId}`);
  expect(otherRoute.status).toBe(200);
  expect(otherRoute.body).toEqual([]);
  const denied=await api(page,"PUT",`/dispatch/route/${data.routeId}/status`,{status:"closed"});
  await info.attach("tenant-B-denied-wire.json",{body:Buffer.from(JSON.stringify({
    ownShops:own.body.length,otherRoute:otherRoute.body,routeWriteStatus:denied.status,
  },null,2)),contentType:"application/json"});
  expect([403,404]).toContain(denied.status);
  const after=dbProbe("snapshot");
  expect(after.routes.find((x:any)=>x.id===String(data.routeId)).status).not.toBe("closed");
});

test("real launch product catalog remains absent from init and actual Warehouse/Vehicle are distinct",async({page},info)=>{
  await login(page,info);
  const init=await api(page,"GET","/dispatch/init");
  expect(init.status).toBe(200);
  expect(init.body).not.toHaveProperty("products");
  const inventory=await api(page,"GET",`/dispatch/inventory/${data.vehicleId}`);
  expect(inventory.status).toBe(200);
  const discovery=await api(page,"GET",
    `/dispatch/products?purpose=LOAD&warehouse_id=${data.warehouseId}&vehicle_id=${data.vehicleId}&limit=80`);
  await info.attach("real-discovery-physical-wire.json",{body:Buffer.from(JSON.stringify({
    initBytes:init.bytes,productRows:discovery.body.items?.length,
    loadBytes:discovery.bytes,vehicleBytes:inventory.bytes,
    vehicle:inventory.body,firstProduct:discovery.body.items?.[0],
  },null,2)),contentType:"application/json"});
  expect(discovery.status).toBe(200);
  expect(Array.isArray(discovery.body.items)).toBe(true);
  expect(discovery.body.items.length).toBeLessThanOrEqual(80);
  expect(inventory.body.some((x:any)=>String(x.id??x.product_id??x.productId)===String(data.variantId))).toBe(true);
});

test("N3: interruption between restore-zone and restore-shop must not pretend atomic success",async({page},info)=>{
  await login(page,info);
  const name=unique()+" partial zone",shopName=unique()+" partial shop";
  const zone=await addZone(page,name);
  const shopId=await addShop(page,zone,shopName);
  const archived=await api(page,"DELETE",`/dispatch/zones/${zone}`);
  expect(archived.status).toBe(200);
  await page.reload();
  await selectTab(page,"zones");
  await page.getByTitle("فتح أرشيف المحلات المؤرشفة").click();
  const recycle=page.getByRole("dialog").first();
  const archivedRow=recycle.locator(".divide-y > div").filter({hasText:shopName});
  await expect(archivedRow).toBeVisible();
  await archivedRow.getByRole("button",{name:/استعادة/}).click();
  const prompt=page.getByRole("dialog").last();
  await expect(prompt).toContainText("المنطقة مؤرشفة");
  // Fault injection: only the second HTTP command is interrupted. The first
  // restore goes to genuine FastAPI/PG16 and MUST be inspected, never mocked.
  await page.route("**/dispatch/shops/bulk_update",r=>r.abort("failed"));
  const first=page.waitForResponse(r=>new URL(r.url()).pathname===`/dispatch/zones/${zone}/restore`&&r.request().method()==="PUT");
  await prompt.getByRole("button",{name:/استعادة المنطقة والمحل/}).click();
  const firstResult=await first;
  expect(firstResult.status()).toBe(200);
  await page.unroute("**/dispatch/shops/bulk_update");
  const init=await api(page,"GET","/dispatch/init");
  const shops=await api(page,"GET","/dispatch/shops");
  const zoneRestored=init.body.zones.some((z:any)=>String(z.id)===zone);
  const shopArchived=shops.body.some((s:any)=>String(s.id)===shopId && s.archived===true);
  await info.attach("N3-real-half-commit.json",{body:Buffer.from(JSON.stringify({
    firstStatus:firstResult.status(),zoneRestored,shopArchived,db:dbProbe("snapshot"),
  },null,2)),contentType:"application/json"});
  expect(zoneRestored && shopArchived,
    "Combined restore left a partially committed Zone/Shop pair after network loss").toBe(false);
});

test.afterEach(async({page},info)=>{
  // All failures stay red; preserve actual screenshots even when an assertion
  // throws before the explicit per-test witness can run.
  try{await page.screenshot({path:info.outputPath("final-"+info.project.name+".png"),fullPage:true,timeout:8_000})}
  catch(error){await info.attach("screenshot-unavailable",{body:Buffer.from(String(error)),contentType:"text/plain"})}
});
