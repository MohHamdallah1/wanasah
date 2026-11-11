/**
 * D15 #909 — evidence-only REAL PG16/Chromium horizontal geometry.
 *
 * Prerequisite: D14's isolated PostgreSQL16 fixture, real FastAPI :4174,
 * built Vite Dashboard :4173 and genuine Chromium. No HTTP route mocks,
 * authentication bypass, page.route or changes to business data.
 *
 * Run in that environment from dashboard/:
 * npx playwright test e2e/dispatch-d15-horizontal-overflow.spec.ts --workers=1
 *
 * This spec is intentionally standalone and does not widen D14's protected
 * testMatch/CI ownership rules. LEAD owns any CI integration seam.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { expect, test, type Page } from "playwright/test";

type Language = "ar" | "en";
type DispatchTab = "routes" | "launch" | "zones";
type Edge = { left: number; right: number; width: number };
type Offender = {
  element: string; left: number; right: number; excessLeft: number; excessRight: number;
  nearestScrollContainer: string | null; nearestOverflowX: string | null;
};
type Geometry = {
  viewport: number; documentClient: number; documentScroll: number;
  bodyClient: number; bodyScroll: number; scrollerClient: number; scrollerScroll: number;
  forbiddenRootExcess: number;
  dispatchContainers: Array<{ selector: string; client: number; scroll: number; excess: number; rect: Edge }>;
  internalScrollers: Array<{ element: string; excess: number; overflowX: string }>;
  offenders: Offender[];
  zones?: { parent: Edge; first: Edge; second: Edge; gap: number; childSumMinusParent: number };
  clippedButtons: Array<{ element: string; clippingAncestor: string; amount: number }>;
};

const apiStateFile = process.env.WANASAH_DISPATCH_D14_BROWSER_STATE;
if (!apiStateFile) {
  throw new Error("D15_REAL_PG16_REQUIRED: use the existing D14 real signed PG16 fixture");
}
const fixture = JSON.parse(readFileSync(apiStateFile, "utf8")) as {
  credentials: { owner: { code: string; username: string; password: string } };
  zones: { a1: string };
  shops: { assigned: { name: string } };
};

test.use({ baseURL: "http://127.0.0.1:4173", browserName: "chromium",
  viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" });
test.describe.configure({ mode: "serial" });

async function signIn(page: Page, language: Language) {
  await page.goto("/");
  await page.evaluate(lang => {
    localStorage.clear();
    localStorage.setItem("wanasah.language", lang);
  }, language);
  await page.goto("/login");
  await page.reload();
  await page.locator("#company-code").fill(fixture.credentials.owner.code);
  await page.locator("#username").fill(fixture.credentials.owner.username);
  await page.locator("#password").fill(fixture.credentials.owner.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 25_000 }),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.goto("/dispatch");
  await expect(page.getByTestId("dispatch-shared-topbar"))
    .toBeVisible({ timeout: 45_000 });
  await expect(page.getByRole("tab", { name: /الخطوط النشطة|Active routes/ }))
    .toBeVisible({ timeout: 45_000 });
}

async function selectTab(page: Page, tab: DispatchTab) {
  const label = tab === "routes" ? /الخطوط النشطة|Active routes/
    : tab === "launch" ? /إطلاق خط جديد|Launch route/
    : /هيكلة المناطق|Zones & shops/;
  const button = page.getByRole("tab", { name: label });
  await button.click();
  await expect(button).toHaveAttribute("aria-selected", "true");
  if (tab === "launch") {
    await expect(page.locator(".dispatch-launch-config")).toBeVisible();
  } else if (tab === "zones") {
    await expect(page.locator(".dispatch-zones-workbench")).toBeVisible();
    const left = page.locator(".dispatch-zones-workbench > div").first();
    const zone = left.getByText(fixture.zones.a1, { exact: true }).first();
    await expect(zone).toBeVisible({ timeout: 25_000 });
    await zone.click();
    await expect(page.locator(".dispatch-shop-table tbody tr")
      .filter({ hasText: fixture.shops.assigned.name })).toHaveCount(1);
  } else {
    await expect(page.locator(".dispatch-route-list").first()).toBeVisible();
  }
  // No animation/transition-only frames; inspect stable mounted DOM.
  await page.waitForTimeout(120);
}

async function measure(page: Page): Promise<Geometry> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const scroller = document.scrollingElement || root;
    const edge = (r: DOMRect): Edge => ({
      left: Math.round(r.left * 100) / 100,
      right: Math.round(r.right * 100) / 100,
      width: Math.round(r.width * 100) / 100,
    });
    const name = (el: Element) => {
      const testId = el.getAttribute("data-testid");
      if (testId) return `[data-testid="${testId}"]`;
      const classes = Array.from(el.classList).filter(Boolean).slice(0, 3);
      return el.tagName.toLowerCase() + classes.map(c => "." + CSS.escape(c)).join("");
    };
    const isRendered = (el: Element) => {
      const css = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return css.display !== "none" && css.visibility !== "hidden" &&
        rect.width > 0.5 && rect.height > 0.5;
    };
    const containerNames = [
      ".dashboard-shell", ".dashboard-main-stage", ".dashboard-content",
      ".dispatch-board", ".dispatch-content", ".dispatch-zones-workbench",
      ".dispatch-launch-config", ".dispatch-route-list", ".dispatch-shop-table",
      ".dispatch-tab-list", '[data-testid="dispatch-shared-topbar"]',
    ];
    const dispatchContainers = containerNames.flatMap(selector =>
      [...document.querySelectorAll(selector)].filter(isRendered).map(el => {
        const node = el as HTMLElement;
        return { selector, client: node.clientWidth, scroll: node.scrollWidth,
          excess: Math.max(0, node.scrollWidth - node.clientWidth),
          rect: edge(el.getBoundingClientRect()) };
      }));
    const offenders: Offender[] = [];
    const internalScrollers: Geometry["internalScrollers"] = [];
    const clippedButtons: Geometry["clippedButtons"] = [];
    for (const el of document.querySelectorAll("*")) {
      if (!isRendered(el)) continue;
      const node = el as HTMLElement;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const localExcess = Math.max(0, node.scrollWidth - node.clientWidth);
      if (localExcess > 1 && /(auto|scroll)/.test(style.overflowX)) {
        internalScrollers.push({ element: name(el), excess: localExcess,
          overflowX: style.overflowX });
      }
      const left = Math.max(0, -rect.left);
      const right = Math.max(0, rect.right - root.clientWidth);
      if (left > 1 || right > 1) {
        let scrollAncestor: Element | null = el.parentElement;
        while (scrollAncestor) {
          const overflowX = getComputedStyle(scrollAncestor).overflowX;
          if (/(auto|scroll|hidden|clip)/.test(overflowX)) break;
          scrollAncestor = scrollAncestor.parentElement;
        }
        const ancestorOverflow = scrollAncestor
          ? getComputedStyle(scrollAncestor).overflowX : null;
        // Fixed offscreen drawers and intentional nested table/tab scrollers
        // are recorded but distinguished from document-level overflow.
        if (offenders.length < 160) {
          offenders.push({ element: name(el), left: edge(rect).left,
            right: edge(rect).right, excessLeft: Math.round(left),
            excessRight: Math.round(right),
            nearestScrollContainer: scrollAncestor ? name(scrollAncestor) : null,
            nearestOverflowX: ancestorOverflow });
        }
      }
      if (el instanceof HTMLButtonElement && el.closest(".dispatch-board") &&
          !el.closest('[aria-hidden="true"]') && clippedButtons.length < 40) {
        let ancestor = el.parentElement;
        while (ancestor) {
          const overflow = getComputedStyle(ancestor).overflowX;
          if (/(auto|scroll)/.test(overflow)) break; // intentional horizontal scroller
          if (/(hidden|clip)/.test(overflow)) {
            const parent = ancestor.getBoundingClientRect();
            const excess = Math.max(0, rect.right - parent.right, parent.left - rect.left);
            if (excess > 1) clippedButtons.push({
              element: name(el), clippingAncestor: name(ancestor),
              amount: Math.round(excess),
            });
            break;
          }
          ancestor = ancestor.parentElement;
        }
      }
    }
    const columns = document.querySelector(".dispatch-zones-workbench");
    let zones: Geometry["zones"];
    if (columns && columns.children.length >= 2) {
      const p = columns.getBoundingClientRect();
      const a = columns.children[0].getBoundingClientRect();
      const b = columns.children[1].getBoundingClientRect();
      const gap = parseFloat(getComputedStyle(columns).columnGap) || 0;
      zones = { parent: edge(p), first: edge(a), second: edge(b),
        gap, childSumMinusParent: Math.round((a.width + b.width + gap - p.width) * 100) / 100 };
    }
    return {
      viewport: window.innerWidth,
      documentClient: root.clientWidth, documentScroll: root.scrollWidth,
      bodyClient: body.clientWidth, bodyScroll: body.scrollWidth,
      scrollerClient: scroller.clientWidth, scrollerScroll: scroller.scrollWidth,
      forbiddenRootExcess: Math.max(0, root.scrollWidth - root.clientWidth,
        body.scrollWidth - body.clientWidth,
        scroller.scrollWidth - scroller.clientWidth),
      dispatchContainers, internalScrollers: internalScrollers.slice(0, 80),
      offenders: offenders.sort((a, b) => Math.max(b.excessLeft, b.excessRight) -
        Math.max(a.excessLeft, a.excessRight)).slice(0, 35),
      zones, clippedButtons,
    };
  });
}

for (const language of ["ar", "en"] as const) {
  for (const width of [390, 768, 1024, 1280, 1440]) {
    test(`D15 REAL Chromium PG16 no page scroll: ${language} ${width}px all three tabs`,
      async ({ page }, info) => {
        test.setTimeout(150_000);
        await page.setViewportSize({ width, height: 900 });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await signIn(page, language);
        const results: Array<{ tab: DispatchTab; phase: "normal" | "refocus"; geometry: Geometry }> = [];
        const failures: string[] = [];
        for (const tab of ["routes", "launch", "zones"] as const) {
          await selectTab(page, tab);
          for (const phase of ["normal", "refocus"] as const) {
            if (phase === "refocus") {
              const elsewhere = await page.context().newPage();
              await elsewhere.goto("about:blank");
              await elsewhere.bringToFront();
              await page.bringToFront();
              await elsewhere.close();
              await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible();
              if (tab === "zones") {
                await expect(page.locator(".dispatch-shop-table tbody tr")
                  .filter({ hasText: fixture.shops.assigned.name }))
                  .toHaveCount(1, { timeout: 30_000 });
              }
              await page.waitForTimeout(120);
            }
            const geometry = await measure(page);
            results.push({ tab, phase, geometry });
            await page.screenshot({ path: info.outputPath(
              `d15-${language}-${width}-${tab}-${phase}.png`), fullPage: true });
            console.log("D15_REAL_GEOMETRY=" + JSON.stringify({
              language, width, tab, phase, ...geometry,
            }));
            if (geometry.forbiddenRootExcess > 0) {
              failures.push(`${tab}/${phase}: root +${geometry.forbiddenRootExcess}px`);
            }
            const unwelcome = geometry.dispatchContainers.filter(x =>
              [".dashboard-main-stage", ".dashboard-content", ".dispatch-board",
               ".dispatch-content", ".dispatch-zones-workbench"].includes(x.selector) &&
              x.excess > 1);
            for (const el of unwelcome) {
              failures.push(`${tab}/${phase}: ${el.selector} +${el.excess}px`);
            }
            if (geometry.clippedButtons.length) {
              failures.push(`${tab}/${phase}: ${geometry.clippedButtons.length} clipped buttons`);
            }
          }
        }
        // One complete JSON matrix per authentic signed fixture, even on fail.
        writeFileSync(info.outputPath(`d15-${language}-${width}-geometry.json`),
          JSON.stringify({ language, width, fixture: "real-postgres16-signed-owner",
            results, failures }, null, 2));
        expect(failures, `D15 horizontal root/ancestor overflow: ${language} ${width}px`)
          .toEqual([]);
      });
  }
}
