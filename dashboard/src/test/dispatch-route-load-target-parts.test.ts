import { describe, expect, it } from "vitest";
import {
  composeRouteLoadTargetBase, splitRouteLoadTargetBase, type RouteLoadTargetUnit,
} from "@/features/dispatch/routeLoadTargetParts";
import { buildRouteLoadBaseTargets, routeLoadReview } from "@/features/dispatch/routeLoadUom";

const carton50: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", display_factor_to_base: "50",
};
const pack8: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", display_factor_to_base: "8",
};
const pallet4800: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", display_factor_to_base: "4800",
};
const single: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", display_factor_to_base: null,
};
const quarter: RouteLoadTargetUnit = {
  quantity_scale: 2, quantity_step: "0.25", display_factor_to_base: "8",
};

describe("Route Launch largest display UOM + exact base remainder", () => {
  it("25 cartons with factor 50 means 1250 BASE, never 25 BASE", () => {
    const total = composeRouteLoadTargetBase("25", "", carton50);
    expect(total).toBe("1250");
    expect(splitRouteLoadTargetBase(total, carton50)).toEqual({
      displayQuantity: "25", baseRemainder: "0", hasDisplayUnit: true,
    });
    expect(composeRouteLoadTargetBase("25", "3", carton50)).toBe("1253");
    expect(splitRouteLoadTargetBase("1253", carton50).baseRemainder).toBe("3");
  });

  it("allows PALLET when PALLET is largest eligible UOM, not carton by default", () => {
    expect(composeRouteLoadTargetBase("25", "1", pallet4800)).toBe("120001");
    expect(splitRouteLoadTargetBase("120001", pallet4800)).toEqual({
      displayQuantity: "25", baseRemainder: "1", hasDisplayUnit: true,
    });
  });

  it("preserves current load and previews delta only in BASE units", () => {
    const target = composeRouteLoadTargetBase("25", "3", carton50);
    const unit = {
      base_uom_id: 1, base_uom_code: "PCS", base_uom_name: "piece",
      quantity_scale: 0, quantity_step: "1",
      display_uom_name: "carton", display_factor_to_base: "50",
    };
    expect(buildRouteLoadBaseTargets({ "7": target }, { "7": unit })).toEqual({ "7": "1253" });
    expect(routeLoadReview("1000", target, unit)).toMatchObject({
      delta: "253", direction: "ADD",
    });
    expect(routeLoadReview("1500", target, unit)).toMatchObject({
      delta: "-247", direction: "UNLOAD",
    });
    expect(routeLoadReview(target, target, unit)).toMatchObject({
      delta: "0", direction: "UNCHANGED",
    });
  });

  it("supports largest pack UOM and exact fractional base-unit remainders", () => {
    expect(splitRouteLoadTargetBase("25", pack8)).toEqual({
      displayQuantity: "3", baseRemainder: "1", hasDisplayUnit: true,
    });
    expect(composeRouteLoadTargetBase("3", "1", pack8)).toBe("25");
    expect(splitRouteLoadTargetBase("20.25", quarter)).toEqual({
      displayQuantity: "2", baseRemainder: "4.25", hasDisplayUnit: true,
    });
    expect(composeRouteLoadTargetBase("2", "4.25", quarter)).toBe("20.25");
    expect(() => composeRouteLoadTargetBase("2", "4.1", quarter)).toThrow();
    expect(() => composeRouteLoadTargetBase("2", "8", quarter)).toThrow(
      "DISPATCH_DISPLAY_REMAINDER_TOO_LARGE",
    );
  });

  it("renders a single base-UOM input when there is no larger display UOM", () => {
    expect(splitRouteLoadTargetBase("25", single)).toEqual({
      displayQuantity: "0", baseRemainder: "25", hasDisplayUnit: false,
    });
    expect(composeRouteLoadTargetBase("", "25", single)).toBe("25");
    expect(() => composeRouteLoadTargetBase("25", "0", single)).toThrow(
      "DISPATCH_DISPLAY_UOM_UNAVAILABLE",
    );
    expect(splitRouteLoadTargetBase("25", {...single, display_factor_to_base: "1"}))
      .toEqual({ displayQuantity: "0", baseRemainder: "25", hasDisplayUnit: false });
  });

  it.each(["-1", "1.5", "1e4", "Infinity", "NaN"])(
    "rejects invalid larger-unit count %s", (raw) => {
      expect(() => composeRouteLoadTargetBase(raw, "", carton50)).toThrow();
    },
  );

  it("never silently carries an oversize small-unit remainder", () => {
    expect(() => composeRouteLoadTargetBase("1", "50", carton50)).toThrow(
      "DISPATCH_DISPLAY_REMAINDER_TOO_LARGE",
    );
    expect(() => composeRouteLoadTargetBase("1", "51", carton50)).toThrow();
  });

  it("supports zero, bounds and exact six-decimal NUMERIC(20,6) with no floats", () => {
    expect(composeRouteLoadTargetBase("", "", carton50)).toBe("0");
    expect(splitRouteLoadTargetBase("0", carton50).displayQuantity).toBe("0");
    const nearMax = "99999999999999.999999";
    const six = { quantity_scale: 6, quantity_step: "0.000001", display_factor_to_base: "50" };
    const parts = splitRouteLoadTargetBase(nearMax, six);
    expect(composeRouteLoadTargetBase(parts.displayQuantity, parts.baseRemainder, six)).toBe(nearMax);
    expect(() => composeRouteLoadTargetBase("2000000000000", "0", six)).toThrow(
      "DISPATCH_TARGET_BASE_OVERFLOW",
    );
    expect(() => composeRouteLoadTargetBase("99999999999999999999999999999", "0", six)).toThrow();
  });

  it("fails closed on invalid or ambiguous display factor metadata", () => {
    for (const display_factor_to_base of ["0", "-5", "2.5", "NaN", ""]) {
      expect(() => composeRouteLoadTargetBase("1", "0", {
        ...carton50, display_factor_to_base,
      })).toThrow();
    }
  });
});
