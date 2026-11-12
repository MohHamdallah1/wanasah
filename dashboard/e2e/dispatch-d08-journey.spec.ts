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

  // Owner-visible Shop actions on the same real company, not API-only claims.
  await page.getByRole("button", { name: "إضافة محل" }).click();
  let shopDialog = page.getByRole("dialog");
  const uiShop = "D08 UI Shop " + Date.now();
  await shopDialog.locator("#shop-form input[type='text']").first().fill(uiShop);
  await shopDialog.locator("#shop-form input[type='tel']").fill("5551000821");
  const createdShop = page.waitForResponse(r => new URL(r.url()).pathname === "/dispatch/shops"
    && r.request().method() === "POST");
  await shopDialog.locator('button[form="shop-form"]').click();
  const shopCreateResponse = await createdShop;
  expect(shopCreateResponse.status()).toBe(201);
  const uiShopId = String((await shopCreateResponse.json()).shop_id);
  await expect(shopDialog).not.toBeVisible();

  await page.getByRole("button", { name: "Edit", exact: true }).click();
  let shopRow = page.locator(".dispatch-shop-table tbody tr").filter({ hasText: uiShop });
  await expect(shopRow).toBeVisible();
  await shopRow.getByRole("button", { name: "Edit " + uiShop }).click();
  shopDialog = page.getByRole("dialog");
  const uiShopEdited = uiShop + " edited";
  await shopDialog.locator("#shop-form input[type='text']").first().fill(uiShopEdited);
  const editedShop = page.waitForResponse(r =>
    new URL(r.url()).pathname === "/dispatch/shops/" + uiShopId &&
    r.request().method() === "PUT");
  await shopDialog.locator('button[form="shop-form"]').click();
  expect((await editedShop).status()).toBe(200);
  await expect(shopDialog).not.toBeVisible();

  shopRow = page.locator(".dispatch-shop-table tbody tr").filter({ hasText: uiShopEdited });
  await expect(shopRow).toBeVisible();
  await shopRow.locator('input[type="number"]').fill("7");
  await shopRow.locator('input[type="number"]').press("Tab");
  const reorderResponse = page.waitForResponse(r =>
    new URL(r.url()).pathname === "/dispatch/shops/bulk_update" &&
    r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((await reorderResponse).status()).toBe(200);

  // Successful reorder intentionally exits edit mode. Re-enter before archive.
  await expect(page.getByRole("button", { name: "Edit", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  // Shop archiving in edit mode is a draft until the explicit Save confirmation.
  shopRow = page.locator(".dispatch-shop-table tbody tr").filter({ hasText: uiShopEdited });
  await expect(shopRow.getByRole("button", { name: "Archive " + uiShopEdited })).toBeEnabled();
  await shopRow.getByRole("button", { name: "Archive " + uiShopEdited }).click();
  const hideConfirm = page.getByRole("dialog", { name: "تأكيد الإخفاء" });
  await hideConfirm.getByRole("button", { name: "تأكيد" }).click();
  const archivedShop = page.waitForResponse(r =>
    new URL(r.url()).pathname === "/dispatch/shops/bulk_update" &&
    r.request().method() === "PUT");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((await archivedShop).status()).toBe(200);

  await page.getByTitle("فتح أرشيف المحلات المؤرشفة").click();
  const bin = page.getByRole("dialog", { name: /سلة المحذوفات/ });
  await expect(bin.getByText(uiShopEdited)).toBeVisible();
  const restoredShop = page.waitForResponse(r =>
    new URL(r.url()).pathname === "/dispatch/shops/bulk_update" &&
    r.request().method() === "PUT");
  await bin.getByRole("button", { name: /استعادة/ }).click();
  expect((await restoredShop).status()).toBe(200);
  await bin.locator(".app-modal-header button").click();

  // Actual bilingual paste-import UI maps to the canonical bulk_import endpoint.
  await page.getByRole("button", { name: /استيراد المحلات الذكي/ }).click();
  const importDialog = page.getByRole("dialog", { name: "Import shops" });
  await importDialog.getByRole("button", { name: "Choose a zone" }).click();
  await importDialog.getByRole("button", { name: browserZone }).click();
  const importedName = "D08 UI Imported " + Date.now();
  await importDialog.getByRole("textbox", { name: "Paste spreadsheet data" })
    .fill(importedName + "\t5551000822");
  await importDialog.getByRole("button", { name: "Read pasted data" }).click();
  const importedShop = page.waitForResponse(r => new URL(r.url()).pathname ===
    "/dispatch/shops/bulk_import" && r.request().method() === "POST");
  await importDialog.getByRole("button", { name: "Review and upload shops" }).click();
  expect((await importedShop).status()).toBe(201);
  // Import POST 201 closes the dialog asynchronously. Its header is
  // destroyed during dismissal, so racing a second header click is not a
  // valid business requirement. Verify the actual auto-close contract.
  await expect(importDialog).not.toBeVisible({ timeout: 15000 });

  // Zone edit/archive/restore uses real browser buttons and same-zone shop provenance.
  const zoneList = page.locator(".dispatch-zones-workbench > div:first-child");
  const zoneHeading = zoneList.getByText(browserZone, { exact: true }).first();
  await zoneHeading.locator("xpath=../..").locator("button").first().click();
  const renameDialog = page.getByRole("dialog");
  const renamedUiZone = browserZone + " updated";
  await renameDialog.locator('#zone-form input[type="text"]').fill(renamedUiZone);
  const zoneRename = page.waitForResponse(r => new URL(r.url()).pathname.startsWith(
    "/dispatch/zones/") && r.request().method() === "PUT");
  await renameDialog.locator('button[form="zone-form"]').click();
  expect((await zoneRename).status()).toBe(200);
  await expect(renameDialog).not.toBeVisible();

  const renamedHeading = zoneList.getByText(renamedUiZone, { exact: true }).first();
  await renamedHeading.locator("xpath=../..")
    .getByTitle("أرشفة المنطقة بمسح شامل (سوبر أدمن)").click();
  const archiveZoneModal = page.getByRole("dialog", { name: /أرشفة منطقة/ });
  await archiveZoneModal.getByPlaceholder("اكتب اسم المنطقة هنا...").fill(renamedUiZone);
  const archivedZone = page.waitForResponse(r => new URL(r.url()).pathname.startsWith(
    "/dispatch/zones/") && r.request().method() === "DELETE");
  await archiveZoneModal.getByRole("button", { name: /تأكيد المسح الشامل/ }).click();
  expect((await archivedZone).status()).toBe(200);
  await page.getByRole("button", { name: /الأرشيف/ }).first().click();
  const zoneBin = page.getByRole("dialog", { name: /الأرشيف \(المناطق المحذوفة\)/ });
  await expect(zoneBin.getByText(renamedUiZone)).toBeVisible();
  const restoredZone = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(
    "/restore") && r.request().method() === "PUT");
  await zoneBin.getByRole("button", { name: /استعادة المنطقة ومحلاتها/ }).click();
  expect((await restoredZone).status()).toBe(200);
  await expect(zoneBin).not.toBeVisible();

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
       zoneId: state.otherZoneId, origin: API });
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

  // Status-only transitions never move Warehouse/Vehicle physical custody.
  await page.reload();
  const active = page.locator(".dispatch-route-row").first();
  await expect(active.getByRole("button", { name: "إيقاف مؤقت" })).toBeEnabled();
  await active.getByRole("button", { name: "إيقاف مؤقت" }).click();
  const stopDialog = page.getByRole("dialog", { name: "إيقاف المنطقة" });
  await expect(stopDialog).toBeVisible();
  const stopped = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await stopDialog.getByRole("button", { name: "تأكيد", exact: true }).click();
  expect((await stopped).status()).toBe(200);
  const waiting = page.locator(".dispatch-route-row").first();
  await expect(waiting.getByRole("button", { name: "متابعة الحمولة" })).toBeVisible();

  const postponed = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await waiting.getByRole("button", { name: /تأجيل المنطقة/ }).click();
  expect((await postponed).status()).toBe(200);
  await page.getByRole("button", { name: /عرض المؤجل|Show postponed/ }).click();
  const postponedDialog = page.getByRole("dialog", { name: /المناطق المؤجلة|Postponed routes/ });
  await expect(postponedDialog.locator("tbody tr")).toHaveCount(1);
  // This D08 fixture is frozen V1 rev1: no current M02 execution period.
  // Preserve the real legacy Restore path only for rev1; canonical route
  // fixtures must use the separate signed M02 RESUME with accepted custody.
  const legacyRestore = postponedDialog.getByRole("button", { name: /^(استعادة|Restore)$/ });
  await expect(legacyRestore).toBeVisible();
  await expect(postponedDialog.getByRole("button", {
    name: /اختيار واستئناف|Select and resume/,
  })).toHaveCount(0);
  const restored = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await legacyRestore.click();
  expect((await restored).status()).toBe(200);
  await postponedDialog.locator(".app-modal-header button").click();
  await expect(postponedDialog).not.toBeVisible();

  // Closing this original rev1 route must use its own legacy status writer,
  // never an unsigned canonical lifecycle command.
  const toClose = page.locator(".dispatch-route-row").first();
  await expect(toClose.getByRole("button", { name: "إغلاق خط السير" })).toBeVisible();
  await toClose.getByRole("button", { name: "إغلاق خط السير" }).click();
  const closingDialog = page.getByRole("dialog", { name: "تأكيد إغلاق خط السير" });
  await expect(closingDialog).toBeVisible();
  const closed = page.waitForResponse(r => new URL(r.url()).pathname === routeStatus &&
    r.request().method() === "PUT");
  await closingDialog.getByRole("button", { name: "تأكيد", exact: true }).click();
  expect((await closed).status()).toBe(200);
  await expect(page.locator(".dispatch-route-row")).toHaveCount(0);
  const custody = await page.evaluate(async ({ id, origin }) => {
    const response = await fetch(origin + "/dispatch/inventory/" + id, {
      headers: { Authorization: "Bearer " + localStorage.getItem("admin_token") },
    });
    return { status: response.status, data: await response.json() };
  }, { id: state.vehicleId, origin: API });
  expect(custody.status).toBe(200);
  const vehicleProduct = custody.data.find((line: { product_id: string }) =>
    String(line.product_id) === String(state.variantId));
  expect(Number(vehicleProduct?.current_base_quantity)).toBe(21);

  // Actual Dashboard Launch UI on the freshly CLOSED route's assets, with D11
  // live commercial preflight and original D07 request identity; no mocked wire.
  await page.getByRole("tab", { name: /إطلاق خط جديد/ }).click();
  const init = await page.evaluate(async origin => {
    const reply = await fetch(origin + "/dispatch/init", {
      headers: { Authorization: "Bearer " + localStorage.getItem("admin_token") },
    });
    if (!reply.ok) throw new Error("Authorized Dispatch init failed: " + reply.status);
    return reply.json();
  }, API);
  const choices = [
    init.zones.find((x: { id: string }) => x.id === String(state.zoneId))?.name,
    init.drivers.find((x: { id: string }) => x.id === String(state.driverId))?.name,
    init.vehicles.find((x: { id: string }) => x.id === String(state.vehicleId))?.label,
    init.warehouses.find((x: { id: string }) => x.id === String(state.warehouseId))?.label,
  ];
  expect(choices.every(Boolean)).toBe(true);
  const selectors = page.locator(".dispatch-launch-config > .relative.mt-2");
  await expect(selectors).toHaveCount(4);
  // Warehouse-first is deliberate: changing physical source invalidates all
  // previous Zone/Representative/Vehicle selections and their stock evidence.
  for (const index of [3, 0, 1, 2]) {
    await selectors.nth(index).locator("button").first().click();
    await selectors.nth(index).getByRole("button", { name: choices[index], exact: true }).click();
    await expect(selectors.nth(index).locator("button").first()).toContainText(choices[index]);
  }
  const readiness = page.getByTestId("d11-commercial-preflight");
  // D11 renders compact visible "Verified", retaining the complete business
  // readiness statement as its accessible aria-label. Prove BOTH contracts.
  const readinessStatus = readiness.getByRole("status");
  await expect(readinessStatus).toHaveAttribute("aria-label",
    "Checks passed — launch requirements are currently met.", { timeout: 30000 });
  await expect(readinessStatus).toContainText("Verified");
  const target = page.locator("#route-base-" + state.variantId);
  await expect(target).toBeEnabled({ timeout: 30000 });
  await target.fill("21");
  const realLaunch = page.waitForResponse(r => new URL(r.url()).pathname === "/dispatch/route"
    && r.request().method() === "POST");
  await page.getByRole("button", { name: "Confirm and launch route" }).click();
  const launchReceipt = await realLaunch;
  expect(launchReceipt.status()).toBe(201);
  const launched = await launchReceipt.json();
  expect(String(launched.route_id)).not.toBe(String(state.routeId));
  const finalCustody = await page.evaluate(async ({ id, origin }) => {
    const response = await fetch(origin + "/dispatch/inventory/" + id, {
      headers: { Authorization: "Bearer " + localStorage.getItem("admin_token") },
    });
    return { status: response.status, data: await response.json() };
  }, { id: state.vehicleId, origin: API });
  expect(finalCustody.status).toBe(200);
  expect(Number(finalCustody.data.find((x: { product_id: string }) =>
    String(x.product_id) === String(state.variantId))?.current_base_quantity)).toBe(21);

  // The existing Operations workflow, not Dispatch, owns settlement.
  const operations = page.waitForResponse(r => new URL(r.url()).pathname ===
    "/admin/sessions/today" && r.request().method() === "GET");
  await page.goto("/");
  expect((await operations).status()).toBe(200);

  writeFileSync(info.outputPath("d08-real-wire.json"), JSON.stringify({
    backend: state.confirmed, browser: {
      zoneCreate: true, routeActivate: true, blockedActiveShopMove: true,
      vehicleAdjust: true, routeActiveWaitingPostponedRestoredClosed: true,
      operationsSettlementHandoff: true, actualDashboardLaunchAndD11Preflight: true,
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
