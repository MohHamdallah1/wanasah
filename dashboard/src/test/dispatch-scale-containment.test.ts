import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  mergeDispatchProductWindow,
  positiveDispatchInventory,
  selectedDispatchProducts,
} from "@/features/dispatch/productWindow";

describe("Dispatch large-catalog containment", () => {
  it("merges the current server window with explicit selected pins only, without duplicates", () => {
    const selected = selectedDispatchProducts(new Map([["999", { id: "999", name: "Selected" }]]), { "999": 4 });
    const window = Array.from({ length: 80 }, (_, i) => ({ id: String(i + 1), name: `Page ${i + 1}` }));
    expect(mergeDispatchProductWindow(selected, [...window, ...selected])).toHaveLength(81);
    expect(mergeDispatchProductWindow(selected, window)[0].id).toBe("999");
  });

  it("keeps the launch payload sparse even if a 50k zero-filled map reaches the client", () => {
    const quantities: Record<string, number> = Object.fromEntries(
      Array.from({ length: 50_000 }, (_, index) => [String(index + 1), 0]),
    );
    quantities["504"] = 1;

    expect(positiveDispatchInventory(quantities)).toEqual({ "504": 1 });
  });

  it("vehicle inventory endpoint returns actual loaded products only", () => {
    const source = readFileSync(
      join(process.cwd(), "../wa_backend/api/dispatch.py"),
      "utf8",
    ).replace(/\r\n/g, "\n");

    const start = source.indexOf("async def get_vehicle_inventory");
    const end = source.indexOf(
      '@router.get("/dispatch/route/{route_id}/live_inventory"',
      start,
    );
    const endpoint = source.slice(start, end);

    expect(endpoint).toContain("if not loaded_ids:\n        return []");
    expect(endpoint).toContain("ProductVariant.id.in_(loaded_ids)");
    expect(endpoint).not.toContain(
      "or_(product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW), ProductVariant.id.in_(loaded_ids))",
    );
  });

  it("does not construct heavy product modals while they are closed", () => {
    const source = readFileSync(
      join(process.cwd(), "src/pages/DispatchBoard.tsx"),
      "utf8",
    );

    expect(source).toContain("{isShortageModalOpen && (");
    expect(source).toContain("{isRouteModalOpen && (");
    expect(source).toContain("<RouteLoadProductTable");
    expect(source).not.toContain("initData.products");
    expect(source).not.toContain("setProducts(");
    expect(source).not.toContain("products\n                        .filter(prod =>");
  });

  it("bootstrap owns no product catalog query or payload", () => {
    const source = readFileSync(join(process.cwd(), "../wa_backend/api/dispatch.py"), "utf8");
    const init = source.slice(source.indexOf("async def dispatch_init"), source.indexOf("# PATCH: DISPATCH_UNIFIED_INVENTORY_CORE"));
    expect(init).not.toContain("ProductVariant");
    expect(init).not.toContain('"products"');
  });

  it("surfaces the backend route-launch reason instead of the generic HTTP message", () => {
    const source = readFileSync(
      join(process.cwd(), "src/pages/DispatchBoard.tsx"),
      "utf8",
    );

    expect(source).toContain(
      'apiErrorMessage(err, "فشل إطلاق خط السير.")',
    );
    expect(source).not.toContain(
      '"خطأ في إطلاق خط السير: " + getErrorMessage(err)',
    );
  });

});
