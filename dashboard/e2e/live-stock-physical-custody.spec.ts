import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page } from "playwright/test";
import { api, item, login, record, shot, state, stock } from "./live-stock-operational.support";

function command(action: "grant" | "load" | "revoke") {
  const output = execFileSync(process.env.PYTHON || "python",
    [resolve("e2e/live-stock-physical-custody.fixture.py"), action], { encoding: "utf8", env: process.env });
  expect(output).toContain("PHYSICAL_CONSUMER_COMMAND PASS " + action);
}
async function witness(page: Page, scope: string, vehicle: string | null, warehouse: string) {
  const response = await api(page, "/warehouse/inventory/cursor?location_id=" + state.warehouse + "&search=OP-MULTI");
  expect(response.status).toBe(200);
  const row = response.body.items.find((x: { id: number }) => x.id === state.mainId);
  expect(row).toMatchObject({ vehicle_quantity_scope: scope, vehicle_quantity: vehicle,
    on_hand_quantity: warehouse, total_quantity: warehouse, total_quantity_scope: "WAREHOUSE_PHYSICAL" });
  return row;
}
async function vehicleFilter(page: Page, expectedIds: number[]) {
  const response = await api(page, "/warehouse/inventory/cursor?location_id=" + state.warehouse +
    "&search=OP-MULTI&has_vehicle=true");
  expect(response.status).toBe(200);
  expect(response.body.items.map((row: { id: number }) => row.id)).toEqual(expectedIds);
}
async function refresh(page: Page) {
  const read = page.waitForResponse(r => r.request().method() === "GET" && r.status() === 200 &&
    new URL(r.url()).pathname === "/warehouse/inventory/cursor");
  await stock(page).locator(".live-stock-context-refresh").click();
  await read;
}

test("real #687 scopes, no-route load and same-token vehicle revocation preserve warehouse truth", async ({ page, browser }, info) => {
  const evidence = record(page);
  await login(page, "reader");
  const cell = () => item(page, state.mainName).locator('[data-cp13-quantity="vehicle"]');
  await witness(page, "NO_ACCESS", null, "1000");
  await vehicleFilter(page, []);
  await expect(cell()).toHaveText("Vehicle stock not disclosed");
  await expect(item(page, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("125");
  const context = await browser.newContext({ baseURL: "http://127.0.0.1:4173", viewport: { width: 1360, height: 900 } });
  const owner = await context.newPage();
  try {
    await login(owner, "owner");
    await witness(owner, "COMPANY_WIDE", "0", "1000");
    await vehicleFilter(owner, []);
    await expect(item(owner, state.mainName).locator('[data-vehicle-scope="COMPANY_WIDE"]')).toContainText("0");
    command("grant");
    await refresh(page);
    await witness(page, "AUTHORIZED_LOCATIONS", "0", "1000");
    await expect(cell()).toContainText("0");
    await expect(cell()).toContainText("Authorized vehicles only");
    command("load");
    await refresh(page);
    await witness(page, "AUTHORIZED_LOCATIONS", "32", "968");
    await vehicleFilter(page, [state.mainId]);
    await expect(cell()).toContainText("4");
    await refresh(owner);
    await witness(owner, "COMPANY_WIDE", "32", "968");
    await vehicleFilter(owner, [state.mainId]);
    for (const [language, width, label] of [
      ["en", 1360, "All company vehicles"], ["en", 390, "All company vehicles"],
      ["ar", 1360, "كل مركبات الشركة"], ["ar", 390, "كل مركبات الشركة"],
    ] as const) {
      await owner.setViewportSize({ width, height: 900 });
      await owner.evaluate(value => localStorage.setItem("wanasah.language", value), language);
      await owner.reload();
      await expect(item(owner, state.mainName)).toBeVisible();
      await expect(item(owner, state.mainName).locator('[data-vehicle-scope="COMPANY_WIDE"]')).toContainText(label);
      await expect(item(owner, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
      await shot(owner, info, "physical-custody-" + language + "-" + width);
    }
    const token = await page.evaluate(() => localStorage.getItem("admin_token"));
    command("revoke");
    await refresh(page);
    await witness(page, "NO_ACCESS", null, "968");
    await vehicleFilter(page, []);
    await expect(cell()).toHaveText("Vehicle stock not disclosed");
    await expect(cell()).not.toContainText("4");
    expect(await page.evaluate(() => localStorage.getItem("admin_token"))).toBe(token);
    await expect(item(page, state.mainName).locator('[data-cp13-quantity="on-hand"]')).toContainText("121");
    await expect(stock(page).locator(".live-stock-context-count strong")).toHaveText("109");
    await shot(page, info, "warehouse-preserved-after-vehicle-revoke");
    await evidence.flush();
    expect(evidence.errors).toEqual([]);
  } finally {
    evidence.persist(info, "physical-custody-requests.json");
    await context.close();
  }
});
