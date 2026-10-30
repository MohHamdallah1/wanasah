import { expect, type Page, type TestInfo } from "playwright/test";
import { api, canon, command, delay, item, record, shot, state, stock, validationFault } from "./live-stock-operational.support";

export async function policyAndScope(p: Page, info: TestInfo, log: ReturnType<typeof record>) {
  await expect(item(p, state.mainName)).toBeVisible();
  const select = stock(p).locator(".live-stock-context-select");
  await expect(select.locator("option")).toHaveCount(1);
  await expect(select).toHaveValue(String(state.warehouse));
  expect(await p.locator("body").innerText()).not.toContain("Hidden Depot");
  expect(log.requests.filter(u => u.includes("/warehouse/setup-status"))).toHaveLength(0);
  const discovery = await api(p, "/warehouse/locations/selection?limit=100");
  expect(discovery.status).toBe(200);
  expect(discovery.body.items.map((x: { id: number }) => x.id)).toEqual([state.warehouse]);
  expect(discovery.body.has_more).toBe(false);
  const denied = await api(p, "/warehouse/inventory/cursor?location_id=" + state.otherWarehouse);
  expect(denied.status).toBe(403);
  const foreign = await api(p, "/warehouse/inventory/cursor?location_id=" + state.foreignWarehouse);
  expect(foreign.status).toBe(404);
  expect(JSON.stringify(foreign.body)).not.toContain("9.75");
  const live = await api(p, "/warehouse/inventory/cursor?location_id=" + state.warehouse + "&limit=50");
  const main = live.body.items.find((x: { id: number }) => x.id === state.mainId);
  expect(canon(main.on_hand_quantity)).toBe("1000");
  expect(canon(main.reserved_quantity)).toBe("16");
  expect(canon(main.available_for_sale_quantity)).toBe("976");
  expect(canon(main.unavailable_quantity)).toBe("8");
  expect(canon(main.last_purchase_cost)).toBe("24");
  expect(canon(main.average_cost_display)).toBe("17.6");
  expect(main.last_purchase_date).toBe(state.date);
  expect(main.display_factor_to_base).toBe("8");
  for (const id of state.policyIds) {
    expect(live.body.items.find((x: { id: number }) => x.id === id).is_low_stock).toBe(false);
  }
  expect(main.is_low_stock).toBe(true);
  const summary = await api(p, "/warehouse/inventory/summary?location_id=" + state.warehouse);
  expect(summary.body).toEqual({ stock_total: 109, alert_count: 1 });
  for (const width of [1360, 390]) {
    await p.setViewportSize({ width, height: 900 });
    const active = item(p, state.mainName);
    await expect(active.locator('[aria-label="Reached minimum stock"]')).toHaveCount(1);
    for (const name of state.policyNames) {
      await expect(item(p, name)).toBeVisible();
      await expect(item(p, name).locator('[aria-label="Reached minimum stock"]')).toHaveCount(0);
    }
    await expect(active.locator('[data-cp13-quantity="on-hand"]')).toContainText("125");
    await expect(active.locator('[data-cp13-quantity="available"]')).toContainText("122");
    await shot(p, info, width === 390 ? "restricted-one-warehouse-mobile" : "restricted-one-warehouse-desktop");
  }
  await p.setViewportSize({ width: 1360, height: 900 });
  const title = item(p, state.mainName).locator("td").nth(8).locator("[title]").first();
  await expect(title).toHaveText("JOD\u00a024");
  await expect(item(p, state.mainName).locator("td").nth(9)).toHaveText("JOD\u00a017.600");
  await expect(title).toHaveAttribute("title", /JOD.*Carton/);
  const date = await p.evaluate((date) => new Intl.DateTimeFormat("en", {
    year: "numeric", month: "2-digit", day: "2-digit", numberingSystem: "latn", timeZone: "UTC",
  }).format(new Date(date + "T00:00:00Z")), state.date);
  expect(await title.getAttribute("title")).toContain(date);
  await expect(stock(p).locator(".live-stock-context-count strong")).toHaveText("109");
  await stock(p).locator(".live-stock-filter-button").click();
  await p.locator(".live-stock-filter-option").filter({ hasText: "At or below minimum" }).click();
  await p.keyboard.press("Escape");
  await expect(p.locator(".live-stock-row")).toHaveCount(1);
  await expect(item(p, state.mainName)).toBeVisible();
  await stock(p).locator(".live-stock-filter-button").click();
  await p.locator(".live-stock-filter-reset").click();
  await p.keyboard.press("Escape");
  await expect(item(p, state.policyNames[0])).toBeVisible();
}

export async function detailFreshness(p: Page, info: TestInfo) {
  await p.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
  const dialog = p.getByRole("dialog");
  await expect(dialog).toContainText("OP-FIRST");
  await expect(dialog).toContainText("OP-SECOND");
  const first = dialog.locator("article").filter({ hasText: "OP-FIRST" });
  const second = dialog.locator("article").filter({ hasText: "OP-SECOND" });
  await first.getByRole("button", { name: "Stock source and reservations" }).click();
  await expect(first).toContainText(/unattributed/i);
  await expect(first.locator("dd").filter({ hasText: /^2 / })).toHaveCount(2);
  await second.getByRole("button", { name: "Stock source and reservations" }).click();
  await expect(first.getByRole("button", { name: "Stock source and reservations" })).toHaveAttribute("aria-expanded", "false");
  await expect(second).toContainText("Blocked");
  const badSource = await validationFault(p, "/warehouse/inventory/" + state.mainId + "/batches/" + state.firstBatch + "/source?");
  const failed = p.waitForResponse(r => r.status() === 422 && r.url().includes("/batches/" + state.firstBatch + "/source?"));
  await first.getByRole("button", { name: "Stock source and reservations" }).click();
  expect((await failed).headers()["x-request-id"]).toBeTruthy();
  await expect(first.getByRole("alert")).toBeVisible();
  await badSource();
  await first.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(first.getByRole("alert")).toHaveCount(0);
  await expect(first).toContainText(/unattributed/i);
  command("reserve");
  const batchUpdate = p.waitForResponse(r => r.status() === 200 && r.url().includes("/inventory/" + state.mainId + "/batches?"));
  const refresh = dialog.getByRole("button", { name: "Refresh now", exact: true });
  await refresh.click();
  await expect(dialog).toBeVisible();
  await batchUpdate;
  await expect(dialog).toContainText("OP-FIRST");
  await expect(first.getByRole("button", { name: "Stock source and reservations" })).toHaveAttribute("aria-expanded", "false");
  await expect(first.locator('[id^="live-stock-source"]')).toHaveCount(0);
  await first.getByRole("button", { name: "Stock source and reservations" }).click();
  const evidence = await api(p, "/warehouse/inventory/" + state.mainId + "/batches/" + state.firstBatch + "/source?location_id=" + state.warehouse);
  const available = evidence.body.statuses.find((x: { stock_status: string }) => x.stock_status === "AVAILABLE");
  expect(canon(available.reserved_quantity)).toBe("24");
  expect(canon(available.movable_quantity)).toBe("776");
  expect(available.reservation_evidence.unattributed_quantity).toBe("24");
  await expect(first.locator("dd").filter({ hasText: /^3 / })).toHaveCount(2);
  await expect(first).toContainText("97");
  await shot(p, info, "open-dialog-fresh-reservation-and-source");
  await p.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(item(p, state.mainName).locator('[data-cp13-quantity="available"]')).toContainText("121");
  await expect(p.locator('[data-live-stock-product-open="' + state.mainId + '"]')).toBeFocused();
}

export async function searchFailures(p: Page, log: ReturnType<typeof record>) {
  const search = stock(p).getByRole("searchbox").first();
  const badSummary = await validationFault(p, "/warehouse/inventory/summary?");
  const summaryFailed = p.waitForResponse(r => r.status() === 422 && r.url().includes("/inventory/summary?"));
  await stock(p).locator(".live-stock-context-refresh").click();
  expect((await summaryFailed).headers()["x-request-id"]).toBeTruthy();
  const banner = stock(p).locator('[data-cp13-state="summary-unavailable"]');
  await expect(banner).toBeVisible();
  await expect(item(p, state.mainName)).toBeVisible();
  await badSummary();
  const listReads = log.requests.filter(u => new URL(u).pathname === "/warehouse/inventory/cursor").length;
  await banner.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(banner).toHaveCount(0);
  await delay(p);
  expect(log.requests.filter(u => new URL(u).pathname === "/warehouse/inventory/cursor")).toHaveLength(listReads);

  const failPage = await validationFault(p, "/warehouse/inventory/cursor?", true);
  await search.fill("Paging");
  await expect(item(p, "Paging Item 001")).toBeVisible();
  const list = stock(p).locator("[data-cp13-stock-list]");
  await list.evaluate(e => { e.scrollTop = e.scrollHeight; });
  await expect(stock(p).locator('[data-cp13-state="stale"]')).toBeVisible();
  await failPage();
  await expect(stock(p).locator(".live-stock-context-count strong")).toHaveText("109");
  const preserved = log.pages.filter(x => new URL(x.url).searchParams.get("search")?.toLowerCase() === "paging");
  expect(preserved[0].ids).toHaveLength(50);
  await stock(p).locator('[data-cp13-state="stale"]').getByRole("button", { name: "Retry", exact: true }).click();
  for (let n = 0; n < 10; n++) {
    await list.evaluate(e => { e.scrollTop = e.scrollHeight; });
    await p.waitForTimeout(150);
    await log.flush();
    const delivered = log.pages.filter(x => new URL(x.url).searchParams.get("search")?.toLowerCase() === "paging");
    const ids = delivered.flatMap(x => x.ids);
    if (ids.length >= 105) {
      expect(ids).toHaveLength(105);
      expect(new Set(ids).size).toBe(105);
      expect([...ids].sort((a, b) => a - b)).toEqual([...state.pagingIds].sort((a: number, b: number) => a - b));
      break;
    }
    if (n === 9) throw new Error("Real cursor continuation did not reach105 independent IDs");
  }
  await search.fill("");
  await stock(p).locator(".live-stock-family-button").click();
  await p.locator(".live-stock-family-list").getByRole("button", { name: "Load more", exact: false }).click();
  const selected = p.locator(".live-stock-family-option").filter({ hasText: "Journey Family 051" });
  await selected.focus();
  await p.keyboard.press("Enter");
  await p.keyboard.press("Escape");
  await expect(stock(p).locator(".live-stock-family-button")).toHaveAttribute("aria-label", /Journey Family 051/);
  await expect(item(p, "Paging Item 105")).toBeVisible();
  await search.fill("Paging Item 105");
  await expect(item(p, "Paging Item 105")).toBeVisible();
  await expect(stock(p).locator(".live-stock-family-button")).toHaveAttribute("aria-label", /Journey Family 051/);
  await stock(p).locator(".live-stock-family-button").click();
  await p.locator(".live-stock-family-clear").click();
  await p.keyboard.press("Escape");
  await search.fill("");
}
