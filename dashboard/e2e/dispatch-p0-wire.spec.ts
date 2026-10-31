import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "playwright/test";

const API = "http://127.0.0.1:4174";
const state = JSON.parse(readFileSync(process.env.WANASAH_DISPATCH_P0_WIRE_STATE!, "utf8"));
const expectedStatus = "/dispatch/route/" + state.routeId + "/status";
const expectedAdjust = "/dispatch/route/" + state.routeId + "/adjust_inventory";

function witness(phase: "status" | "adjust" | "replay") {
  const output = execFileSync(process.env.PYTHON || "python",
    [resolve("../wa_backend/tests/dispatch_p0_wire_fixture.py")], {
      encoding: "utf8", env: { ...process.env, WANASAH_DISPATCH_P0_VERIFY_PHASE: phase },
    });
  expect(output).toContain("DISPATCH_BROWSER_WIRE_" + phase.toUpperCase() + "=PASS");
}

test("built Dashboard → actual FastAPI bearer HTTP → PostgreSQL16 never mutates stock for route-only changes", async ({ page }, info) => {
  test.setTimeout(120_000);
  const requests: Array<{ path: string; body: unknown; response: number }> = [];
  page.on("response", async response => {
    const path = new URL(response.url()).pathname;
    if (![expectedStatus, expectedAdjust].includes(path) || response.request().method() !== "PUT") return;
    requests.push({ path, body: response.request().postDataJSON(), response: response.status() });
  });
  await page.goto("/login");
  await page.evaluate(() => localStorage.setItem("wanasah.language", "en"));
  await page.reload();
  await page.locator("#company-code").fill(state.credentials.code);
  await page.locator("#username").fill(state.credentials.username);
  await page.locator("#password").fill(state.credentials.password);
  await Promise.all([
    page.waitForURL(u => u.pathname !== "/login"),
    page.locator('button[type="submit"]').click(),
  ]);
  await page.goto("/dispatch");
  const row = page.locator(".dispatch-route-row").first();
  await expect(row).toBeVisible();
  const statusButton = row.getByRole("button", { name: /متابعة الحمولة|استئناف نفس الخط/ });
  await expect(statusButton).toBeEnabled();
  await statusButton.click();
  const routeModal = page.getByRole("dialog");
  await expect(routeModal).toBeVisible();
  const activated = page.waitForResponse(r =>
    new URL(r.url()).pathname === expectedStatus && r.request().method() === "PUT");
  await routeModal.getByRole("button", { name: "Confirm route status and assignment" }).click();
  const activation = await activated;
  expect(activation.status()).toBe(200);
  const actualBody = activation.request().postDataJSON();
  expect(actualBody).toMatchObject({ status: "active", driverId: String(state.driverId),
    vehicleId: String(state.vehicleId) });
  expect(actualBody).not.toHaveProperty("inventory");
  witness("status");

  // Prove the *same production HTTP endpoint* refuses both legacy absolute
  // targets and empty inventory maps, regardless of browser payload behavior.
  for (const inventory of [{ [state.variantId]: 3 }, {}]) {
    const denied = await page.evaluate(async ({ endpoint, target, origin }) => {
      const response = await fetch(origin + endpoint, {
        method: "PUT",
        headers: { Authorization: "Bearer " + localStorage.getItem("admin_token"),
          "Content-Type": "application/json" },
        body: JSON.stringify({ status: "active", inventory: target }),
      });
      return { status: response.status, body: await response.json(),
        requestId: response.headers.get("x-request-id") };
    }, { endpoint: expectedStatus, origin: API, target: inventory });
    expect(denied.status).toBe(409);
    expect(denied.body.error.code).toBe("DISPATCH_ROUTE_STATUS_INVENTORY_FORBIDDEN");
    expect(denied.requestId).toBeTruthy();
    witness("status");
  }

  // User opens the *real* current Vehicle's Adjust Load dialog after route
  // activation; only explicit reviewed +1 base can post physical movement.
  const current = page.locator(".dispatch-route-row").first();
  await expect(current.getByRole("button", { name: "تعديل الحمولة" })).toBeEnabled();
  await current.getByRole("button", { name: "تعديل الحمولة" }).click();
  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible();
  const input = modal.getByRole("spinbutton").first();
  await expect(input).toBeEnabled();
  await input.fill("1");
  await modal.getByRole("button", { name: "Review changes" }).click();
  const saved = page.waitForResponse(r =>
    new URL(r.url()).pathname === expectedAdjust && r.request().method() === "PUT");
  await modal.getByRole("button", { name: "Confirm adjustment" }).click();
  const result = await saved;
  expect(result.status()).toBe(200);
  expect((await result.json()).mode).toBe("DIRECT");
  const adjustmentBody = result.request().postDataJSON();
  const sentHeaders = result.request().headers();
  expect(sentHeaders["x-dispatch-expected-vehicle-id"]).toBe(String(state.vehicleId));
  expect(sentHeaders["x-dispatch-expected-source-warehouse-id"]).toBe(String(state.warehouseId));
  expect(adjustmentBody.deltas).toEqual([{ product_id: state.variantId, delta_base: "1" }]);
  expect(adjustmentBody.context).toMatchObject({
    version: "ADJUST_LOAD_CONTEXT_V2",
    vehicle_id: state.vehicleId,
    source_warehouse_id: state.warehouseId,
    work_session_id: null,
  });
  expect(adjustmentBody.context.route_context_revision).toBeGreaterThan(0);
  expect(adjustmentBody.request_id).toMatch(/^[0-9a-f-]{36}$/i);
  witness("adjust");

  const replay = await page.evaluate(async ({ endpoint, body, origin }) => {
    const response = await fetch(origin + endpoint, {
      method: "PUT",
      headers: { Authorization: "Bearer " + localStorage.getItem("admin_token"),
        "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { status: response.status, body: await response.json() };
  }, { endpoint: expectedAdjust, body: adjustmentBody, origin: API });
  expect(replay.status).toBe(200);
  expect(replay.body.mode).toBe("DIRECT");
  witness("replay");

  // Pre-cutover durable route-only command: verify NOT_CONFIRMED first, then
  // explicitly persist CANCELLED through the real Dashboard/FastAPI/PG16 path.
  const legacy = await page.evaluate(async (seed) => {
    const payload = { deltas: [{ product_id: seed.variantId, delta_base: "8" }] };
    const canonicalize = (value: unknown): unknown => {
      if (Array.isArray(value)) return value.map(canonicalize);
      if (value !== null && typeof value === "object") {
        return Object.fromEntries(Object.entries(value as Record<string, unknown>)
          .filter(([, item]) => item !== undefined)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, item]) => [key, canonicalize(item)]));
      }
      return value;
    };
    const bytes = new TextEncoder().encode(JSON.stringify(canonicalize(payload)));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const payloadHash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
    const requestId = crypto.randomUUID();
    const scope = `wanasah:durable:v1:${seed.companyId}:${seed.principalId}:dispatch-adjust-base:${seed.routeId}`;
    localStorage.setItem(scope, JSON.stringify({
      kind: "command", requestId, payloadHash, payload, createdAt: Date.now(),
    }));
    return { requestId, scope, payload };
  }, state);

  await page.reload();
  const recoveryRow = page.locator(".dispatch-route-row").first();
  await expect(recoveryRow.getByRole("button", { name: "تعديل الحمولة" })).toBeEnabled();
  await recoveryRow.getByRole("button", { name: "تعديل الحمولة" }).click();
  const recoveryModal = page.getByRole("dialog");
  await expect(recoveryModal).toContainText("Unresolved earlier load adjustment");
  await expect(recoveryModal).not.toContainText(legacy.requestId);

  const verifiedResponse = page.waitForResponse(r =>
    new URL(r.url()).pathname === expectedAdjust + "/recovery" && r.request().method() === "POST");
  await recoveryModal.getByRole("button", { name: "Verify original request outcome (read-only)" }).click();
  const verifiedResult = await verifiedResponse;
  expect(verifiedResult.status()).toBe(200);
  expect((await verifiedResult.json()).state).toBe("NOT_CONFIRMED");
  await expect(recoveryModal).toContainText("The server verified no completed or pending evidence");

  await recoveryModal.getByRole("button", { name: "Permanently cancel old request" }).click();
  const confirmCancel = recoveryModal.getByRole("alertdialog", { name: "Confirm permanent cancellation" });
  await expect(confirmCancel).toBeVisible();
  const cancelledResponse = page.waitForResponse(r =>
    new URL(r.url()).pathname === expectedAdjust + "/recovery/cancel" && r.request().method() === "POST");
  await confirmCancel.getByRole("button", { name: "Confirm permanent cancellation" }).click();
  const cancelledResult = await cancelledResponse;
  expect(cancelledResult.status()).toBe(200);
  expect((await cancelledResult.json()).state).toBe("CANCELLED");
  expect(await page.evaluate(scope => localStorage.getItem(scope), legacy.scope)).toBeNull();
  witness("cancel");

  const late = await page.evaluate(async ({ endpoint, requestId, payload, origin }) => {
    const response = await fetch(origin + endpoint, {
      method: "PUT",
      headers: { Authorization: "Bearer " + localStorage.getItem("admin_token"),
        "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, ...payload }),
    });
    return { status: response.status, body: await response.json() };
  }, { endpoint: expectedAdjust, requestId: legacy.requestId, payload: legacy.payload, origin: API });
  expect(late.status).toBe(409);
  expect(late.body.error.code).toBe("DISPATCH_ADJUSTMENT_CANCELLED");
  witness("cancel");
  writeFileSync(info.outputPath("dispatch-p0-real-wire.json"),
    JSON.stringify({ routeId: state.routeId, requests, activation: actualBody,
      adjust: adjustmentBody, replay }, null, 2));
  expect(requests.some(r => r.path === expectedStatus && r.response === 200)).toBe(true);
  expect(requests.some(r => r.path === expectedAdjust && r.response === 200)).toBe(true);
  expect(page.locator("html")).toHaveAttribute("dir", "ltr");
});
