import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  DISPATCH_PRODUCT_WINDOW_LIMIT,
  boundedDispatchProductSearch,
  mergeDispatchProductWindow,
  selectedDispatchProducts,
} from "@/features/dispatch/productWindow";

describe("Dispatch large-catalog containment", () => {
  it("bounds the visible launch window with a 50k product catalog", () => {
    const products = Array.from({ length: 50_000 }, (_, index) => ({
      id: String(index + 1),
      name: `Product ${String(index + 1).padStart(5, "0")}`,
    }));

    const result = boundedDispatchProductSearch(products, "");

    expect(result).toHaveLength(DISPATCH_PRODUCT_WINDOW_LIMIT);
    expect(result[0]?.id).toBe("1");
    expect(result.at(-1)?.id).toBe(String(DISPATCH_PRODUCT_WINDOW_LIMIT));
  });

  it("can find a product near the end without rendering the whole catalog", () => {
    const products = Array.from({ length: 50_000 }, (_, index) => ({
      id: String(index + 1),
      name: index === 49_999 ? "Needle Product" : `Product ${index + 1}`,
    }));

    const result = boundedDispatchProductSearch(products, "needle");

    expect(result).toEqual([{ id: "50000", name: "Needle Product" }]);
  });

  it("keeps selected load products visible while merging bounded search results", () => {
    const products = Array.from({ length: 1_000 }, (_, index) => ({
      id: String(index + 1),
      name: `Product ${index + 1}`,
    }));
    const productsById = new Map(products.map((product) => [product.id, product] as const));

    const selected = selectedDispatchProducts(productsById, {
      "999": 4,
      "1000": 0,
    });
    const searched = boundedDispatchProductSearch(products, "Product 1", 5);
    const merged = mergeDispatchProductWindow(selected, searched);

    expect(merged[0]).toEqual({ id: "999", name: "Product 999" });
    expect(merged.some((product) => product.id === "1000")).toBe(false);
    expect(merged).toHaveLength(6);
  });

  it("does not construct heavy product modals while they are closed", () => {
    const source = readFileSync(
      join(process.cwd(), "src/pages/DispatchBoard.tsx"),
      "utf8",
    );

    expect(source).toContain("{isShortageModalOpen && (");
    expect(source).toContain("{isRouteModalOpen && (");
    expect(source).toContain("visibleLaunchProducts.map");
    expect(source).not.toContain("products\n                        .filter(prod =>");
  });

  it("projects only dispatch product id and name in the bootstrap query", () => {
    const source = readFileSync(
      join(process.cwd(), "../wa_backend/api/dispatch.py"),
      "utf8",
    );

    expect(source).toContain(
      "select(ProductVariant.id, ProductVariant.name).where(",
    );
    expect(source).toContain(
      '"products": [{"id": str(product_id), "name": product_name} for product_id, product_name in products]',
    );
  });
});
