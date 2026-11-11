/**
 * Independent #919 security FRAME witness: genuinely signed Backoffice sessions,
 * real PG16 grants/revokes, no fake HTTP responses and no auth bypass.
 * This supplements canonical D14's 4/4 browser permission tests.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "playwright/test";

const fixture=JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!,"utf8"));
const root="node_modules/.cache/dispatch-d15-independent-security";
type Actor="reader"|"limited"|"foreign";
type Frame={ms:number;path:string;selected:string;zoneRows:number;
  a1:boolean;a2:boolean;unassigned:boolean;debtA1:boolean;debtA2:boolean;
  tableVisible:boolean;tabs:number;pending:boolean};
function toggle(kind:"reader"|"limited"|"reset",flag?:"on"|"off"){
  const args=["-m","tests.test_dispatch_d14_browser_fixture",kind];
  if(flag)args.push(flag);
  execFileSync("python",args,{cwd:resolve(process.cwd(),"../wa_backend"),timeout:25000});
}
async function signIn(page:Page,actor:Actor,lang:"ar"|"en"){
  await page.goto("http://127.0.0.1:4173/");
  await page.evaluate(l=>{localStorage.clear();localStorage.setItem("wanasah.language",l)},lang);
  await page.goto("http://127.0.0.1:4173/login");
  await page.reload();
  const cred=fixture.credentials[actor];
  await page.locator("#company-code").fill(cred.code);
  await page.locator("#username").fill(cred.username);
  await page.locator("#password").fill(cred.password);
  await Promise.all([
    page.waitForURL(u=>u.pathname!=="/login",{timeout:30000}),
    page.locator('button[type="submit"]').click()
  ]);
}
async function tab(page:Page,id:"routes"|"zones"){
  const label=id==="routes"?/الخطوط النشطة|Active routes/:/هيكلة المناطق|Zones & shops/;
  const b=page.getByRole("tab",{name:label});
  await expect(b).toBeEnabled({timeout:40000});
  await b.click();
  await expect(b).toHaveAttribute("aria-selected","true");
}
async function chooseZone(page:Page,zone:string){
  const pane=page.locator(".dispatch-zones-workbench > div").first();
  await expect(pane.getByText(zone,{exact:true}).first()).toBeVisible({timeout:25000});
  await pane.getByText(zone,{exact:true}).first().click();
  await expect(page.locator(".dispatch-shop-table")).toBeVisible({timeout:25000});
}
function probeStart(names:{a1:string;a2:string;unassigned:string}){
  const w=window as any;
  w.__d15SecStop?.();
  let stop=false,start=performance.now();
  const frames:Frame[]=[];
  const visible=(x:Element|null)=>{
    if(!x||x.closest('[aria-hidden="true"]'))return false;
    const s=getComputedStyle(x),r=x.getBoundingClientRect();
    return s.display!=="none"&&s.visibility!=="hidden"&&r.height>1&&r.width>1;
  };
  const tick=()=>{
    if(stop)return;
    const rows=[...document.querySelectorAll(".dispatch-shop-table tbody tr")]
      .filter(visible).map(x=>x.textContent||"");
    const text=rows.join(" ");
    const normalized=text.replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-0x660))
      .replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-0x6f0))
      .replace(/٫/g,".");
    const selected=[...document.querySelectorAll('[data-testid="dispatch-shared-topbar"] [role=tab]')]
      .find(x=>visible(x)&&x.getAttribute("aria-selected")==="true")?.textContent||"";
    frames.push({ms:Math.round(performance.now()-start),path:location.pathname,
      selected:selected.trim(),zoneRows:rows.length,
      a1:text.includes(names.a1),a2:text.includes(names.a2),
      unassigned:text.includes(names.unassigned),
      debtA1:normalized.includes("181.125"),debtA2:normalized.includes("901.125"),
      tableVisible:visible(document.querySelector(".dispatch-shop-table")),
      tabs:[...document.querySelectorAll('[data-testid="dispatch-shared-topbar"] [role=tab]')].filter(visible).length,
      pending:!!document.querySelector('[data-dispatch-workspace][aria-busy="true"]')});
    if(performance.now()-start<2800)requestAnimationFrame(tick);
  };
  w.__d15SecFrames=frames;w.__d15SecStop=()=>{stop=true};
  requestAnimationFrame(tick);
}
async function sample(page:Page,label:string,act:()=>Promise<void>){
  await page.evaluate(probeStart,{a1:fixture.shops.assigned.name,
    a2:fixture.shops.a2.name,unassigned:fixture.shops.unassigned.name});
  await act();
  await page.waitForTimeout(2850);
  const data=await page.evaluate(()=>(window as any).__d15SecFrames as Frame[]);
  mkdirSync(root,{recursive:true});
  writeFileSync(root+"/"+label+".json",JSON.stringify(data,null,2));
  await page.screenshot({path:root+"/"+label+".png",fullPage:true});
  return data;
}
for(const [lang,width] of [["ar",390],["en",1440]] as const){
  test("D15 #919 restricted and same-token revoke every-rAF "+lang+" "+width,
    async({page})=>{
      test.setTimeout(240000);
      await page.setViewportSize({width,height:900});
      toggle("reset");
      await signIn(page,"limited",lang);
      await page.goto("http://127.0.0.1:4173/dispatch");
      const restricted=await sample(page,lang+width+"-limited",async()=>{
        await tab(page,"zones");
        await chooseZone(page,fixture.zones.a1);
      });
      const exposed=restricted.filter(f=>f.path==="/dispatch"&&
        (f.a2||f.unassigned||f.debtA1||f.debtA2));
      expect(exposed, "A1-restricted account must have ZERO foreign/unassigned/debt frames").toEqual([]);
      expect(restricted.some(f=>f.a1),"actual authorized A1 Shop must appear").toBe(true);

      await signIn(page,"reader",lang);
      await page.goto("http://127.0.0.1:4173/dispatch");
      await tab(page,"zones");await chooseZone(page,fixture.zones.a2);
      const noFinance=await sample(page,lang+width+"-reader-redacted",async()=>{
        await tab(page,"routes");await tab(page,"zones");await chooseZone(page,fixture.zones.a2);
      });
      expect(noFinance.filter(f=>f.debtA1||f.debtA2),"reader money before grant").toEqual([]);
      const originalToken=await page.evaluate(()=>localStorage.getItem("admin_token"));
      toggle("reader","on");
      await tab(page,"routes");await tab(page,"zones");await chooseZone(page,fixture.zones.a2);
      await expect.poll(async()=>page.locator(".dispatch-shop-table tbody tr")
        .filter({hasText:fixture.shops.a2.name}).first().innerText(),
        {timeout:20000}).toMatch(/901[٫.]125|٩٠١[٫.]١٢٥/);
      expect(await page.evaluate(()=>localStorage.getItem("admin_token"))).toBe(originalToken);

      toggle("reader","off");
      const revoked=await sample(page,lang+width+"-revoke-same-token",async()=>{
        await tab(page,"routes");await tab(page,"zones");await chooseZone(page,fixture.zones.a2);
      });
      // Previously displayed finance may remain until first actual route-leave commit.
      // From first no-Zones row after leaving the old tab, even one frame is forbidden.
      const firstCleared=revoked.findIndex((x,i)=>i>0&&x.zoneRows===0);
      expect(firstCleared,"must actually unmount old financial rows on revalidation").toBeGreaterThanOrEqual(0);
      const leaked=revoked.slice(firstCleared).filter(f=>f.debtA1||f.debtA2);
      expect(leaked,"same-token revoked finance must never reappear after prior view leaves").toEqual([]);
      expect(await page.evaluate(()=>localStorage.getItem("admin_token"))).toBe(originalToken);

      await signIn(page,"foreign",lang);
      await page.goto("http://127.0.0.1:4173/dispatch");
      const foreign=await sample(page,lang+width+"-foreign-company",async()=>{
        await tab(page,"zones");
      });
      expect(foreign.filter(f=>f.path==="/dispatch"&&(f.a1||f.a2||f.unassigned||f.debtA1||f.debtA2)),
        "Company B cannot flash Company A Shop rows or debt").toEqual([]);
      toggle("reset");
      console.log("D15_919_FRAME_SECURITY="+JSON.stringify({
        lang,width,limitedFrames:restricted.length,readerFrames:noFinance.length,
        revokedFrames:revoked.length,foreignFrames:foreign.length,
        oldValueBeforeRevokeClear:revoked.slice(0,firstCleared).filter(x=>x.debtA2).length,
        foreignLeaked:0,revokedReappeared:0,signedRealPG16:true}));
  });
}
