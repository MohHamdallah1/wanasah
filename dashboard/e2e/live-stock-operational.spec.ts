import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page, type Route } from "playwright/test";
import { visualCases } from "./live-stock-ux-closure.fixtures";
import { API, api, command, delay, item, login, record, shot, state, stock } from "./live-stock-operational.support";
import { detailFreshness, policyAndScope, searchFailures } from "./live-stock-operational.journey";


function physicalCommand(action: "setup" | "grant" | "load") {
  const output = execFileSync(process.env.PYTHON || "python",
    [resolve("e2e/live-stock-physical-custody.fixture.py"), action],
    { encoding: "utf8", env: process.env });
  expect(output).toContain("PHYSICAL_CONSUMER_COMMAND PASS " + action);
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
    ) throw new Error("Foreign real login returned an invalid canonical Dashboard identity");

    // Mirror Login.tsx's canonical cross-tab commit using the genuine FastAPI tokens.
    localStorage.setItem("wanasah:auth-session:generation", crypto.randomUUID());
    localStorage.setItem("admin_token", data.token);
    localStorage.setItem("refresh_token", data.refresh_token);
    localStorage.setItem("company_id", String(companyId));
    localStorage.setItem("principal_id", String(principalId));
    localStorage.setItem("backoffice_user_id", String(backofficeUserId));
    localStorage.removeItem("driver_id");
    if (typeof data.company_code === "string") localStorage.setItem("company_code", data.company_code);
    if (typeof data.display_name === "string") localStorage.setItem("admin_name", data.display_name);
    localStorage.setItem("inventory_selected_location:" + companyId, String(warehouse));
    localStorage.setItem("inventory_active_tab:" + companyId, "live");
    return { companyId, principalId, backofficeUserId };
  }, { origin: API, credentials, warehouse: state.foreignWarehouse });
}

test("remaining V1 operational clauses on production Dashboard and real FastAPI/PG16", async ({ page, browser }, info) => {
  test.setTimeout(240_000);
  const readerLog = record(page);
  let owner: Awaited<ReturnType<typeof browser.newContext>> | undefined;
  try {
    expect(state.expected).toMatchObject({ onHand: "1000", value: "2200", reserved: "16",
      available: "976", afterReserved: "24", afterAvailable: "968", stockTotal: 109, alerts: 1 });
    expect(state.date).not.toBe(state.browserDate);
    await test.step("one inventory-only warehouse among211; authoritative flags, currency/UOM/company date", async () => {
      await login(page, "reader");
      await policyAndScope(page, info, readerLog);
    });
    await test.step("open dialog refresh, two actual batches, source error/retry and canonical reservation", async () => {
      await detailFreshness(page, info);
    });
    await test.step("independent real-server validation failures, cursor retry and selected-family identity", async () => {
      await searchFailures(page, readerLog);
    });
    owner = await browser.newContext({ baseURL: "http://127.0.0.1:4173",
      viewport: { width: 1440, height: 900 }, timezoneId: "Pacific/Honolulu" });
    const op = await owner.newPage();
    const ownerLog = record(op);
    await login(op, "owner");
    await test.step("warehouse change resets filters/cursors under real scope", async () => {
      const searchRead = op.waitForResponse(r => r.request().method() === "GET" && r.status() === 200 &&
        new URL(r.url()).pathname === "/warehouse/inventory/cursor" &&
        new URL(r.url()).searchParams.get("search") === "Paging");
      await stock(op).getByRole("searchbox").first().fill("Paging");
      await searchRead;
      await expect(item(op, "Paging Item 001")).toBeVisible();
      await stock(op).locator(".live-stock-context-select").selectOption(String(state.otherWarehouse));
      await expect(stock(op).getByRole("searchbox").first()).toHaveValue("");
      await stock(op).locator(".live-stock-filter-button").click();
      await op.locator(".live-stock-filter-option").filter({ hasText: "Stock in warehouse" }).click();
      await op.keyboard.press("Escape");
      await expect(item(op, "Paging Item 001")).toBeVisible();
      await expect(op.locator(".live-stock-row")).toHaveCount(1);
      await expect(item(op, "Paging Item 001").locator('[data-cp13-quantity="on-hand"]')).toContainText("2");
      const other = await api(op, "/warehouse/inventory/cursor?location_id=" + state.otherWarehouse + "&stock_state=on_hand");
      expect(other.status).toBe(200);
      expect(other.body.items.map((r: { id: number }) => r.id)).toEqual([state.pagingIds[0]]);
      expect(other.body.items[0].on_hand_quantity).toBe("2");
      await stock(op).locator(".live-stock-context-select").selectOption(String(state.warehouse));
      await expect(stock(op).getByRole("searchbox").first()).toHaveValue("");
      await expect(item(op, state.mainName)).toBeVisible();
    });
    await test.step("real responsive/locale/theme screenshots; bounded keyboard-reachable dock", async () => {
      for (const v of visualCases) {
        await op.setViewportSize({ width: v.width, height: v.height });
        await op.evaluate(locale => localStorage.setItem("wanasah.language", locale), v.locale);
        await op.reload();
        await expect(stock(op)).toBeVisible();
        await expect(item(op, state.mainName)).toBeVisible();
        await op.evaluate(theme => document.documentElement.classList.toggle("dark", theme === "dark"), v.theme);
        await expect(op.locator("html")).toHaveAttribute("dir", v.locale === "ar" ? "rtl" : "ltr");
        const rail = op.getByRole("tablist");
        const box = await rail.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(v.width + 1);
        expect(await op.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
        const selected = rail.getByRole("tab", { selected: true });
        await selected.focus();
        await op.keyboard.press(v.locale === "ar" ? "ArrowLeft" : "ArrowRight");
        await expect(rail.getByRole("tab").nth(1)).toBeFocused();
        await op.keyboard.press(v.locale === "ar" ? "ArrowRight" : "ArrowLeft");
        await expect(rail.getByRole("tab").first()).toBeFocused();
        await op.keyboard.press("End");
        const end = rail.getByRole("tab").last();
        await expect(end).toBeFocused();
        const endBox = await end.boundingBox();
        expect(endBox!.x).toBeGreaterThanOrEqual(box!.x - 1);
        expect(endBox!.x + endBox!.width).toBeLessThanOrEqual(box!.x + box!.width + 1);
        await op.keyboard.press("Home");
        await expect(rail.getByRole("tab").first()).toBeFocused();
        await expect(stock(op)).toBeVisible();
        expect(await rail.getByRole("tab").first().evaluate(e => {
          const style = getComputedStyle(e);
          return { style: style.outlineStyle, color: style.outlineColor, offset: style.outlineOffset };
        })).toEqual({ style: "solid", color: "rgb(2, 6, 23)", offset: "-4px" });
        await expect(item(op, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("125");
        await expect(item(op, state.mainName).locator('[data-cp13-quantity="available"]')).toContainText("121");
        await shot(op, info, "real-" + v.name + "-bounded-tabs");
      }
    });
    await test.step("leave/reenter another tab with no redundant Live Stock requests", async () => {
      await op.setViewportSize({ width: 1440, height: 900 });
      await op.evaluate(() => localStorage.setItem("wanasah.language", "en"));
      await op.reload();
      await expect(stock(op)).toBeVisible();
      await op.getByRole("tab", { name: "Batches & expiry", exact: true }).click();
      await expect(stock(op)).toHaveCount(0);
      await delay(op);
      const start = ownerLog.requests.length;
      // Actual sidebar navigation keeps the warm in-memory session alive.
      await op.locator(".operations-nav").getByRole("button", { name: "Products", exact: true }).click();
      await expect(op).toHaveURL(/\/products/);
      await op.locator(".operations-nav").getByRole("button", { name: "Inventory & Warehouse", exact: true }).click();
      await expect(op).toHaveURL(/\/inventory/);
      await expect(op.getByRole("tab", { name: "Batches & expiry", exact: true })).toHaveAttribute("aria-selected", "true");
      await delay(op);
      const liveReads = ownerLog.requests.slice(start).filter(u => [
        "/warehouse/inventory/cursor", "/warehouse/inventory/summary", "/warehouse/inventory/families",
      ].includes(new URL(u).pathname));
      expect(liveReads).toEqual([]);
      const resume = ownerLog.requests.length;
      await op.getByRole("tab", { name: "Live stock", exact: true }).click();
      await expect(item(op, state.mainName)).toBeVisible();
      await delay(op);
      expect(ownerLog.requests.slice(resume).filter(u => new URL(u).pathname === "/warehouse/inventory/cursor")).toHaveLength(1);
      expect(ownerLog.requests.slice(resume).filter(u => new URL(u).pathname === "/warehouse/inventory/summary")).toHaveLength(1);
    });
    await test.step("real movement cannot make delayed list, summary, batch and source one fresh snapshot", async () => {
      command("race-threshold");
      physicalCommand("setup");
      physicalCommand("grant");

      const initialList = op.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && response.status() === 200 &&
          url.pathname === "/warehouse/inventory/cursor" &&
          url.searchParams.get("location_id") === String(state.warehouse);
      });
      const initialSummary = op.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && response.status() === 200 &&
          url.pathname === "/warehouse/inventory/summary" &&
          url.searchParams.get("location_id") === String(state.warehouse);
      });
      await stock(op).locator(".live-stock-context-refresh").click();
      await Promise.all([initialList, initialSummary]);
      const thresholdSummary = await api(op,
        "/warehouse/inventory/summary?location_id=" + state.warehouse);
      expect(thresholdSummary.status).toBe(200);
      expect(thresholdSummary.body.alert_count).toBe(0);
      await expect(item(op, state.mainName).locator('[aria-label="Reached minimum stock"]')).toHaveCount(0);
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("125");
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="vehicle"]')).toContainText("0");

      await op.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      let dialog = op.locator('[role="dialog"][aria-modal="true"]');
      await expect(dialog).toContainText("OP-FIRST");
      let first = dialog.locator("article").filter({ hasText: "OP-FIRST" });

      type RaceKey = "list" | "summary" | "batch" | "source";
      const raceKeys: RaceKey[] = ["list", "summary", "batch", "source"];
      const captured = new Map<RaceKey, unknown>();
      const ready = new Map<RaceKey, Promise<void>>();
      const readyResolve = new Map<RaceKey, () => void>();
      const done = new Map<RaceKey, Promise<void>>();
      const doneResolve = new Map<RaceKey, () => void>();
      for (const key of raceKeys) {
        let resolveReady!: () => void;
        let resolveDone!: () => void;
        ready.set(key, new Promise<void>((resolve) => { resolveReady = resolve; }));
        done.set(key, new Promise<void>((resolve) => { resolveDone = resolve; }));
        readyResolve.set(key, resolveReady);
        doneResolve.set(key, resolveDone);
      }
      let releaseHeld!: () => void;
      const heldRelease = new Promise<void>((resolve) => { releaseHeld = resolve; });

      const raceHandler = async (route: Route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (request.method() !== "GET") {
          await route.continue();
          return;
        }
        let key: RaceKey | null = null;
        if (
          url.pathname === "/warehouse/inventory/cursor" &&
          url.searchParams.get("location_id") === String(state.warehouse)
        ) key = "list";
        else if (
          url.pathname === "/warehouse/inventory/summary" &&
          url.searchParams.get("location_id") === String(state.warehouse)
        ) key = "summary";
        else if (
          url.pathname === `/warehouse/inventory/${state.mainId}/batches` &&
          url.searchParams.get("location_id") === String(state.warehouse)
        ) key = "batch";
        else if (
          url.pathname === `/warehouse/inventory/${state.mainId}/batches/${state.firstBatch}/source` &&
          url.searchParams.get("location_id") === String(state.warehouse)
        ) key = "source";
        if (!key || captured.has(key)) {
          await route.continue();
          return;
        }

        const genuineOldResponse = await route.fetch();
        expect(genuineOldResponse.status()).toBe(200);
        captured.set(key, await genuineOldResponse.json());
        readyResolve.get(key)!();
        await heldRelease;
        try {
          await route.fulfill({ response: genuineOldResponse });
        } catch {
          // A scope change may abort the transport before Playwright can deliver
          // the already-captured response. The consumer must stay fail-closed in
          // both cooperative-abort and late-delivery cases.
        } finally {
          doneResolve.get(key)!();
        }
      };
      await op.route(API + "/warehouse/inventory/**", raceHandler);

      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      await ready.get("source");
      await op.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);

      await op.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      await ready.get("batch");
      dialog = op.locator('[role="dialog"][aria-modal="true"]');
      await op.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);

      await stock(op).locator(".live-stock-context-refresh").click();
      await Promise.all([ready.get("list")!, ready.get("summary")!]);

      const oldList = captured.get("list") as {
        items: Array<{ id: number; on_hand_quantity: string; vehicle_quantity: string | null }>;
      };
      const oldSummary = captured.get("summary") as { alert_count: number };
      const oldBatch = captured.get("batch") as {
        batches: Array<{ batch_id: number; on_hand_quantity: string }>;
      };
      const oldSource = captured.get("source") as {
        statuses: Array<{ stock_status: string; on_hand_quantity: string; reserved_quantity: string }>;
      };
      expect(oldList.items.find((row) => row.id === state.mainId)).toMatchObject({
        on_hand_quantity: "1000",
        vehicle_quantity: "0",
      });
      expect(oldSummary.alert_count).toBe(0);
      expect(oldBatch.batches.find((batch) => batch.batch_id === state.firstBatch)?.on_hand_quantity).toBe("800");
      expect(oldSource.statuses.find((status) => status.stock_status === "AVAILABLE")).toMatchObject({
        on_hand_quantity: "800",
        reserved_quantity: "24",
      });

      physicalCommand("load");

      const select = stock(op).locator(".live-stock-context-select");
      const otherRead = op.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && response.status() === 200 &&
          url.pathname === "/warehouse/inventory/cursor" &&
          url.searchParams.get("location_id") === String(state.otherWarehouse);
      });
      await select.selectOption(String(state.otherWarehouse));
      await otherRead;
      await expect(item(op, "Paging Item 001")).toBeVisible();

      const freshListPromise = op.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && response.status() === 200 &&
          url.pathname === "/warehouse/inventory/cursor" &&
          url.searchParams.get("location_id") === String(state.warehouse);
      });
      const freshSummaryPromise = op.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.request().method() === "GET" && response.status() === 200 &&
          url.pathname === "/warehouse/inventory/summary" &&
          url.searchParams.get("location_id") === String(state.warehouse);
      });
      await select.selectOption(String(state.warehouse));
      const [freshListResponse, freshSummaryResponse] =
        await Promise.all([freshListPromise, freshSummaryPromise]);
      const freshList = await freshListResponse.json() as {
        items: Array<{ id: number; on_hand_quantity: string; vehicle_quantity: string | null }>;
      };
      const freshSummary = await freshSummaryResponse.json() as { alert_count: number };
      expect(freshList.items.find((row) => row.id === state.mainId)).toMatchObject({
        on_hand_quantity: "968",
        vehicle_quantity: "32",
      });
      expect(freshSummary.alert_count).toBe(1);
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="vehicle"]')).toContainText("4");
      await expect(item(op, state.mainName).locator('[aria-label="Reached minimum stock"]')).toHaveCount(1);

      const freshBatchApi = await api(op,
        "/warehouse/inventory/" + state.mainId + "/batches?location_id=" + state.warehouse + "&limit=100");
      const freshFirstBatch = freshBatchApi.body.batches.find(
        (batch: { batch_id: number }) => batch.batch_id === state.firstBatch);
      expect(freshFirstBatch.on_hand_quantity).toBe("768");

      await op.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      dialog = op.locator('[role="dialog"][aria-modal="true"]');
      first = dialog.locator("article").filter({ hasText: "OP-FIRST" });
      await expect(first).toBeVisible();
      await expect(dialog).toContainText("independent reads, not one atomic snapshot");
      await expect(first.locator("dd").filter({ hasText: /^96 / })).toHaveCount(1);
      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      await expect(first).toContainText("not a complete physical-inventory total");
      const freshSourceApi = await api(op,
        "/warehouse/inventory/" + state.mainId + "/batches/" + state.firstBatch +
          "/source?location_id=" + state.warehouse);
      const freshAvailable = freshSourceApi.body.statuses.find(
        (status: { stock_status: string }) => status.stock_status === "AVAILABLE");
      expect(freshAvailable).toMatchObject({ on_hand_quantity: "768", reserved_quantity: "24" });
      await expect(first.locator('[id^="live-stock-source"] dd').filter({ hasText: /^96 / })).toHaveCount(1);

      releaseHeld();
      await Promise.all(raceKeys.map((key) => done.get(key)!));
      await delay(op);
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
      await expect(item(op, state.mainName).locator('[data-cp13-quantity="vehicle"]')).toContainText("4");
      await expect(item(op, state.mainName).locator('[aria-label="Reached minimum stock"]')).toHaveCount(1);
      await expect(first.locator("dd").filter({ hasText: /^96 / })).toHaveCount(1);
      await expect(first).toContainText("not a complete physical-inventory total");
      await op.unroute(API + "/warehouse/inventory/**", raceHandler);
      await op.keyboard.press("Escape");
      await shot(op, info, "real-movement-race-fresh-authority");
    });

    await test.step("cross-tab A→B rejects delayed A while fresh B authority follows physical custody truth", async () => {
      const transition = await browser.newContext({
        baseURL: "http://127.0.0.1:4173",
        viewport: { width: 1360, height: 900 },
      });
      const aTab = await transition.newPage();
      const bTab = await transition.newPage();
      try {
        await login(aTab, "reader");
        const physical = await api(
          aTab,
          "/warehouse/inventory/cursor?location_id=" + state.warehouse + "&search=OP-MULTI",
        );
        expect(physical.status).toBe(200);
        const physicalRow = physical.body.items.find((row: { id: number }) => row.id === state.mainId);
        expect(physicalRow).toMatchObject({
          on_hand_quantity: "968",
          total_quantity: "968",
          total_quantity_scope: "WAREHOUSE_PHYSICAL",
          vehicle_quantity: "32",
          vehicle_quantity_scope: "AUTHORIZED_LOCATIONS",
        });
        await expect(item(aTab, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
        await expect(item(aTab, state.mainName).locator('[data-cp13-quantity="vehicle"]')).toContainText("4");

        let releaseStaleA!: () => void;
        let staleACaptured!: () => void;
        let staleADelivered!: () => void;
        const staleARelease = new Promise<void>((resolveRelease) => { releaseStaleA = resolveRelease; });
        const staleAReady = new Promise<void>((resolveReady) => { staleACaptured = resolveReady; });
        const staleADone = new Promise<void>((resolveDone) => { staleADelivered = resolveDone; });
        let heldA = false;
        const staleAHandler = async (route: Route) => {
          const request = route.request();
          const url = new URL(request.url());
          if (
            !heldA &&
            request.method() === "GET" &&
            url.pathname === "/warehouse/inventory/cursor" &&
            url.searchParams.get("location_id") === String(state.warehouse)
          ) {
            heldA = true;
            const genuineAResponse = await route.fetch();
            expect(genuineAResponse.status()).toBe(200);
            staleACaptured();
            await staleARelease;
            await route.fulfill({ response: genuineAResponse });
            staleADelivered();
            return;
          }
          await route.continue();
        };
        await aTab.route(API + "/warehouse/inventory/cursor*", staleAHandler);

        let releaseBAuth!: () => void;
        let bAuthCaptured!: () => void;
        let bAuthDelivered!: () => void;
        const bAuthRelease = new Promise<void>((resolveRelease) => { releaseBAuth = resolveRelease; });
        const bAuthReady = new Promise<void>((resolveReady) => { bAuthCaptured = resolveReady; });
        const bAuthDone = new Promise<void>((resolveDone) => { bAuthDelivered = resolveDone; });
        let heldB = false;
        let bAuthBody: Record<string, unknown> | null = null;
        const bAuthHandler = async (route: Route) => {
          const response = await route.fetch();
          const body = await response.json() as Record<string, unknown>;
          if (!heldB && body.company_id !== state.companyId) {
            heldB = true;
            bAuthBody = body;
            bAuthCaptured();
            await bAuthRelease;
            await route.fulfill({ response });
            bAuthDelivered();
            return;
          }
          await route.fulfill({ response });
        };
        await aTab.route(API + "/inventory/access/me*", bAuthHandler);

        await stock(aTab).locator(".live-stock-context-refresh").click();
        await staleAReady;

        const foreignSession = await commitForeignDashboardSession(bTab);
        await bAuthReady;

        // ProtectedRoute/DashboardLayout must drop A before fresh B authorization finishes.
        await expect(item(aTab, state.mainName)).toHaveCount(0);
        expect(await aTab.evaluate(() => localStorage.getItem("company_id"))).toBe(String(foreignSession.companyId));

        releaseStaleA();
        await staleADone;
        await expect(item(aTab, state.mainName)).toHaveCount(0);

        const freshBCursor = aTab.waitForResponse((response) => {
          const url = new URL(response.url());
          return response.request().method() === "GET" &&
            response.status() === 200 &&
            url.pathname === "/warehouse/inventory/cursor" &&
            url.searchParams.get("location_id") === String(state.foreignWarehouse);
        });
        releaseBAuth();
        await bAuthDone;
        expect(bAuthBody).toMatchObject({
          company_id: foreignSession.companyId,
          principal_id: foreignSession.principalId,
          backoffice_user_id: foreignSession.backofficeUserId,
        });
        await freshBCursor;

        const bOwn = await api(aTab, "/warehouse/inventory/cursor?location_id=" + state.foreignWarehouse + "&limit=50");
        expect(bOwn.status).toBe(200);
        expect(JSON.stringify(bOwn.body)).not.toContain(state.mainName);
        const bCrossTenant = await api(aTab, "/warehouse/inventory/cursor?location_id=" + state.warehouse + "&limit=50");
        expect(bCrossTenant.status).toBe(404);
        expect(JSON.stringify(bCrossTenant.body)).not.toContain(state.mainName);
        await expect(item(aTab, state.mainName)).toHaveCount(0);

        await aTab.unroute(API + "/warehouse/inventory/cursor*", staleAHandler);
        await aTab.unroute(API + "/inventory/access/me*", bAuthHandler);
      } finally {
        await transition.close();
      }
    });
    await test.step("same-token source403 revokes already-open batch, list and costs", async () => {
      await page.setViewportSize({ width: 1360, height: 900 });
      await expect(item(page, state.mainName)).toBeVisible();
      await page.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      const dialog = page.locator('[role="dialog"][aria-modal="true"]');
      const first = dialog.locator("article").filter({ hasText: "OP-FIRST" });
      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      await expect(first).toContainText(/unattributed/i);
      const token = await page.evaluate(() => localStorage.getItem("admin_token"));
      command("revoke");
      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      const denial = page.waitForResponse(r => r.request().method() === "GET" && r.status() === 403 && r.url().includes("/source?"));
      await first.getByRole("button", { name: "Actionable Warehouse source and reservations" }).click();
      await denial;
      await expect(dialog).toHaveCount(0);
      await expect(stock(page)).toHaveCount(0);
      await expect(page.getByText(state.mainName)).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem("admin_token"))).toBe(token);
      for (const path of [
        "/warehouse/inventory/cursor?location_id=" + state.warehouse,
        "/warehouse/inventory/" + state.mainId + "/batches?location_id=" + state.warehouse,
        "/warehouse/inventory/" + state.mainId + "/batches/" + state.firstBatch + "/source?location_id=" + state.warehouse,
      ]) {
        const denied = await api(page, path);
        expect(denied.status).toBe(403);
        expect(JSON.stringify(denied.body)).not.toContain("2200");
      }
      await shot(page, info, "real-revoked-reader-no-stale-evidence");
    });
    await ownerLog.flush();
    expect(ownerLog.errors).toEqual([]);
    await readerLog.flush();
    expect(readerLog.errors).toEqual([]);
    ownerLog.persist(info, "owner-browser-evidence.json");
  } finally {
    readerLog.persist(info);
    await owner?.close();
  }
});
