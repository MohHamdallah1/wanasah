import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "playwright/test";

const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D12_STATE!, "utf8"));
const endpoints = ["/dispatch/init", "/dispatch/shops", "/dispatch/active_routes", "/dispatch/shortages"];

for (const width of [1440, 390]) {
  test(`D12 real PG16 authenticated Dispatch read and visible DOM ${width}px`, async ({ page }, info) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/login");
    await page.evaluate(() => localStorage.setItem("wanasah.language", "en"));
    await page.reload();
    await page.locator("#company-code").fill(state.credentials.code);
    await page.locator("#username").fill(state.credentials.username);
    await page.locator("#password").fill(state.credentials.password);
    await Promise.all([
      page.waitForURL(url => url.pathname !== "/login"),
      page.locator('button[type="submit"]').click(),
    ]);
    const seen = new Map<string, { status: number; bytes: number; duration: number }>();
    page.on("response", async response => {
      const path = new URL(response.url()).pathname;
      if (!endpoints.includes(path)) return;
      const timing = response.request().timing();
      seen.set(path, {
        status: response.status(),
        bytes: (await response.body()).length,
        duration: timing.responseEnd >= 0 && timing.startTime >= 0
          ? timing.responseEnd - timing.startTime : -1,
      });
    });
    const started = Date.now();
    await page.goto("/dispatch");
    await expect(page.locator(".dispatch-route-row").first()).toBeVisible({ timeout: 60000 });
    await expect.poll(() => seen.size, { timeout: 60000 }).toBe(4);
    const rendered = await page.evaluate(() => ({
      domNodes: document.querySelectorAll("*").length,
      visibleRouteRow: document.querySelectorAll(".dispatch-route-row").length,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    const result = {
      width, loadMs: Date.now() - started, ...rendered,
      reads: Object.fromEntries(seen),
    };
    expect(rendered.visibleRouteRow).toBeGreaterThan(0);
    expect([...seen.values()].every(x => x.status === 200)).toBe(true);
    writeFileSync(info.outputPath(`d12-real-browser-${width}.json`), JSON.stringify(result, null, 2));
    console.log("D12_AUTHENTICATED_BROWSER=" + JSON.stringify(result));
  });
}
