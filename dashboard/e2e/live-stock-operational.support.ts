import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page, type TestInfo, type Route } from "playwright/test";

export const API = "http://127.0.0.1:4174";
export const state = JSON.parse(readFileSync(process.env.WANASAH_OPERATIONAL_BROWSER_STATE!, "utf8"));
export const stock = (p: Page) => p.locator('[data-cp13-surface="live-stock"]');
export const rows = (p: Page) => p.locator(".live-stock-row");
export const item = (p: Page, name: string) => p.locator('.live-stock-row,[data-cp13-stock-card]').filter({ hasText: name });
export const canon = (value: string) => value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;

export async function login(p: Page, actor: "reader" | "owner" | "foreign", locale = "en") {
  await p.goto("/login");
  await p.evaluate((language) => localStorage.setItem("wanasah.language", language), locale);
  await p.reload();
  const c = state.credentials[actor];
  await p.locator("#company-code").fill(c.code);
  await p.locator("#username").fill(c.username);
  await p.locator("#password").fill(c.password);
  await Promise.all([p.waitForURL(u => u.pathname !== "/login"), p.locator('button[type="submit"]').click()]);
  if (actor !== "foreign") await p.evaluate(({ companyId, warehouse }) => {
    localStorage.setItem("inventory_selected_location:" + companyId, String(warehouse));
    localStorage.setItem("inventory_active_tab:" + companyId, "live");
  }, state);
  await p.goto("/inventory");
  await expect(stock(p)).toBeVisible();
}

export async function api(p: Page, path: string) {
  return p.evaluate(async ({ origin, path }) => {
    const r = await fetch(origin + path, { headers: { Authorization: "Bearer " + localStorage.getItem("admin_token") } });
    return { status: r.status, requestId: r.headers.get("x-request-id"), body: await r.json() };
  }, { origin: API, path });
}

export function command(action: "reserve" | "race-threshold" | "revoke") {
  const output = execFileSync(process.env.PYTHON || "python", [
    resolve(process.cwd(), "../wa_backend/tests/live_stock_operational_browser_support.py"), action,
  ], { encoding: "utf8", env: process.env });
  expect(output).toContain("OPERATIONAL_COMMAND PASS " + action);
}

export async function shot(p: Page, info: TestInfo, name: string) {
  await p.screenshot({ path: info.outputPath(name + ".png"), fullPage: true });
}
export const delay = (p: Page) => p.waitForTimeout(450);

export async function validationFault(p: Page, path: string, cursorOnly = false) {
  const pattern = API + path + "*";
  let used = false;
  const handler = async (route: Route) => {
    const url = new URL(route.request().url());
    if (!used && (!cursorOnly || url.searchParams.has("cursor"))) {
      used = true;
      // Forward to actual FastAPI validation. Never fulfill/stub an inventory response.
      url.searchParams.set("location_id", "invalid-operational-validation");
      await route.continue({ url: url.toString() });
    } else await route.continue();
  };
  await p.route(pattern, handler);
  return async () => { expect(used).toBe(true); await p.unroute(pattern, handler); };
}

export function record(p: Page) {
  const requests: string[] = [];
  const pages: Array<{ url: string; ids: number[]; cursor: string | null }> = [];
  const errors: string[] = [];
  const pending: Promise<void>[] = [];
  p.on("request", r => { if (r.method() === "GET" && r.url().startsWith(API)) requests.push(r.url()); });
  p.on("pageerror", e => errors.push(String(e)));
  p.on("requestfinished", request => {
    if (request.method() !== "GET" || new URL(request.url()).pathname !== "/warehouse/inventory/cursor") return;
    // Count initiated reads above; collect membership only after the body finished.
    // An intentionally cancelled reader has no committed page to audit.
    const work = (async () => {
      const response = await request.response();
      if (response?.status() !== 200) return;
      const body = await response.json();
      pages.push({ url: request.url(), ids: body.items.map((x: { id: number }) => x.id),
        cursor: body.next_cursor });
    })();
    pending.push(work);
  });
  return { requests, pages, errors, flush: () => Promise.all(pending),
    persist: (info: TestInfo, name = "operational-browser-evidence.json") => writeFileSync(info.outputPath(name),
      JSON.stringify({ expected: state.expected, requests, pages, errors }, null, 2)) };
}
