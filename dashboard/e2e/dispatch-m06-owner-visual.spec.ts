import { expect, test, type Page } from "playwright/test";
import { mkdirSync, readFileSync } from "node:fs";

// This is D12's genuine disposable restricted PG16 seed, not a mocked HTTP
// route or a fabricated Dashboard model. M05's scenario UI is NOT yet on MAIN.
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D12_STATE!, "utf8"));
const evidence = "node_modules/.cache/dispatch-m06-owner-visual";
const readPaths = new Set(["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes", "/dispatch/shortages"]);

async function login(page: Page, language: "ar" | "en") {
  await page.goto("/");
  await page.evaluate(locale => {
    localStorage.clear();
    localStorage.setItem("wanasah.language", locale);
  }, language);
  await page.goto("/login");
  await page.reload();
  await page.locator("#company-code").fill(state.credentials.code);
  await page.locator("#username").fill(state.credentials.username);
  await page.locator("#password").fill(state.credentials.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login", { timeout: 35000 }),
    page.locator('button[type="submit"]').click(),
  ]);
}

async function navigate(page: Page, target: "dispatch" | "products", mobile: boolean) {
  if (mobile) await page.locator(".dashboard-mobile-menu").click();
  await page.locator(".operations-nav button")
    .nth(target === "dispatch" ? 1 : 4).click();
  await expect(page).toHaveURL(new RegExp("/" + target + "$"), { timeout: 25000 });
}

function sampleReentry() {
  const w = window as any;
  const started = performance.now();
  const samples: Array<{
    tabs: number; shell: boolean; routeRows: number;
    falseZero: boolean; falseSkeleton: boolean; docWidth: number; viewport: number;
  }> = [];
  w.__m06Samples = samples;
  function frame() {
    if (location.pathname === "/dispatch") {
      const board = document.querySelector(".dispatch-board");
      const shell = board?.querySelector('[data-testid="dispatch-shared-topbar"]');
      const stage = document.querySelector(".dashboard-main-stage");
      const routeRows = document.querySelectorAll(".dispatch-route-row").length;
      samples.push({
        tabs: shell?.querySelectorAll('[role="tab"]').length ?? 0,
        shell: Boolean(shell && (shell as HTMLElement).getClientRects().length > 0),
        routeRows,
        falseZero: Boolean(
          (stage as HTMLElement | null)?.getClientRects().length &&
          !shell && !stage?.querySelector(".dashboard-access-state") &&
          !stage?.querySelector('[role="status"]')
        ),
        falseSkeleton: Boolean(document.querySelector('[data-testid="dispatch-quiet-loading"]')),
        docWidth: document.documentElement.scrollWidth, viewport: innerWidth,
      });
    }
    if (performance.now() - started < 1100) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

for (const language of ["ar", "en"] as const) {
  for (const width of [1440, 390] as const) {
    test("M06 independent real D15 visual baseline " + language + " " + width, async ({ page }, info) => {
      test.setTimeout(165000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: 900 });
      await login(page, language);
      const traffic = new Map<string, number>();
      page.on("response", response => {
        const url = new URL(response.url());
        if (!readPaths.has(url.pathname)) return;
        if (response.status() !== 200) return;
        traffic.set(url.pathname, (traffic.get(url.pathname) ?? 0) + 1);
      });

      await page.goto("/dispatch");
      await expect(page.getByTestId("dispatch-shared-topbar")).toBeVisible({ timeout: 45000 });
      await expect(page.locator(".dispatch-route-row").first()).toBeVisible({ timeout: 60000 });
      await expect(page.getByRole("tab")).toHaveCount(3);
      const before = await page.locator(".dispatch-route-row").count();
      expect(before).toBeGreaterThan(0);
      const firstDocumentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(firstDocumentWidth).toBe(width);
      await page.screenshot({ path: info.outputPath("owner-initial.png"), fullPage: true });

      // Visit another real workspace through the existing navigation, not
      // reload / mocked route. The same mounted Dispatch host must survive.
      await expect(page.locator('[data-persistent-dispatch-host="true"]')).toHaveCount(1);
      await page.locator('[data-persistent-dispatch-host="true"]')
        .evaluate(node => node.setAttribute("data-m06-mounted", "same"));
      await navigate(page, "products", width === 390);
      await page.evaluate(sampleReentry);
      await navigate(page, "dispatch", width === 390);
      await expect(page.locator(".dispatch-route-row").first()).toBeVisible({ timeout: 45000 });
      await page.waitForTimeout(1200);
      const samples = await page.evaluate(() => ((window as any).__m06Samples ?? []) as Array<{
        shell: boolean; tabs: number; routeRows: number;
        falseZero: boolean; falseSkeleton: boolean; docWidth: number; viewport: number;
      }>);
      expect(samples.length, "Actual SPA return must be measured in Chromium frames").toBeGreaterThan(0);
      expect(samples.filter(s => s.falseZero).length, "No visibly blank Dashboard after signed admission").toBe(0);
      expect(samples.filter(s => s.shell && s.tabs !== 3).length, "No disappearing tabs").toBe(0);
      expect(samples.filter(s => s.falseSkeleton).length, "Never mount a fake loading table").toBe(0);
      expect(samples.filter(s => s.docWidth !== s.viewport).length, "No outer horizontal scroll").toBe(0);
      await expect(page.locator('[data-persistent-dispatch-host="true"][data-m06-mounted="same"]')).toHaveCount(1);
      await page.screenshot({ path: info.outputPath("owner-after-reentry.png"), fullPage: true });

      // Launch is the first place the D15 contract permits a real Shops GET.
      const launch = page.getByRole("tab", { name: "إطلاق خط جديد" });
      await expect(launch).toBeEnabled({ timeout: 25000 });
      await launch.click();
      await expect(launch).toHaveAttribute("aria-selected", "true");
      await expect.poll(() => traffic.get("/dispatch/shops") ?? 0, { timeout: 35000 }).toBeGreaterThan(0);
      await expect(page.getByTestId("dispatch-launch-workspace")).toBeVisible();
      await page.screenshot({ path: info.outputPath("owner-launch.png"), fullPage: true });
      const summary = {
        language, width, routeRows: before, sampledFrames: samples.length,
        realSignedResponses: Object.fromEntries(traffic),
        mobile: width === 390,
        M05Integrated: false, ownerReviewed: false,
      };
      console.log("M06_OWNER_VISUAL_BASELINE=" + JSON.stringify(summary));
      await info.attach("m06-visual-measurements.json", {
        body: Buffer.from(JSON.stringify(summary, null, 2)), contentType: "application/json",
      });
    });
  }
}
