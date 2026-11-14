import { mkdirSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

const fixture = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const origin = "http://127.0.0.1:4173";
const enforce = process.env.D15_DATA_REENTRY_ENFORCE === "1";
const dest = "node_modules/.cache/dispatch-d15-data-reentry-" + (enforce ? "after" : "before");
type Tab = "routes" | "launch" | "zones";

async function login(page: Page, role: "owner" | "limited" | "foreign" = "owner", lang = "ar") {
  await page.goto(origin + "/");
  await page.evaluate(value => { localStorage.clear(); localStorage.setItem("wanasah.language", value); }, lang);
  await page.goto(origin + "/login");
  await page.reload();
  const actor = fixture.credentials[role];
  await page.locator("#company-code").fill(actor.code);
  await page.locator("#username").fill(actor.username);
  await page.locator("#password").fill(actor.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 35000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function nav(page: Page, id: "dispatch" | "products" | "inventory", mobile: boolean) {
  // Use the real navigation's localized accessible name, not the index in a
  // permission-filtered list. This is still a genuine SPA sidebar transition.
  const labels = {
    dispatch: /^(التوزيع والمناطق|Dispatch & Regions)$/,
    products: /^(المنتجات|Products)$/,
    inventory: /^(المخزون والمستودع|Inventory & Warehouse)$/,
  };
  const target = page.locator(".operations-nav").getByRole("button", { name: labels[id] });
  // CSS transforms can park the closed mobile sidebar outside the viewport
  // while Playwright isVisible() still reports its buttons as visible.
  if (mobile) await page.locator(".dashboard-mobile-menu").click();
  await expect(target, "Signed navigation must expose the authorized destination").toBeVisible({ timeout: 15000 });
  await target.click();
  await expect(page).toHaveURL(new RegExp("/" + id + "$"));
  // Fail at the real render fault instead of timing out on an absent sidebar.
  await expect(page.getByRole("heading", { name: /حدث خطأ غير متوقع|An unexpected error/i }),
    "The SPA must not fall into the React error boundary after navigation").toHaveCount(0);
}

async function select(page: Page, tab: Tab) {
  const names: Record<Tab, string> = {
    routes: "الخطوط النشطة", launch: "إطلاق خط جديد", zones: "هيكلة المناطق",
  };
  const button = page.getByRole("tab", { name: names[tab] });
  await expect(button).toBeEnabled({ timeout: 25000 });
  await button.click();
  await expect(button).toHaveAttribute("aria-selected", "true");
  const workspace = page.getByTestId("dispatch-" + tab + "-workspace");
  await expect(workspace).toBeVisible();
  await expect(workspace).not.toHaveAttribute("inert", "", { timeout: 25000 });
  return workspace;
}

async function chooseLaunch(page: Page) {
  const slots = page.locator(".dispatch-launch-config > div.relative.mt-2");
  await expect(slots, "Four stable signed resource selectors").toHaveCount(4);
  const selected: string[] = [];
  for (const i of [3, 0, 1, 2]) {
    const slot = slots.nth(i);
    const button = slot.locator(":scope > div.relative > button");
    await expect(button).toBeEnabled({ timeout: 25000 });
    await button.click();
    // BEFORE on frozen MAIN still uses unversioned CustomSelect motion items.
    // AFTER on M05 uses signed listbox options with native disabled reasons.
    if (await button.getAttribute("aria-haspopup") !== "listbox") {
      const legacy = slot.locator("div.absolute.top-full button");
      await expect(legacy.first()).toBeVisible({ timeout: 25000 });
      await legacy.first().click();
      const label = (await button.textContent() ?? "").trim();
      expect(label.length).toBeGreaterThan(0);
      selected.push(label);
      continue;
    }
    const options = slot.locator('div[role="listbox"] button[role="option"]');
    await expect.poll(async () => options.count(), { timeout: 25000 }).toBeGreaterThan(0);
    // Use an explicit enabled native option: some signed FIELD identities are
    // correctly unverified, reserved and disabled in this genuine PG16 seed.
    const permitted = slot.locator('div[role="listbox"] button[role="option"]:not(:disabled)');
    const disabled = slot.locator('div[role="listbox"] button[role="option"]:disabled');
    if (await permitted.count()) {
      const option = permitted.first();
      expect(await option.getAttribute("data-resource-id")).toMatch(/^[1-9]\d*$/);
      await option.click();
      const label = (await button.textContent() ?? "").trim();
      expect(label.length).toBeGreaterThan(0);
      selected.push(label);
    } else {
      await expect(disabled.first()).toBeVisible();
      await expect(disabled.first()).toBeDisabled();
      expect((await disabled.first().getAttribute("title"))?.trim().length ?? 0,
        "Unavailable resource needs a signed, precise reason").toBeGreaterThan(0);
      await button.click();
      // A blocked resource has no selection to preserve; do not fake one.
      selected.push("");
    }
  }
  return selected;
}

async function sample(page: Page, tab: Tab, label: string, expected: {
  zone: string | null; routeRows: number; choiceNames: string[];
}) {
  await page.evaluate(({ tab, label, expected }) => {
    const w = window as any;
    const started = performance.now();
    w.__d15DataFrames = [];
    const frame = () => {
      if (location.pathname === "/dispatch") {
        const target = document.querySelector('[data-testid="dispatch-' + tab + '-workspace"]') as HTMLElement | null;
        const wrapper = document.querySelector(".dispatch-content") as HTMLElement | null;
        const launch = document.querySelector(".dispatch-launch-config") as HTMLElement | null;
        const table = document.querySelector(".dispatch-shop-table") as HTMLElement | null;
        const tabNode = document.querySelector('.dispatch-tab-list [role=tab][aria-selected=true]') as HTMLElement | null;
        // Count the four SELECT BUTTONS only; the prior broad selector also
        // captured a transient dropdown option during its exit transition.
        const names = [...document.querySelectorAll(
          ".dispatch-launch-config > div.relative.mt-2 > div.relative > button")];
        const text = target?.textContent || "";
        w.__d15DataFrames.push({
          tab,label,ms:Math.round(performance.now()-started),
          present:!!target, selected:!!tabNode,
          // Cached signed same-principal rows must remain visible even while
          // ordinary access/shops reads are truly in flight. Do not just
          // prove that a geometric placeholder remains mounted.
          missingChoices: expected.choiceNames.map((name, i) =>
            Boolean(name) && !((names[[3,0,1,2][i]]?.textContent ?? "").trim().includes(name))),
          warmDataMissing: (
            tab === "zones" && !!expected.zone && !text.includes(expected.zone) ||
            tab === "routes" && expected.routeRows > 0 &&
              (target?.querySelectorAll(".dispatch-route-row").length ?? 0) < expected.routeRows ||
            tab === "launch" && expected.choiceNames.some((name, i) => {
              if (!name) return false;
              return !((names[[3,0,1,2][i]]?.textContent ?? "").trim().includes(name));
            })
          ),
          falseZero:tab === "zones" && /المناطق \(0\)/.test(text),
          falseShops:tab === "zones" && text.includes("لا توجد محلات في هذه المنطقة"),
          falseRoutes:tab === "routes" && text.includes("لا توجد خطوط سير تشغيلية حالياً"),
          // A product context can only disappear if this test genuinely had
          // BOTH an authorized vehicle and source warehouse selected before
          // leaving. When the signed fixture has no eligible vehicle, the
          // product search correctly asks for one; that is NOT lost data.
          // chosen order is warehouse, zone, representative, vehicle.
          falseProductContext:tab === "launch" &&
            Boolean(expected.choiceNames[0] && expected.choiceNames[3]) &&
            text.includes("اختر السيارة ومستودع المصدر للبحث"),
          workspaceX:target ? Math.max(0,target.scrollWidth-target.clientWidth) : -1,
          frameX:wrapper ? Math.max(0,wrapper.scrollWidth-wrapper.clientWidth) : -1,
          configX:launch ? Math.max(0,launch.scrollWidth-launch.clientWidth) : -1,
          tableX:table ? Math.max(0,table.scrollWidth-table.clientWidth) : -1,
          controlNames:names.length,
          routes:target?.querySelectorAll(".dispatch-route-row").length ?? 0,
        });
      }
      if (performance.now()-started < 1900) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }, { tab, label, expected });
}

for (const width of [1440, 390] as const) {
  test("D15 DATA P1 signed browser 3 reentries, delayed Shops and inner x " + width, async ({ page }) => {
    test.setTimeout(180000);
    mkdirSync(dest, { recursive:true });
    await page.setViewportSize({ width,height:900 });
    await login(page);
    await page.goto(origin + "/dispatch");
    await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible();
    let shopReads = 0, routeReads = 0, initReads = 0;
    let delayShops = false;
    let delayAccess = false;
    // Recreate the exact owner complaint using the genuine signed capability
    // response, not a fake authorization or an application timeout.
    await page.route("**/inventory/access/me*", async route => {
      if (delayAccess) await page.waitForTimeout(500);
      await route.continue();
    });
    await page.route("**/dispatch/shops", async route => {
      shopReads++;
      if (delayShops) await page.waitForTimeout(2400);
      await route.continue(); // NEVER stub a signed response
    });
    page.on("request", req => {
      const p = new URL(req.url()).pathname;
      if (p === "/dispatch/active_routes") routeReads++;
      if (p === "/dispatch/init") initReads++;
    });

    for (const tab of ["routes","launch","zones"] as const) {
      await select(page,tab);
      let chosen: string[] = [];
      if (tab === "launch") chosen = await chooseLaunch(page);
      if (tab === "zones") {
        await expect(page.locator(".dispatch-zones-workbench").getByText(fixture.zones.a1,{exact:true}).first()).toBeVisible();
      }
      const original = await page.getByTestId("dispatch-" + tab + "-workspace").elementHandle();
      const expected = {
        zone: tab === "zones" ? fixture.zones.a1 as string : null,
        routeRows: tab === "routes" ? await page.locator(".dispatch-route-row").count() : 0,
        choiceNames: chosen,
      };
      await nav(page, "products", width === 390);
      const before = { shops: shopReads, routes: routeReads, init: initReads };
      delayShops = tab === "zones";
      delayAccess = true;
      await sample(page,tab,String(width)+":"+tab,expected);
      await nav(page, "dispatch", width === 390);
      if (tab === "zones") {
        // Actual /init is independent; Zone list need not wait 2.4s Shops GET.
        await expect(page.locator(".dispatch-zones-workbench").getByText(fixture.zones.a1,{exact:true}).first()).toBeVisible({ timeout: 25000 });
        await page.screenshot({path:dest+"/"+width+"-zones-init-before-shops.png"});
      }
      await page.waitForTimeout(1950);
      const frames = await page.evaluate(() => (window as any).__d15DataFrames as Array<any>);
      const report = {
        width,tab, frames:frames.length,
        noWorkspace:frames.filter(f=>!f.present).length,
        falseZero:frames.filter(f=>f.falseZero).length,
        falseShops:frames.filter(f=>f.falseShops).length,
        falseRoutes:frames.filter(f=>f.falseRoutes).length,
        falseProductContext:frames.filter(f=>f.falseProductContext).length,
        warmDataMissing:frames.filter(f=>f.warmDataMissing).length,
        maxWorkspaceX:Math.max(0,...frames.map(f=>f.workspaceX)),
        maxFrameX:Math.max(0,...frames.map(f=>f.frameX)),
        maxConfigX:Math.max(0,...frames.map(f=>f.configX)),
        requests:{shops:shopReads-before.shops,routes:routeReads-before.routes,init:initReads-before.init},
      };
      console.log("D15_DATA_REENTRY="+JSON.stringify(report));
      if (report.warmDataMissing > 0) {
        // Only report Boolean mismatches and counts, never private labels.
        console.log("D15_WARM_MISSING_FRAMES="+JSON.stringify(frames
          .filter(f=>f.warmDataMissing).slice(0,3)
          .map(f=>({tab:f.tab,ms:f.ms,present:f.present,routes:f.routes,
            controlNames:f.controlNames,missingChoices:f.missingChoices}))));
      }
      if (enforce) {
        expect(report.warmDataMissing,"Previously signed same-actor data must not disappear during ordinary SPA return").toBe(0);
        expect(report.falseZero).toBe(0);
        expect(report.falseShops).toBe(0);
        expect(report.falseRoutes).toBe(0);
        expect(report.falseProductContext).toBe(0);
        expect(report.maxWorkspaceX,"No horizontal Launch page scrollbar").toBeLessThanOrEqual(2);
        expect(report.maxFrameX,"No extra page-wide Dispatch content scrollbar").toBeLessThanOrEqual(2);
        expect(report.maxConfigX).toBeLessThanOrEqual(2);
        if (tab === "routes") expect(report.requests.shops,"Routes must not request the global Shops list").toBe(0);
        if (tab === "launch") expect(report.requests.shops,"Launch must read real Shops for its POST precondition").toBeGreaterThan(0);
        if (tab === "routes" && report.requests.routes === 0) {
          // D15 keeps same-actor previously signed route rows across SPA returns.
          // Requiring a redundant GET would penalize the approved warm cache;
          // require the identical actual route rows when no GET occurred.
          expect(expected.routeRows, "A warm return must have real signed route rows").toBeGreaterThan(0);
          await expect(page.locator(".dispatch-route-row")).toHaveCount(expected.routeRows);
        }
      }
      const now = page.getByTestId("dispatch-" + tab + "-workspace");
      await expect(now).toBeVisible();
      await expect(now).not.toHaveAttribute("inert", "", { timeout: 25000 });
      expect(await page.evaluate(node=>node===document.querySelector('[data-testid="dispatch-'+
        (window as any).__d15DataFrames[0]?.tab+'-workspace"]'),original)).toBe(true);
      if (tab === "launch") {
        const current = page.locator(".dispatch-launch-config > div.relative.mt-2 > div.relative > button");
        for (let i=0;i<4;i++) if (chosen[i]) {
          const index = [3,0,1,2][i];
          await expect(current.nth(index)).toContainText(chosen[i]);
        }
      }
      delayShops = false;
      delayAccess = false;
      await page.screenshot({path:dest+"/"+width+"-"+tab+"-returned.png"});
    }
  });
}

test("D15 DATA P1 real scoped A1 and foreign tenant B receive no cached A Shop", async ({ page }) => {
  test.setTimeout(90000);
  await page.setViewportSize({width:1440,height:900});
  await login(page,"limited");
  await page.goto(origin+"/dispatch");
  await select(page,"zones");
  await expect(page.getByText(fixture.zones.a1,{exact:true}).first()).toBeVisible();
  const zone = page.getByTestId("dispatch-zones-workspace");
  await expect(zone).not.toContainText(fixture.shops.a2.name);
  await expect(zone).not.toContainText(fixture.shops.unassigned.name);
  await expect(zone).not.toContainText(fixture.shops.assigned.balance);
  console.log("D15_DATA_SCOPE="+JSON.stringify({actor:"limited",a1Visible:true,a2Leaked:false,financeLeaked:false}));
  // Switch actor through a fresh actual sign-in, never impersonate a token.
  await login(page,"foreign");
  await page.goto(origin+"/dispatch");
  const foreignText = await page.locator(".dispatch-board").textContent();
  expect(foreignText||"").not.toContain(fixture.shops.assigned.name);
  expect(foreignText||"").not.toContain(fixture.zones.a1);
  console.log("D15_DATA_SCOPE="+JSON.stringify({actor:"foreign",oldCompanyVisible:false}));
});

test("D15 DATA P1 first Products/Inventory JS stays free of DispatchBoard", async ({ page,browser }) => {
  await login(page);
  const state = await page.evaluate(() => Object.fromEntries(
    [...Array(localStorage.length)].map((_,i)=>{const k=localStorage.key(i)!;return[k,localStorage.getItem(k)];})));
  for (const target of ["products","inventory"]) {
    const context=await browser.newContext();
    await context.addInitScript(state=>{
      for(const [key,value] of Object.entries(state))if(value!=null)localStorage.setItem(key,value);
    },state);
    const fresh=await context.newPage();
    let boardJs=0;
    fresh.on("request",req=>{if(/\/assets\/DispatchBoard-[^/]+\.js/.test(req.url()))boardJs++;});
    await fresh.goto(origin+"/"+target);
    await expect(fresh).toHaveURL(new RegExp("/"+target+"$"));
    await fresh.waitForTimeout(500);
    console.log("D15_DATA_JS="+JSON.stringify({target,dispatchBoardRequests:boardJs}));
    expect(boardJs).toBe(0);
    await context.close();
  }
});
