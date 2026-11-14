import { mkdirSync, readFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

// Synthetic PG16 actors and credentials from a fresh, restricted fixture; the
// real FastAPI, Bearer and all HTTP responses are NEVER stubbed.
const fixture = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D14_BROWSER_STATE!, "utf8"));
const origin = "http://127.0.0.1:4173";
const enforce = process.env.D15_P1_ENFORCE === "1";
const imageDir = "node_modules/.cache/dispatch-d15-launch-reentry-" + (enforce ? "after" : "before");

async function signIn(page: Page, lang: "ar" | "en") {
  await page.goto(origin + "/");
  await page.evaluate(l => { localStorage.clear(); localStorage.setItem("wanasah.language", l); }, lang);
  await page.goto(origin + "/login");
  await page.reload();
  await page.locator("#company-code").fill(fixture.credentials.owner.code);
  await page.locator("#username").fill(fixture.credentials.owner.username);
  await page.locator("#password").fill(fixture.credentials.owner.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

// The source warehouse resets dependent selections; select it FIRST.
// Never guess a name/id. Choose only an item genuinely served by PG16.
async function selectAuthorizedChoices(page: Page) {
  const slots = page.locator(".dispatch-launch-config > div.relative.mt-2");
  await expect(slots, "All four signed launch choices are required").toHaveCount(4);
  let selected = 0;
  for (const index of [3, 0, 1, 2]) {
    const slot = slots.nth(index);
    const button = slot.locator(":scope > div.relative > button");
    await expect(button, "Signed resource control must be interactive").toBeEnabled({ timeout: 25000 });
    await button.click();
    // The workflow compares frozen MAIN (legacy CustomSelect) to signed M05.
    // Only M05 supplies native-disabled listbox roles; retain the original
    // baseline option path without changing any production selector.
    if (await button.getAttribute("aria-haspopup") !== "listbox") {
      const legacy = slot.locator("div.absolute.top-full button");
      await expect(legacy.first()).toBeVisible({ timeout: 25000 });
      await legacy.first().click();
      selected++;
      continue;
    }
    const enabled = slot.locator('div[role="listbox"] button[role="option"]:not(:disabled)');
    const blocked = slot.locator('div[role="listbox"] button[role="option"]:disabled');
    const options = slot.locator('div[role="listbox"] button[role="option"]');
    await expect.poll(async () => options.count(), { timeout: 25000 }).toBeGreaterThan(0);
    if (await enabled.count()) {
      const candidate = enabled.first();
      const signedId = await candidate.getAttribute("data-resource-id");
      expect(signedId, "Only canonical signed option IDs are selectable").toMatch(/^[1-9]\d*$/);
      await candidate.click();
      await expect(button, "The selected signed resource should persist").not.toHaveText(/^(اختر|Select) /);
      selected++;
    } else {
      // Some real PG16 fixtures intentionally have no FIELD-verified rep.
      // Do not click a disabled item or invent a driver to make D15 pass.
      await expect(blocked.first()).toBeVisible();
      await expect(blocked.first()).toBeDisabled();
      expect((await blocked.first().getAttribute("title"))?.trim().length ?? 0,
        "The blocked signed resource must explain its exact reason").toBeGreaterThan(0);
      await button.click();
    }
  }
  return selected;
}

async function navigateSidebar(page: Page, id: "dispatch" | "products" | "inventory", mobile: boolean) {
  // Permission-dependent sidebar indices are not route identities.
  const labels = {
    dispatch: /^(التوزيع والمناطق|Dispatch & Regions)$/,
    products: /^(المنتجات|Products)$/,
    inventory: /^(المخزون والمستودع|Inventory & Warehouse)$/,
  };
  const target = page.locator(".operations-nav").getByRole("button", { name: labels[id] });
  if (mobile) await page.locator(".dashboard-mobile-menu").click();
  await expect(target, "Authorized sidebar destination must be visible").toBeVisible({ timeout: 15000 });
  await target.click();
  await expect(page).toHaveURL(new RegExp("/" + id + "$"));
  await expect(page.getByRole("heading", { name: /حدث خطأ غير متوقع|An unexpected error/i }),
    "React render must survive this real cross-page navigation").toHaveCount(0);
}

async function prepareLaunch(page: Page) {
  await page.goto(origin + "/dispatch");
  await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible();
  const tab = page.getByRole("tab", { name: "إطلاق خط جديد" });
  await expect(tab).toBeEnabled({ timeout: 30000 });
  await tab.click();
  await expect(page.getByTestId("dispatch-launch-workspace")).toBeVisible();
  await expect(page.getByTestId("dispatch-launch-workspace")).not.toHaveAttribute("inert", "", { timeout: 30000 });
  const chosen = await selectAuthorizedChoices(page);
  await page.waitForTimeout(300);
  // A missing config may be a crashed React root, not an empty/late data panel.
  await expect(page.getByRole("heading", { name: /حدث خطأ غير متوقع|An unexpected error/i }),
    "No React error boundary during signed resource selection (check draft/UOM bundle compatibility)").toHaveCount(0);
  await expect(page.locator(".dispatch-launch-config")).toBeVisible();
  return chosen;
}

// Install reference nodes once, before leaving the route; frame samples include
// genuine JS DOM identity (not just bounding-box similarity).
async function setReference(page: Page) {
  await page.evaluate(() => {
    const w = window as any;
    const workspace = document.querySelector('[data-testid="dispatch-launch-workspace"]') as HTMLElement;
    const config = workspace.querySelector(".dispatch-launch-config") as HTMLElement;
    const product = config.nextElementSibling as HTMLElement;
    const tab = document.querySelectorAll(".dispatch-tab-list [role=tab]")[1] as HTMLElement;
    const fields = [...config.querySelectorAll("div.relative.mt-2 > div.relative > button")];
    w.__d15P1Ref = {
      workspace, config, product, fields,
      gold: getComputedStyle(tab).backgroundColor,
      top: config.getBoundingClientRect().top,
      height: config.getBoundingClientRect().height,
      productTop: product.getBoundingClientRect().top,
      scrollTop: workspace.scrollTop,
    };
  });
}

async function armFrames(page: Page, label: string) {
  await page.evaluate(label => {
    const w = window as any;
    w.__d15P1Frames = [];
    const begin = performance.now();
    const sample = () => {
      if (location.pathname === "/dispatch") {
        const workspace = document.querySelector('[data-testid="dispatch-launch-workspace"]') as HTMLElement | null;
        const visible = Boolean(workspace && workspace.getClientRects().length && workspace.getBoundingClientRect().height);
        if (visible) {
          const config = workspace!.querySelector(".dispatch-launch-config") as HTMLElement | null;
          const product = config?.nextElementSibling as HTMLElement | null;
          const section = config?.querySelector('[data-testid="d11-commercial-preflight"]') as HTMLElement | null;
          const buttons = config ? [...config.querySelectorAll("div.relative.mt-2 > div.relative > button")] as HTMLButtonElement[] : [];
          const tab = document.querySelectorAll(".dispatch-tab-list [role=tab]")[1] as HTMLButtonElement;
          const tabs = [...document.querySelectorAll(".dispatch-tab-list [role=tab]")] as HTMLButtonElement[];
          const ref = w.__d15P1Ref;
          const locked = workspace!.hasAttribute("inert");
          const text = section?.textContent || "";
          w.__d15P1Frames.push({
            ms: Math.round(performance.now() - begin), label,
            sameWorkspace: workspace === ref.workspace,
            sameConfig: config === ref.config,
            sameProduct: product === ref.product,
            sameFields: buttons.length === 4 && buttons.every((b,i) => b === ref.fields[i]),
            tabs: tabs.length, selected: tab.getAttribute("aria-selected") === "true",
            selectedCount: tabs.filter(t => t.getAttribute("aria-selected") === "true").length,
            gold: getComputedStyle(tab).backgroundColor === ref.gold,
            goldColor: getComputedStyle(tab).backgroundColor,
            tabDisabled: tab.disabled, locked,
            controlsDisabled: buttons.length === 4 && buttons.every(b => b.disabled),
            checkingText: text.includes("جاري التحقق من الإعدادات الحالية") || text.includes("Checking current company"),
            sectionExists: Boolean(section), busy: section?.getAttribute("aria-busy"),
            configHeightDelta: config ? Math.abs(config.getBoundingClientRect().height-ref.height) : -1,
            configTopDelta: config ? Math.abs(config.getBoundingClientRect().top-ref.top) : -1,
            productTopDelta: product ? Math.abs(product.getBoundingClientRect().top-ref.productTop) : -1,
            scrollDelta: Math.abs(workspace!.scrollTop - ref.scrollTop),
            overflow: document.documentElement.scrollWidth - innerWidth,
          });
        }
      }
      if (performance.now()-begin < 2000) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }, label);
}

async function inspect(page: Page, label: string, held: { access: number; init: number }, selectedCount: number) {
  await page.waitForTimeout(2050);
  const frames = await page.evaluate(() => ((window as any).__d15P1Frames || []) as Array<{
    sameWorkspace: boolean; sameConfig: boolean; sameProduct: boolean; sameFields: boolean;
    selected: boolean; selectedCount: number; gold: boolean; tabDisabled: boolean;
    locked: boolean; controlsDisabled: boolean; checkingText: boolean; sectionExists: boolean;
    configHeightDelta: number; configTopDelta: number; productTopDelta: number;
    scrollDelta: number; overflow: number; tabs: number; busy: string | null;
  }>);
  const outcome = {
    label, selectedCount, samples: frames.length, held,
    lostGold: frames.filter(x => !x.selected || !x.gold || x.selectedCount !== 1).length,
    remount: frames.filter(x => !x.sameWorkspace || !x.sameConfig || !x.sameProduct || !x.sameFields).length,
    checking: frames.filter(x => x.checkingText).length,
    wrongTabs: frames.filter(x => x.tabs !== 3).length,
    leakedControls: frames.filter(x => x.locked && (!x.tabDisabled || !x.controlsDisabled)).length,
    noPanel: frames.filter(x => !x.sectionExists).length,
    maxHeightDelta: Math.max(0, ...frames.map(x => x.configHeightDelta)),
    maxConfigTopDelta: Math.max(0, ...frames.map(x => x.configTopDelta)),
    maxProductTopDelta: Math.max(0, ...frames.map(x => x.productTopDelta)),
    maxScrollDelta: Math.max(0, ...frames.map(x => x.scrollDelta)),
    overflowFrames: frames.filter(x => x.overflow !== 0).length,
    lockedSamples: frames.filter(x => x.locked).length,
    readySamples: frames.filter(x => !x.locked).length,
  };
  console.log("D15_P1_LAUNCH_RAF=" + JSON.stringify(outcome));
  if (enforce) {
    expect(outcome.samples, label).toBeGreaterThan(10);
    expect(outcome.lostGold, label).toBe(0);
    expect(outcome.remount, label).toBe(0);
    expect(outcome.checking, label).toBe(0);
    expect(outcome.wrongTabs, label).toBe(0);
    expect(outcome.leakedControls, label).toBe(0);
    expect(outcome.noPanel, label).toBe(0);
    expect(outcome.maxHeightDelta, label).toBeLessThanOrEqual(2);
    expect(outcome.maxConfigTopDelta, label).toBeLessThanOrEqual(2);
    expect(outcome.maxProductTopDelta, label).toBeLessThanOrEqual(2);
    expect(outcome.maxScrollDelta, label).toBeLessThanOrEqual(2);
    expect(outcome.overflowFrames, label).toBe(0);
  }
}

for (const language of ["ar", "en"] as const) for (const width of [1440,390] as const) {
  test("D15 P1 Launch secure reentry gold + geometry " + language + " " + width, async ({ page }) => {
    test.setTimeout(180000);
    mkdirSync(imageDir, { recursive: true });
    await page.setViewportSize({ width, height: 900 });
    await signIn(page, language);
    const selections = await prepareLaunch(page);
    await setReference(page);
    const held = { access: 0, init: 0 };
    let hold = false;
    await page.route("**/inventory/access/me", async route => {
      if (hold) { held.access++; await page.waitForTimeout(320); }
      await route.continue();
    });
    await page.route("**/dispatch/init", async route => {
      if (hold) { held.init++; await page.waitForTimeout(450); }
      await route.continue();
    });
    for (const dest of ["products","inventory"] as const) {
      await navigateSidebar(page, dest, width === 390);
      hold = true;
      const label = language + ":" + width + ":" + dest;
      await armFrames(page, label);
      await navigateSidebar(page, "dispatch", width === 390);
      await page.waitForTimeout(190);
      await page.screenshot({ path: imageDir + "/" + label.replaceAll(":","-") + "-pending.png" });
      await inspect(page, label, { ...held }, selections);
      await page.screenshot({ path: imageDir + "/" + label.replaceAll(":","-") + "-ready.png" });
      await expect(page.getByRole("tab", { name: "إطلاق خط جديد" })).toHaveAttribute("aria-selected","true");
      await setReference(page);
      hold = false;
    }
    // Actual history transition instead of a fabricated tab event.
    await page.goBack();
    await expect(page).toHaveURL(/\/inventory$/);
    hold = true;
    await armFrames(page, language + ":" + width + ":history");
    await page.goForward();
    await expect(page).toHaveURL(/\/dispatch$/);
    await inspect(page, language + ":" + width + ":history", { ...held }, selections);
  });
}

test("D15 P1 Products and Inventory first-page scripts exclude the lazy DispatchBoard", async ({ page, browser }) => {
  await signIn(page, "ar");
  const values = await page.evaluate(() => Object.fromEntries(
    Array.from({ length: localStorage.length }, (_, i) => {
      const key = localStorage.key(i)!;
      return [key, localStorage.getItem(key)];
    }),
  ));
  for (const target of ["products", "inventory"]) {
    const context = await browser.newContext();
    await context.addInitScript(state => {
      for (const [key,value] of Object.entries(state)) if (value !== null) localStorage.setItem(key, value);
    }, values);
    const fresh = await context.newPage();
    const js: string[] = [];
    fresh.on("request", request => { if (/\/assets\/.+\.js(?:\?|$)/.test(request.url())) js.push(request.url()); });
    await fresh.goto(origin + "/" + target);
    await expect(fresh).toHaveURL(new RegExp("/" + target + "$"));
    await fresh.waitForTimeout(1000);
    const dispatch = js.filter(url => /DispatchBoard-[^/]+\.js/.test(url));
    console.log("D15_P1_NETWORK=" + JSON.stringify({ target, count: js.length, dispatchCount: dispatch.length }));
    expect(dispatch).toHaveLength(0);
    await context.close();
  }
});
