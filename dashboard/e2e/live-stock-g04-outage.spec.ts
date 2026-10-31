import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page, type Route } from "playwright/test";

import { API, api, item, login, state } from "./live-stock-operational.support";

const DB_CONTAINER = process.env.WANASAH_G04_DB_CONTAINER || "live-stock-g04-pg";
const PYTHON = process.env.PYTHON || "python";

if (process.env.WANASAH_G04_GATE !== "1") {
  throw new Error("G04 real outage browser proof requires its isolated PG16 workflow");
}

function support(action: "fingerprint" | "revoke" | "restore" | "api-stop" | "api-start") {
  const output = execFileSync(
    PYTHON,
    [resolve(process.cwd(), "../wa_backend/tests/live_stock_g04_outage_support.py"), action],
    { encoding: "utf8", env: process.env },
  ).trim();
  if (action === "fingerprint") return JSON.parse(output) as Record<string, unknown>;
  const marker = {
    revoke: "G04_REVOKE PASS",
    restore: "G04_RESTORE PASS",
    "api-stop": "G04_API_STOP PASS",
    "api-start": "G04_API_START PASS",
  }[action];
  expect(output).toContain(marker);
  return output;
}

function stopDatabase() {
  execFileSync("docker", ["stop", "-t", "1", DB_CONTAINER], { encoding: "utf8" });
}

function startDatabase() {
  const running = execFileSync(
    "docker",
    ["inspect", "-f", "{{.State.Running}}", DB_CONTAINER],
    { encoding: "utf8" },
  ).trim();
  if (running !== "true") {
    execFileSync("docker", ["start", DB_CONTAINER], { encoding: "utf8" });
  }
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      execFileSync("docker", [
        "exec", DB_CONTAINER, "pg_isready", "-U", "g04_admin",
        "-d", "wanasah_no_lot_contract_test", "-p", "55439",
      ], { stdio: "ignore" });
      return;
    } catch {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
    }
  }
  throw new Error("PostgreSQL16 did not recover");
}

async function waitReady(page: Page) {
  await expect.poll(async () => {
    try {
      return (await page.request.get(API + "/ready")).status();
    } catch {
      return 0;
    }
  }, { timeout: 20_000 }).toBe(200);
}

async function commitForeignDashboardSession(page: Page) {
  const credentials = state.credentials.foreign as { code: string; username: string; password: string };
  if (!page.url().startsWith("http://127.0.0.1:4173/")) {
    await page.goto("http://127.0.0.1:4173/");
  }
  return page.evaluate(async ({ origin, credentials, warehouse }) => {
    const response = await fetch(origin + "/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company_code: credentials.code,
        username: credentials.username,
        password: credentials.password,
      }),
    });
    const data = await response.json() as Record<string, unknown>;
    if (!response.ok) throw new Error("Foreign real login failed: " + response.status);
    const companyId = data.company_id;
    const principalId = data.principal_id;
    const backofficeUserId = data.backoffice_user_id;
    if (
      typeof data.token !== "string" || !data.token ||
      typeof data.refresh_token !== "string" || !data.refresh_token ||
      typeof companyId !== "number" || !Number.isSafeInteger(companyId) || companyId <= 0 ||
      typeof principalId !== "number" || !Number.isSafeInteger(principalId) || principalId <= 0 ||
      typeof backofficeUserId !== "number" || !Number.isSafeInteger(backofficeUserId) || backofficeUserId <= 0 ||
      data.channel !== "DASHBOARD" || data.principal_type !== "BACKOFFICE"
    ) throw new Error("Foreign login returned invalid Dashboard identity");

    localStorage.setItem("wanasah:auth-session:generation", crypto.randomUUID());
    localStorage.setItem("admin_token", data.token);
    localStorage.setItem("refresh_token", data.refresh_token);
    localStorage.setItem("company_id", String(companyId));
    localStorage.setItem("principal_id", String(principalId));
    localStorage.setItem("backoffice_user_id", String(backofficeUserId));
    localStorage.removeItem("driver_id");
    if (typeof data.company_code === "string") localStorage.setItem("company_code", data.company_code);
    localStorage.setItem("inventory_selected_location:" + companyId, String(warehouse));
    localStorage.setItem("inventory_active_tab:" + companyId, "live");
    return { companyId, principalId, backofficeUserId };
  }, { origin: API, credentials, warehouse: state.foreignWarehouse });
}

async function retryStale(page: Page) {
  const stale = page.locator('[data-cp13-state="stale"]');
  await expect(stale).toBeVisible();
  const fresh = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "GET" &&
      url.pathname === "/warehouse/inventory/cursor" &&
      response.status() === 200;
  });
  await stale.getByRole("button").click();
  await fresh;
  await expect(stale).toHaveCount(0);
}

test("G04 real outage and fail-closed recovery on built Dashboard/FastAPI/PG16", async ({ page, browser }, info) => {
  test.setTimeout(240_000);
  const before = support("fingerprint");
  let revoked = false;

  try {
    await login(page, "owner");
    const ownerRow = item(page, state.mainName);
    await expect(ownerRow).toBeVisible();
    await expect(ownerRow.locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
    await expect(ownerRow.locator('[data-cp13-quantity="vehicle"]')).toContainText("4");
    const initialText = await ownerRow.innerText();

    stopDatabase();
    const serverFailure = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/warehouse/inventory/cursor" && response.status() >= 500;
    });
    await page.locator(".live-stock-context-refresh").click();
    const failureResponse = await serverFailure;
    expect(failureResponse.status()).toBeGreaterThanOrEqual(500);
    await expect(page.locator('[data-cp13-state="stale"]')).toBeVisible();
    await expect(ownerRow).toBeVisible();
    expect(await ownerRow.innerText()).toBe(initialText);
    await expect(page.locator('[data-cp13-state="empty"]')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath("g04-real-db-outage-stale-not-zero.png"), fullPage: true });

    startDatabase();
    await waitReady(page);
    await retryStale(page);
    await expect(ownerRow.locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
    await expect(ownerRow.locator('[data-cp13-quantity="vehicle"]')).toContainText("4");

    let dropped = false;
    const dropOnce = async (route: Route) => {
      if (!dropped) {
        dropped = true;
        await route.abort("failed");
        return;
      }
      await route.continue();
    };
    await page.route(API + "/warehouse/inventory/cursor*", dropOnce);
    await page.locator(".live-stock-context-refresh").click();
    await expect.poll(() => dropped).toBe(true);
    await expect(page.locator('[data-cp13-state="stale"]')).toBeVisible();
    await expect(ownerRow).toBeVisible();
    expect(await ownerRow.innerText()).toBe(initialText);
    await page.unroute(API + "/warehouse/inventory/cursor*", dropOnce);
    await retryStale(page);

    // Actual HTTP service unavailability: terminate the genuine FastAPI process,
    // refresh while the already-visible page cannot connect, then restart that
    // same application and require a fresh successful read before freshness returns.
    const failedCursor = page.waitForEvent("requestfailed", (request) => {
      const url = new URL(request.url());
      return request.method() === "GET" &&
        url.origin === API &&
        url.pathname === "/warehouse/inventory/cursor";
    });
    support("api-stop");
    await page.locator(".live-stock-context-refresh").click();
    const unavailableRequest = await failedCursor;
    expect(unavailableRequest.failure()?.errorText).toBeTruthy();
    await expect(page.locator('[data-cp13-state="stale"]')).toBeVisible();
    await expect(ownerRow).toBeVisible();
    expect(await ownerRow.innerText()).toBe(initialText);
    await expect(page.locator('[data-cp13-state="empty"]')).toHaveCount(0);
    await page.screenshot({
      path: info.outputPath("g04-real-http-unavailable-stale-not-zero.png"),
      fullPage: true,
    });

    support("api-start");
    await waitReady(page);
    await retryStale(page);
    await expect(ownerRow.locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
    await expect(ownerRow.locator('[data-cp13-quantity="vehicle"]')).toContainText("4");

    const restricted = await browser.newContext({
      baseURL: "http://127.0.0.1:4173",
      viewport: { width: 1360, height: 900 },
    });
    const reader = await restricted.newPage();
    try {
      await login(reader, "reader");
      await expect(item(reader, state.mainName)).toBeVisible();
      await reader.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      const dialog = reader.locator('[role="dialog"][aria-modal="true"]');
      const first = dialog.locator("article").filter({ hasText: "OP-FIRST" });
      await expect(first).toBeVisible();

      let releaseLate!: () => void;
      let capturedLate!: () => void;
      let deliveredLate!: () => void;
      const release = new Promise<void>((resolve) => { releaseLate = resolve; });
      const captured = new Promise<void>((resolve) => { capturedLate = resolve; });
      const delivered = new Promise<void>((resolve) => { deliveredLate = resolve; });
      let held = false;
      const sourceHandler = async (route: Route) => {
        if (!held) {
          held = true;
          const genuine = await route.fetch();
          expect(genuine.status()).toBe(200);
          capturedLate();
          await release;
          await route.fulfill({ response: genuine });
          deliveredLate();
          return;
        }
        await route.continue();
      };
      await reader.route(API + "/warehouse/inventory/*/batches/*/source*", sourceHandler);
      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      await captured;

      support("revoke");
      revoked = true;
      const denied = reader.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/warehouse/inventory/cursor" && response.status() === 403;
      });
      await reader.locator(".live-stock-context-refresh").evaluate((element: HTMLElement) => element.click());
      await denied;
      await expect(item(reader, state.mainName)).toHaveCount(0);

      releaseLate();
      await delivered;
      await expect(dialog).toHaveCount(0);
      await expect(reader.getByText(state.mainName)).toHaveCount(0);
      await reader.screenshot({ path: info.outputPath("g04-revoked-late-response-stays-closed.png"), fullPage: true });

      for (const path of [
        "/warehouse/inventory/cursor?location_id=" + state.warehouse,
        "/warehouse/inventory/" + state.mainId + "/batches?location_id=" + state.warehouse,
        "/warehouse/inventory/" + state.mainId + "/batches/" + state.firstBatch + "/source?location_id=" + state.warehouse,
      ]) {
        const response = await api(reader, path);
        expect(response.status).toBe(403);
        expect(JSON.stringify(response.body)).not.toContain(state.mainName);
        expect(JSON.stringify(response.body)).not.toContain(state.expected.value);
      }
      await reader.unroute(API + "/warehouse/inventory/*/batches/*/source*", sourceHandler);
    } finally {
      await restricted.close();
    }

    support("restore");
    revoked = false;

    const switched = await browser.newContext({
      baseURL: "http://127.0.0.1:4173",
      viewport: { width: 1360, height: 900 },
    });
    const aTab = await switched.newPage();
    const bTab = await switched.newPage();
    try {
      await login(aTab, "reader");
      await expect(item(aTab, state.mainName)).toBeVisible();

      const abortFreshB = async (route: Route) => route.abort("failed");
      await aTab.route(API + "/inventory/access/me*", abortFreshB);
      await aTab.route(API + "/warehouse/inventory/cursor*", abortFreshB);
      const foreign = await commitForeignDashboardSession(bTab);

      await expect(item(aTab, state.mainName)).toHaveCount(0);
      expect(await aTab.evaluate(() => localStorage.getItem("company_id"))).toBe(String(foreign.companyId));
      await aTab.screenshot({ path: info.outputPath("g04-session-switch-network-loss-no-a-cache.png"), fullPage: true });

      await aTab.unroute(API + "/inventory/access/me*", abortFreshB);
      await aTab.unroute(API + "/warehouse/inventory/cursor*", abortFreshB);
      await aTab.reload();
      const own = await api(aTab, "/warehouse/inventory/cursor?location_id=" + state.foreignWarehouse);
      expect(own.status).toBe(200);
      expect(JSON.stringify(own.body)).not.toContain(state.mainName);
      const cross = await api(aTab, "/warehouse/inventory/cursor?location_id=" + state.warehouse);
      expect(cross.status).toBe(404);
      await expect(aTab.getByText(state.mainName)).toHaveCount(0);
    } finally {
      await switched.close();
    }

    const after = support("fingerprint");
    expect(after).toEqual(before);
  } finally {
    try {
      startDatabase();
    } catch {
      // The workflow's final readiness step reports any real recovery failure.
    }
    if (revoked) support("restore");
  }
});
