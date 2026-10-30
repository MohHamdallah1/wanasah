import { expect, test } from "playwright/test";
import { visualCases } from "./live-stock-ux-closure.fixtures";
import { api, command, delay, item, login, record, shot, state, stock } from "./live-stock-operational.support";
import { detailFreshness, policyAndScope, searchFailures } from "./live-stock-operational.journey";

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
      await stock(op).getByRole("searchbox").first().fill("Paging");
      await expect(item(op, "Paging Item 001")).toBeVisible();
      await stock(op).locator(".live-stock-context-select").selectOption(String(state.otherWarehouse));
      await expect(stock(op).getByRole("searchbox").first()).toHaveValue("");
      await stock(op).locator(".live-stock-filter-button").click();
      await op.locator(".live-stock-filter-option").filter({ hasText: "Stock in warehouse" }).click();
      await op.keyboard.press("Escape");
      await expect(item(op, "Paging Item 001")).toBeVisible();
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
      // Actual React Router links keep the warm in-memory session alive.
      await op.locator('a[href="/products"]').first().click();
      await expect(op).toHaveURL(/\/products/);
      await op.locator('a[href="/inventory"]').first().click();
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
    await test.step("same-token source403 revokes already-open batch, list and costs", async () => {
      await page.setViewportSize({ width: 1360, height: 900 });
      await expect(item(page, state.mainName)).toBeVisible();
      await page.locator('[data-live-stock-product-open="' + state.mainId + '"]').click();
      const dialog = page.getByRole("dialog");
      const first = dialog.locator("article").filter({ hasText: "OP-FIRST" });
      await first.getByRole("button", { name: "Stock source and reservations" }).click();
      await expect(first).toContainText(/unattributed/i);
      const token = await page.evaluate(() => localStorage.getItem("admin_token"));
      command("revoke");
      await first.getByRole("button", { name: "Stock source and reservations" }).click();
      const denial = page.waitForResponse(r => r.status() === 403 && r.url().includes("/source?"));
      await first.getByRole("button", { name: "Stock source and reservations" }).click();
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
