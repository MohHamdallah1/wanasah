import { describe, expect, it } from "vitest";

import {
  STOCKTAKE_STOCK_STATUSES,
  type StocktakeStockStatus,
} from "../inventoryUtils";
import { parseCountSheet } from "./parsers";

const row = (
  stockStatus: StocktakeStockStatus,
  productVariantId: number,
) => ({
  product_variant_id: productVariantId,
  batch_id: productVariantId,
  stock_status: stockStatus,
  product_name: `Product ${productVariantId}`,
  base_uom_id: 1,
  base_uom_code: "EACH",
  base_uom_name: "Each",
  quantity_scale: 0,
  quantity_step: "1",
  batch_number: `LOT-${productVariantId}`,
  expiry_date: null,
});

describe("Stocktake stock-status contract", () => {
  it("accepts every canonical backend inventory stock status", () => {
    expect(STOCKTAKE_STOCK_STATUSES).toEqual([
      "AVAILABLE",
      "QUARANTINED",
      "BLOCKED",
      "RECALLED",
      "DAMAGED",
      "DISPOSAL_PENDING",
    ]);

    const parsed = parseCountSheet(
      STOCKTAKE_STOCK_STATUSES.map((status, index) =>
        row(status, index + 1),
      ),
    );

    expect(parsed.map((item) => item.stock_status)).toEqual(
      STOCKTAKE_STOCK_STATUSES,
    );
  });

  it("still rejects any non-canonical stock status", () => {
    expect(() =>
      parseCountSheet([
        {
          ...row("AVAILABLE", 1),
          stock_status: "HACKED_STATUS",
        },
      ]),
    ).toThrow("تعذر فتح الجرد لأن حالة أحد أسطر المخزون غير معروفة للنظام.");
  });
});
