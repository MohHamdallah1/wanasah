import { describe, expect, it } from "vitest";

import type { CatalogVariant } from "@/features/catalog/contracts";
import { emptyInboundBatch, type InboundDraftMap } from "./contracts";
import { orderInboundCatalog, withoutRecalledInboundDrafts } from "./eligibility";

const variant = (id: number, operational_hold: CatalogVariant["operational_hold"] = "NONE") =>
  ({ id, operational_hold });

describe("Inbound recall presentation", () => {
  const logicalOrder = [variant(1), variant(2, "RECALL"), variant(3), variant(4, "RECALL"), variant(5)];

  it("stably partitions all loaded pages without mutating their normal source order", () => {
    const firstPage = logicalOrder.slice(0, 2);
    const nextPage = logicalOrder.slice(2);
    const source = Object.freeze([...firstPage, ...nextPage]);
    expect(orderInboundCatalog(source).map((item) => item.id)).toEqual([1, 3, 5, 2, 4]);
    expect(source.map((item) => item.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it("returns a released product to normal source order without keeping a ranking", () => {
    const released = logicalOrder.map((item) => item.id === 2 ? variant(2) : item);
    expect(orderInboundCatalog(released).map((item) => item.id)).toEqual([1, 2, 3, 5, 4]);
  });

  it("keeps SALES_HOLD among normal rows and handles empty/all-recalled results", () => {
    expect(orderInboundCatalog([variant(1, "RECALL"), variant(2, "SALES_HOLD"), variant(3)])
      .map((item) => item.id)).toEqual([2, 3, 1]);
    expect(orderInboundCatalog([])).toEqual([]);
    expect(orderInboundCatalog([variant(4, "RECALL"), variant(2, "RECALL")])
      .map((item) => item.id)).toEqual([4, 2]);
  });

  it("removes every local recalled row while preserving eligible and unresolved drafts", () => {
    const drafts: InboundDraftMap = {
      "1": [{ ...emptyInboundBatch("recall-1"), quantity: "5" }, emptyInboundBatch("recall-2")],
      "2": [{ ...emptyInboundBatch("sales-hold"), quantity: "3" }],
      "3": [emptyInboundBatch("unresolved")],
    };
    const cleaned = withoutRecalledInboundDrafts(drafts, [variant(1, "RECALL"), variant(2, "SALES_HOLD")]);
    expect(cleaned).toEqual({ "2": drafts["2"], "3": drafts["3"] });
    expect(cleaned["2"]).toBe(drafts["2"]);
    expect(drafts["1"]).toHaveLength(2);
    expect(withoutRecalledInboundDrafts(cleaned, [variant(1)])).toBe(cleaned);
  });

  it("does not change draft identity when no known recall needs cleanup", () => {
    const drafts = { "1": [emptyInboundBatch("normal")] };
    expect(withoutRecalledInboundDrafts(drafts, [variant(1, "SALES_HOLD"), variant(2, "RECALL")])).toBe(drafts);
    expect(withoutRecalledInboundDrafts(drafts, [])).toBe(drafts);
  });
});
