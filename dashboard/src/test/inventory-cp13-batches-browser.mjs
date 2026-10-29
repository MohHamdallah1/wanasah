// Opt-in browser acceptance, run only by the CP13 GitHub workflow.
// Isolated Vite harness consumes real Batches rendering, Modal and locale code.
// Only auth/data seams are fixtures. No backend, credentials or business writes.
import assert from "node:assert/strict";
import path from "node:path";
import { createServer } from "vite";
import react from "@vitejs/plugin-react-swc";
import { chromium } from "playwright";

const row = {
  batch_id: 41, batch_number: null, production_date: "2026-01-01", expiry_date: "2026-10-21",
  disposition: "RELEASED", disposition_reason: null, disposition_revision: 1,
  allowed_disposition_targets: [], days_to_expiry: 5,
  product_id: 10, product_variant_id: 141, product_name: "Browser fixture product with a long operator label",
  sku: "SKU-141", family_name: "Family A", lot_control_mode: "OPTIONAL", expiry_control_mode: "REQUIRED",
  minimum_remaining_shelf_life_days: 14, sellability_state: "NOT_SELLABLE",
  sellability_reason_codes: ["MINIMUM_REMAINING_SHELF_LIFE_NOT_MET"],
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
  display_uom_id: 1, display_uom_code: "EACH", display_uom_name: "Each",
  display_factor_to_base: "1", quantity_scale: 0, quantity_step: "1",
  on_hand_quantity: "10", reserved_quantity: "1", available_for_sale_quantity: "0", unavailable_quantity: "10",
  available_status_quantity: "7", quarantined_quantity: "3", blocked_quantity: "0", recalled_quantity: "0",
  damaged_quantity: "0", disposal_pending_quantity: "0",
};
const modules = {
  "\0cp13-fetch": `const read = async (url, options) => {
    const response = await fetch("/cp13-api" + url, options);
    if (!response.ok) throw Object.assign(new Error("CP13_READ_FAILED"), { code: "CP13_READ_FAILED", request_id: "cp13-browser" });
    return response.json();
  }; export const useAuthFetch = () => read;`,
  "\0cp13-access": `const access = { can: (code) => code === "inventory.read",
    data: { company_id: 1, principal_id: 7, backoffice_user_id: 17,
      permissions: ["inventory.read"], location_permissions: [], any_permissions: [] } };
    export const useInventoryAccess = () => access;`,
  "\0cp13-main.tsx": `import React, { useState } from "react";
    import { createRoot } from "react-dom/client";
    import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
    import "/src/i18n/index.ts";
    import "/src/index.css";
    import { TabBatches } from "/src/pages/inventory/TabBatches.tsx";
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const noop = () => {};
    function Harness() {
      const [focus, setFocus] = useState(new URLSearchParams(location.search).has("focus")
        ? { version: 1, kind: "batch-focus", tab: "batches", batchId: 41, variantId: 141, productName: "Untrusted label", locationId: 119 } : null);
      return <QueryClientProvider client={client}><div style={{ height: "100dvh", display: "flex" }}>
        <TabBatches locationId={119} focus={focus} onFocusConsumed={() => setFocus(null)}
          onOpenTransfers={noop} onOpenReservationOwner={noop} onInventoryChanged={noop} />
      </div></QueryClientProvider>;
    }
    createRoot(document.getElementById("root")).render(<Harness />);`,
};
const server = await createServer({
  configFile: false,
  plugins: [react(), {
    name: "cp13-isolated-browser-harness",
    resolveId(id) { if (id === "/cp13-main.tsx") return "\0cp13-main.tsx"; if (id in modules) return id; },
    load(id) { return modules[id]; },
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith("/cp13.html")) return next();
        res.setHeader("Content-Type", "text/html");
        res.end(await vite.transformIndexHtml(req.url, '<!doctype html><html><body><div id="root"></div><script type="module" src="/cp13-main.tsx"></script></body></html>'));
      });
    },
  }],
  resolve: { alias: [
    { find: "@/hooks/useAuthFetch", replacement: "\0cp13-fetch" },
    { find: "@/hooks/useInventoryAccess", replacement: "\0cp13-access" },
    { find: "@", replacement: path.resolve("src") },
  ] },
  server: { host: "127.0.0.1", port: 4193, strictPort: true },
});
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true });
  for (const language of ["ar", "en"]) for (const width of [1440, 768, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let failList = true;
    const requests = [];
    await page.route("**/cp13-api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const pathname = url.pathname.replace("/cp13-api", "");
      requests.push({ method: request.method(), pathname, search: url.search });
      assert.equal(request.method(), "GET");
      const send = (json) => route.fulfill({ json, headers: { "X-Request-Id": "cp13-browser" } });
      if (pathname === "/warehouse/inventory/batches/cursor") {
        if (failList) return route.fulfill({ status: 503, json: { code: "UNAVAILABLE", request_id: "cp13-browser" } });
        return send({ location_id: 119, as_of_date: "2026-10-16", items: [row], next_cursor: null, has_more: false });
      }
      if (pathname === "/warehouse/inventory/batches/summary") return send({
        location_id: 119, as_of_date: "2026-10-16", total_relevant_batches: 1, expired_count: 0, expiring_soon_count: 1,
        non_sellable_count: 1, quarantined_count: 0, blocked_count: 0, recalled_count: 0, damaged_or_disposal_attention_count: 0,
      });
      if (pathname === "/warehouse/batches/41/stock-sources") return send({ ...row, operational_hold: "NONE", sources: [] });
      // Exact-warehouse action-source read: no status mutation eligibility.
      if (pathname.endsWith("/action-source")) return send({
        location_id: 119, location_name: "Warehouse A", product_variant_id: 141, batch_id: 41,
        base_uom_id: 1, base_uom_code: "EACH", quantity_scale: 0, quantity_step: "1", statuses: [],
      });
      return route.fulfill({ status: 404, json: { code: "NOT_FOUND", request_id: "cp13-browser" } });
    });
    await page.addInitScript((lang) => { localStorage.setItem("wanasah.language", lang); }, language);
    await page.goto("http://127.0.0.1:4193/cp13.html");
    const view = page.locator(".inventory-batches-view");
    await view.getByRole("alert").waitFor();
    failList = false;
    await view.getByRole("button", { name: language === "ar" ? "إعادة المحاولة" : "Retry", exact: true }).click();
    const action = view.getByRole("button", { name: language === "ar" ? "عرض تفاصيل التشغيلة" : "View batch details", exact: true });
    await action.waitFor();
    assert.equal(await view.getAttribute("dir"), language === "ar" ? "rtl" : "ltr");
    assert.equal(await view.locator("dl dt").count(), 8);
    assert.equal(await view.locator("input[type=search]").count(), 1);
    const params = new URLSearchParams(requests.find((r) => r.pathname.endsWith("/cursor")).search);
    assert.equal(params.has("product_variant_id"), false);
    assert.equal(/[\u0660-\u0669\u06f0-\u06f9]/.test(await view.innerText()), false);
    assert.equal(await view.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), true);
    // Verify native search -> filters and both keyboard directions in Chromium.
    const search = view.getByRole("searchbox");
    await search.focus(); await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => document.activeElement?.tagName), "SELECT");
    await page.keyboard.press("Shift+Tab");
    assert.equal(await search.evaluate((el) => el === document.activeElement), true);
    await action.focus();
    assert.notEqual(await action.evaluate((el) => getComputedStyle(el).boxShadow), "none");
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await page.waitForFunction(() => document.querySelector('[role="dialog"]')?.contains(document.activeElement));
    assert.equal(await dialog.getByText("Family A", { exact: false }).count(), 1);
    await page.keyboard.press("Shift+Tab");
    assert.equal(await dialog.evaluate((el) => el.contains(document.activeElement)), true);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached" });
    await page.waitForFunction(() => document.activeElement?.textContent?.includes(localStorage.getItem("wanasah.language") === "ar" ? "عرض تفاصيل التشغيلة" : "View batch details"));
    await page.screenshot({ path: `cp13-${language}-${width}.png`, fullPage: true });
    await page.goto("http://127.0.0.1:4193/cp13.html?focus=41");
    await page.getByRole("dialog").waitFor();
    assert.equal(await page.getByText("Untrusted label", { exact: true }).count(), 0);
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(`CP13_BROWSER ${language} ${width}px PASS: retry, batch-first, digits, direction, layout, keyboard, detail, focus`);
    await page.close();
  }
} finally { await browser?.close(); await server.close(); }
