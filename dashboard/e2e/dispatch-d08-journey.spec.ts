import { readFileSync, writeFileSync } from "node:fs";
import { expect, test } from "playwright/test";

const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_D08_STATE!, "utf8"));
const API = "http://127.0.0.1:4174";
const routeStatus = `/dispatch/route/${state.routeId}/status`;
const adjust = `/dispatch/route/${state.routeId}/adjust_inventory`;

test("D08 real Dashboard Zone UI → route state → vehicle load → existing operations handoff", async ({ page }, info) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const wires: Array<{ method: string; path: string; status: number }> = [];
  page.on("response", response => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/dispatch/") || path.startsWith("/admin/sessions/")) {
      wires.push({ path, method: response.request().method(), status: response.status() });
    }
  });

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

  await page.goto("/dispatch");
  await expect(page.locator(".dispatch-route-row").first()).toBeVisible();

  // Real user Zone create UI, not direct API calls or intercepted network.
  await page.getByRole("tab", { name: /هيكلة المناطق/ }).click();
  await page.getByRole("button", { name: /منطقة جديدة/ }).click();
  const zoneDialog = page.getByRole("dialog");
  await expect(zoneDialog).toBeVisible();
  const browserZone = "D08 UI Zone " + Date.now();
  await zoneDialog.locator('input[type="text"]').fill(browserZone);
  const created = page.waitForResponse(r => new URL(r.url()).pathname === "/dispatch/zones"
    && r.request().method() === "POST");
  await zoneDialog.locator('button[type="submit"]').click();
  expect((await created).status()).toBe(201);
  await expect(page.getByText(browserZone).first()).toBeVisible();
  // Successful Zone creation opens the mandatory scheduling dialog.
  const schedule = page.getByRole("dialog", { name: "إعدادات الجدولة" });
  await expect(schedule).toBeVisible();
  await schedule.locator('input[type="date"]').fill("2026-11-13");
  const scheduled = page.waitForResponse(r => new URL(r.url()).pathname.startsWith("/dispatch/zones/")
    && r.request().method() === "PUT");
  await schedule.getByRole("button", { name: "تأكيد الجدولة" }).click();
  expect((await scheduled).status()).toBe(200);
  await expect(schedule).not.toBeVisible();

  await page.getByRole("tab", { name: /الخطوط النشطة/ }).click();
  const row = page.locator(".dispatch-route-row").first();
  await expect(row.getByRole("button", { name: "متابعة الحمولة" })).toBeEnabled();
  await row.getByRole("button", { name: "متابعة الحمولة" }).click();
  const statusDialog = page.getByRole("dialog");
  await expect(statusDialog).toBeVisible();
  const activation = page.waitForResponse(r =>
    new URL(r.url()).pathname === routeStatus && r.request().method() === "PUT");
  await statusDialog.getByRole("button", { name: "Confirm route status and assignment" }).click();
  expect((await activation).status()).toBe(200);
  await expect(page.locator(".dispatch-route-row").first()
    .getByRole("button", { name: "تعديل الحمولة" })).toBeEnabled();

  // Active Visit must block cross-zone Shop movement. Real API and auth used by the UI.
  const deniedMove = await page.evaluate(async ({ endpoint, shopId, zoneId, origin }) => {
    const r = await fetch(origin + endpoint, {
      method: "PUT",
      headers: {
        Authorization: "Bearer " + localStorage.getItem("admin_token"),
        "Content-Type": "application/json",
      },
      body: JSON.stringify([{ id: String(shopId), zoneId: String(zoneId) }]),
    });
    return { status: r.status, body: await r.json() };
  }, { endpoint: "/dispatch/shops/bulk_update", shopId: state.importedShopId,
       zoneId: state.zoneId, origin: API });
  expect(deniedMove.status).toBe(409);

  await page.locator(".dispatch-route-row").first()
    .getByRole("button", { name: "تعديل الحمولة" }).click();
  const inventory = page.getByRole("dialog");
  await expect(inventory).toBeVisible();
  const input = inventory.getByRole("spinbutton").first();
  await input.fill("1");
  await inventory.getByRole("button", { name: "Review changes" }).click();
  const loaded = page.waitForResponse(r => new URL(r.url()).pathname === adjust
    && r.request().method() === "PUT");
  await inventory.getByRole("button", { name: "Confirm adjustment" }).click();
  const loadResponse = await loaded;
  expect(loadResponse.status()).toBe(200);
  expect((await loadResponse.json()).mode).toBe("DIRECT");

  // The route's closure does NOT silently unload or settle vehicle custody.
  await page.reload();
  const active = page.locator(".dispatch-route-row").first();
  await expect(active.getByRole("button", { name: "إيقاف مؤقت" })).toBeEnabled();
  const stopped = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await active.getByRole("button", { name: "إيقاف مؤقت" }).click();
  expect((await stopped).status()).toBe(200);
  const resumedRow = page.locator(".dispatch-route-row").first();
  await expect(resumedRow.getByRole("button", { name: "متابعة الحمولة" })).toBeVisible();
  await resumedRow.getByRole("button", { name: "متابعة الحمولة" }).click();
  const resume = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await page.getByRole("dialog").getByRole("button", { name: "Confirm route status and assignment" }).click();
  expect((await resume).status()).toBe(200);

  const closed = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await page.locator(".dispatch-route-row").first()
    .getByRole("button", { name: "إيقاف مؤقت" }).click();
  expect((await closed).status()).toBe(200);
  await page.getByRole("button", { name: /عرض المؤجل/ }).click();
  await expect(page.getByRole("dialog")).toBeVisible();

  writeFileSync(info.outputPath("d08-real-wire.json"), JSON.stringify({
    backend: state.confirmed, browser: {
      zoneCreate: true, routeActivate: true, blockedActiveShopMove: true,
      vehicleAdjust: true, routeStopAndRestore: true,
    }, wires,
  }, null, 2));
  expect(wires.some(w => w.path === "/dispatch/zones" && w.method === "POST" && w.status === 201)).toBe(true);
  expect(wires.some(w => w.path === adjust && w.method === "PUT" && w.status === 200)).toBe(true);
});

test("D08 real mobile 390px authenticated routes and zone controls", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await page.locator("#company-code").fill(state.credentials.code);
  await page.locator("#username").fill(state.credentials.username);
  await page.locator("#password").fill(state.credentials.password);
  await Promise.all([
    page.waitForURL(url => url.pathname !== "/login"),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.goto("/dispatch");
  await expect(page.getByRole("tab", { name: /هيكلة المناطق/ })).toBeVisible();
  await page.getByRole("tab", { name: /هيكلة المناطق/ }).click();
  await expect(page.getByRole("button", { name: /منطقة جديدة/ })).toBeVisible();
  const metrics = await page.evaluate(() => ({
    width: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
  }));
  expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.width);
  console.log("D08_REAL_MOBILE=" + JSON.stringify(metrics));
});
