import { describe, expect, it } from "vitest";
import type { StocktakeRow } from "../inventoryUtils";
import { parseCountSheet } from "./parsers";
import {
  calculateCount, countOuterFactor, parseCountOuterUom, restoreCountParts,
  splitCountForDisplay, validBaseCount,
} from "./countEntry";

const sheet = {
  product_variant_id: 118, batch_id: 51, stock_status: "AVAILABLE",
  product_name: "Registered product", batch_number: "LOT-51", expiry_date: null,
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 3, quantity_step: "0.125",
};
const outer = {
  count_outer_uom_id: 13, count_outer_uom_name: "Carton",
  count_outer_uom_code: "CTN", count_outer_factor_numerator: 50,
  count_outer_factor_denominator: 1,
};
const row = (meta: Record<string, unknown> = outer): StocktakeRow => ({
  ...sheet, stock_status: "AVAILABLE", row_key: "118:51:AVAILABLE",
  actual_quantity: "", counted: false, ...(meta as object),
});

describe("Stocktake exact optional server UOM read and base count arithmetic", () => {
  it("accepts only complete safe integer-rational authoritative mapping", () => {
    const read = parseCountSheet([{ ...sheet, ...outer }]);
    expect(read[0]).toMatchObject(outer);
    expect(countOuterFactor(row())).toBe(50n);
    expect(parseCountSheet([sheet])[0].count_outer_uom_id).toBeUndefined();
    for (const invalid of [
      { ...outer, count_outer_factor_numerator: 3, count_outer_factor_denominator: 2 },
      { ...outer, count_outer_uom_id: 7 },
      { ...outer, count_outer_factor_denominator: 0 },
      { ...outer, count_outer_uom_name: null },
      { ...outer, count_outer_factor_numerator: 50.2 },
      { ...outer, count_outer_factor_denominator: undefined },
      { count_outer_uom_id: 13 },
    ]) {
      expect(parseCountOuterUom(invalid, 7)).toBeNull();
      expect(parseCountSheet([{ ...sheet, ...invalid }])[0].count_outer_uom_id).toBeUndefined();
    }
  });

  it("adds 2 authoritative cartons × 50 plus 7 loose exactly without floats", () => {
    expect(calculateCount(row(), "2", "7")).toBe("107");
    expect(calculateCount(row(), "2", "7.125")).toBe("107.125");
    expect(calculateCount(row(), "2", "")).toBe("100");
    expect(calculateCount(row(), "", "7")).toBe("7");
    expect(splitCountForDisplay(row(), "107.125")).toEqual({ outer: "2", base: "7.125" });
    expect(restoreCountParts(row(), {
      ...row(), actual_quantity: "107.125", counted: true,
      count_outer_quantity: "2", count_base_quantity: "7.125",
    })).toEqual({ outer: "2", base: "7.125" });
  });

  it("rejects implicit zero, negative, NaN, excess precision, wrong scale/step and partial punctuation", () => {
    const precise = row();
    for (const [outerValue, base] of [
      ["", ""], ["0", ""], ["", "0"], ["0", "0"],
      ["-2", "7"], ["two", "7"], ["2", "7..1"],
      ["2", "7.1234567"], ["2", "7.100"], ["2", "NaN"],
    ]) {
      expect(calculateCount(precise, outerValue, base)).toBeNull();
    }
    expect(validBaseCount(precise, "0")).toBe("0"); // Zero only counts via explicit action.
    expect(validBaseCount(precise, "-4")).toBeNull();
    expect(validBaseCount(precise, "1e6")).toBeNull();
    expect(validBaseCount(precise, "0.25")).toBe("0.25");
  });

  it("falls back to exactly one base input if metadata is absent or untrusted", () => {
    const base = row({});
    expect(countOuterFactor(base)).toBeNull();
    expect(calculateCount(base, "999", "3.125")).toBe("3.125");
    expect(calculateCount(base, "2", "")).toBeNull();
    const changingServerFactor = row({ ...outer, count_outer_factor_numerator: 40 });
    expect(restoreCountParts(changingServerFactor, {
      ...row(), actual_quantity: "107", counted: true,
      count_outer_quantity: "2", count_base_quantity: "7",
    })).toEqual({ outer: "2", base: "27" });
  });
});
