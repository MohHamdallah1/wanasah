/* C03-FINAL: built Dashboard, actual scoped HTTP and real Chromium. */
const { chromium, request } = require("playwright");
const { readFileSync, mkdirSync } = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const ui="http://127.0.0.1:4183", api="http://127.0.0.1:4184";
const state=JSON.parse(readFileSync(process.env.WANASAH_C03_FINAL_BROWSER_STATE,"utf8"));
const output=process.env.C03_EVIDENCE_DIR;
assert(output&&process.env.C03_DISPOSABLE==="1");
mkdirSync(output,{recursive:true});
const samples=[["ar",1440],["en",1440],["ar",390],["en",390]];
const observed=[],errors=[];
async function launch(page){
  await page.goto(ui+"/dispatch");
  const target=page.getByTestId("dispatch-launch-workspace");
  if(!(await target.isVisible().catch(()=>false))){
    const tabs=page.getByRole("tab");
    const labels=(await tabs.allTextContents()).map(x=>x.trim());
    const idx=labels.findIndex(x=>/إطلاق|Launch|خط سير جديد/i.test(x));
    console.log("C03_TABS",JSON.stringify(labels.map(x=>x.slice(0,40))));
    assert(idx>=0,"Launch tab");
    await tabs.nth(idx).click();
  }
  await target.waitFor({state:"visible"});
  const trigger=page.getByTestId("m05-launch-vehicles").locator('button[aria-haspopup="listbox"]');
  await trigger.waitFor({state:"visible"});
  await page.waitForFunction(()=>{
    const el=document.querySelector('[data-testid="m05-launch-vehicles"] button[aria-haspopup="listbox"]');
    return el&&!el.disabled;
  },null,{timeout:45000});
  return trigger;
}
async function manager(browser,locale,width){
  const context=await browser.newContext({viewport:{width,height:width===390?844:900},
    permissions:["clipboard-read","clipboard-write"],deviceScaleFactor:1,reducedMotion:"reduce"});
  const page=await context.newPage();
  page.on("pageerror",x=>errors.push(String(x.message).slice(0,180)));
  page.on("response",x=>{
    const url=new URL(x.url());
    if(url.pathname.includes("custody")||url.pathname.includes("resource-availability"))
      observed.push({path:url.pathname,status:x.status(),method:x.request().method()});
  });
  await page.goto(ui+"/login");
  await page.evaluate(l=>localStorage.setItem("wanasah.language",l),locale);
  await page.reload();
  await page.locator("#company-code").fill(state.credentials.company_code);
  await page.locator("#username").fill(state.credentials.owner);
  await page.locator("#password").fill(state.credentials.password);
  await Promise.all([page.waitForURL(x=>x.pathname!=="/login"),
    page.locator('button[type="submit"]').click()]);
  await launch(page);
  return {context,page,locale,width};
}
async function fieldReceipt(offer){
  const http=await request.newContext();
  try{
    const login=await http.post(api+"/driver/login",{data:{
      company_code:state.credentials.company_code,
      username:state.credentials.field,password:state.credentials.password,
    }});
    assert.equal(login.status(),200,"real FIELD login");
    const auth="Bearer "+(await login.json()).token;
    const endpoint=api+"/driver/vehicles/"+state.vehicleId+"/custody/";
    // Wrong FIELD principal may NOT see a signed physical stock offer.
    const other=await http.post(api+"/driver/login",{data:{
      company_code:state.credentials.company_code,
      username:state.credentials.other_field,
      password:state.credentials.password,
    }});
    assert.equal(other.status(),200);
    const wrong=await http.post(endpoint+"offer-preview",{
      headers:{Authorization:"Bearer "+(await other.json()).token},
      data:{offer_token:offer},
    });
    assert.equal(wrong.status(),403,"wrong FIELD identity rejected by backend");
    const bad=offer.slice(0,-5)+(offer.at(-5)==="a"?"b":"a")+offer.slice(-4);
    const stale=await http.post(endpoint+"offer-preview",{
      headers:{Authorization:auth},data:{offer_token:bad},
    });
    assert.equal(stale.status(),409,"tampered signed token rejected");
    const preview=await http.post(endpoint+"offer-preview",{headers:{Authorization:auth},
      data:{offer_token:offer}});
    assert.equal(preview.status(),200,"real signed FIELD preview");
    const rows=await preview.json();
    assert.equal(rows.stock_snapshot,state.stockSnapshot);
    assert.equal(rows.stock_lines.length,state.stockLines.length);
    const confirm=await http.post(endpoint+"confirm",{headers:{Authorization:auth},data:{
      offer_token:offer,confirmed_stock_snapshot:rows.stock_snapshot,
      receiver_confirms_physical_count:true,
    }});
    assert.equal(confirm.status(),200,"signed physical count");
    const evidence=await confirm.json();
    assert.equal(evidence.confirmed,true);
    console.log("C03_FIELD_REAL_BEARER_RECEIPT=PASS");
    return evidence.receiver_proof;
  }finally{await http.dispose()}
}
async function checkedLayout(page,locale,width,phase){
  const size=await page.evaluate(()=>({
    width:window.innerWidth,scrollWidth:document.documentElement.scrollWidth,
  }));
  assert(size.scrollWidth<=size.width+1,"horizontal overflow "+locale+" "+width+" "+phase+" "+JSON.stringify(size));
  const tokenVisible=await page.locator('[data-testid="c03-custody-panel"]')
    .locator("text=/PRIVATE_SIGNED_TOKEN_NEVER_PRESENT/").count();
  assert.equal(tokenVisible,0);
  await page.screenshot({path:path.join(output,locale+"-"+width+"-"+phase+".png"),
    fullPage:false});
}
async function main(){
  const browser=await chromium.launch({channel:"msedge",headless:true});
  const sessions=[];
  try{
    // Four distinct signed owner browser sessions BEFORE the actual transfer.
    for(const [locale,width] of samples){
      const sample=await manager(browser,locale,width);sessions.push(sample);
      const trigger=sample.page.getByTestId("m05-launch-vehicles")
        .locator('button[aria-haspopup="listbox"]');
      await trigger.click();
      const car=sample.page.locator('[data-testid="m05-launch-vehicles"]')
        .locator('[role="option"][data-resource-id="'+state.vehicleId+'"]');
      await car.waitFor({state:"visible"});
      assert(await car.isDisabled(),"C01 blocked car must stay disabled");
      await sample.page.getByTestId("c03-review-blocked-car-"+state.vehicleId)
        .waitFor({state:"visible"});
      await checkedLayout(sample.page,locale,width,"before");
      console.log("C03_BEFORE_"+locale+"_"+width+"_DISABLED_WITH_RECOVERY=PASS");
    }
    const sample=sessions.find(x=>x.locale==="en"&&x.width===1440);
    const page=sample.page;
    await page.getByTestId("c03-review-blocked-car-"+state.vehicleId).click();
    const panel=page.getByTestId("c03-custody-panel");
    await panel.waitFor({state:"visible"});
    await panel.getByText(state.stockLines[0].product_name,{exact:true})
      .waitFor({state:"visible"});
    assert((await panel.textContent()).includes(state.stockLines[0].batch_number));
    assert(!await page.locator('[data-testid="m05-launch-vehicles"]')
      .locator('[role="option"][data-resource-id="'+state.vehicleId+'"]')
      .isVisible(),"No vehicle became selected while opening C03");
    await panel.locator("select").selectOption(String(state.fieldDriverId));
    await panel.getByRole("button",{name:"Prepare handoff"}).click();
    const share=panel.getByRole("button",{name:"Copy private handoff"});
    await share.waitFor({state:"visible"});
    await share.click();
    const signedOffer=await page.evaluate(()=>navigator.clipboard.readText());
    assert(signedOffer.length>100,"signed short-lived handoff available to intended field rep");
    assert(!(await panel.textContent()).includes(signedOffer),"never disclose offer in DOM");
    const proof=await fieldReceipt(signedOffer);
    await panel.locator("textarea").fill(proof);
    // Preserve the exact workbench DOM node while a C02 receipt is posted.
    await page.evaluate(()=>{
      window.__c03_pre_accept_workspace=document.querySelector(
        '[data-testid="dispatch-launch-workspace"]');
    });
    const signedRefresh=page.waitForResponse(response=>
      new URL(response.url()).pathname==="/dispatch/launch/resource-availability" &&
      response.status()===200,{timeout:20000});
    const accepting=page.waitForResponse(response=>
      new URL(response.url()).pathname==="/vehicles/"+state.vehicleId+"/custody/accept" &&
      response.request().method()==="POST",{timeout:20000});
    await panel.getByRole("button",{name:"Approve verified custody"}).click();
    const answer=await accepting;
    assert.equal(answer.status(),201);
    const result=await answer.json();
    assert.equal(result.state,"ACCEPTED");
    assert.equal(result.stock_movements,0);
    await panel.waitFor({state:"hidden"});
    const refreshed=await signedRefresh;
    const freshRow=(await refreshed.json()).vehicles.find(x=>x.id===String(state.vehicleId));
    assert(freshRow&&freshRow.code==="AVAILABLE"&&freshRow.available===true,
      "Signed resource availability after C02 acceptance");
    const sameWorkbench=await page.evaluate(()=>
      window.__c03_pre_accept_workspace===
      document.querySelector('[data-testid="dispatch-launch-workspace"]'));
    assert(sameWorkbench,"Real Dispatch workbench must stay mounted during custody acceptance");
    const liveTrigger=page.getByTestId("m05-launch-vehicles")
      .locator('button[aria-haspopup="listbox"]');
    await liveTrigger.waitFor({state:"visible"});
    await liveTrigger.click();
    const liveCar=page.locator('[data-testid="m05-launch-vehicles"]')
      .locator('[role="option"][data-resource-id="'+state.vehicleId+'"]');
    await liveCar.waitFor({state:"visible"});
    assert(await liveCar.isEnabled(),
      "Same-page verified car available without reload or optimistic state");
    console.log("C03_NO_REMOUNT_SIGNED_REFETCH_AFTER_ACCEPT=PASS");
    console.log("C03_MANAGER_SIGNED_C02_ACCEPTANCE=PASS");

    // All four owner sessions must read the same new authoritative availability.
    for(const entry of sessions){
      const {page,locale,width}=entry;
      await page.reload();
      await launch(page);
      const trigger=page.getByTestId("m05-launch-vehicles")
        .locator('button[aria-haspopup="listbox"]');
      await trigger.click();
      const car=page.locator('[data-testid="m05-launch-vehicles"]')
        .locator('[role="option"][data-resource-id="'+state.vehicleId+'"]');
      await car.waitFor({state:"visible"});
      assert(await car.isEnabled(),"Backend must certify availability, not client optimism");
      assert.equal(await page.getByTestId("c03-review-blocked-car-"+state.vehicleId).count(),0);
      await checkedLayout(page,locale,width,"after");
      console.log("C03_AFTER_"+locale+"_"+width+"_REAL_AVAILABLE=PASS");
    }
    assert.equal(errors.length,0,"browser JS errors "+JSON.stringify(errors));
    console.log("C03_REAL_CHROMIUM_EIGHT_BEFORE_AFTER=PASS");
    console.log("C03_SIGNED_HTTP_COUNTS",JSON.stringify({
      availability:observed.filter(x=>x.path==="/dispatch/launch/resource-availability"&&x.status===200).length,
      stockReads:observed.filter(x=>x.path.endsWith("/custody/stock-review")).length,
      accepted:observed.filter(x=>x.path.endsWith("/custody/accept")&&x.status===201).length,
    }));
  }finally{
    for(const entry of sessions)await entry.context.close();
    await browser.close();
  }
}
main().catch(error=>{
  // Never print browser actions/serialized payloads: an unsuccessful FIELD
  // receipt may contain a sensitive signed token in a Playwright call log.
  console.error("C03_REAL_BROWSER_FAILURE",
    String(error?.message||"unknown").split("\n")[0].slice(0,150));
  process.exitCode=1;
});
