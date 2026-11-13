import { describe, expect, it } from "vitest";
import {
  composeRouteLoadTargetBase, splitRouteLoadTargetBase, type RouteLoadTargetUnit,
} from "@/features/dispatch/routeLoadTargetParts";
import { buildRouteLoadBaseTargets, routeLoadReview } from "@/features/dispatch/routeLoadUom";

const carton50: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", carton_factor_to_base: "50",
};
const carton8: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", carton_factor_to_base: "8",
};
const pieces: RouteLoadTargetUnit = {
  quantity_scale: 0, quantity_step: "1", carton_factor_to_base: null,
};
const quarter: RouteLoadTargetUnit = {
  quantity_scale: 2, quantity_step: "0.25", carton_factor_to_base: "8",
};

describe("Route Launch explicit carton + exact base remainder", () => {
  it("25 cartons (factor 50) means 1250 BASE, never 25 BASE", () => {
    const total = composeRouteLoadTargetBase("25", "", carton50);
    expect(total).toBe("1250");
    expect(splitRouteLoadTargetBase(total, carton50)).toEqual({
      cartons: "25", baseRemainder: "0", hasCarton: true,
    });
    expect(composeRouteLoadTargetBase("25", "3", carton50)).toBe("1253");
    expect(splitRouteLoadTargetBase("1253", carton50).baseRemainder).toBe("3");
  });

  it("retains current load and produces only delta: ADD/UNLOAD/UNCHANGED", () => {
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

  it("retains every base remainder (including fractions and step precision)", () => {
    expect(splitRouteLoadTargetBase("25", carton8)).toEqual({
      cartons: "3", baseRemainder: "1", hasCarton: true,
    });
    expect(composeRouteLoadTargetBase("3", "1", carton8)).toBe("25");
    expect(splitRouteLoadTargetBase("20.25", quarter)).toEqual({
      cartons: "2", baseRemainder: "4.25", hasCarton: true,
    });
    expect(composeRouteLoadTargetBase("2", "4.25", quarter)).toBe("20.25");
    expect(() => composeRouteLoadTargetBase("2", "4.1", quarter)).toThrow();
    expect(() => composeRouteLoadTargetBase("2", "8", quarter)).toThrow(
      "DISPATCH_CARTON_REMAINDER_TOO_LARGE",
    );
  });

  it("does not invent a carton when server has no verified carton UOM", () => {
    expect(splitRouteLoadTargetBase("25", pieces)).toEqual({
      cartons: "0", baseRemainder: "25", hasCarton: false,
    });
    expect(composeRouteLoadTargetBase("", "25", pieces)).toBe("25");
    expect(() => composeRouteLoadTargetBase("25", "0", pieces)).toThrow(
      "DISPATCH_CARTON_UOM_UNAVAILABLE",
    );
    // The UI must use an explicit carton_factor_to_base; never treat a
    // separate display UOM (potentially PALLET) as a carton automatically.
    const displayMayBePallet = { ...pieces, display_factor_to_base: "4800" };
    expect(splitRouteLoadTargetBase("25", displayMayBePallet)).toEqual({
      cartons: "0", baseRemainder: "25", hasCarton: false,
    });
  });

  it.each(["-1", "1.5", "1e4", "Infinity", "NaN"])(
    "rejects invalid carton draft %s", (raw) => {
      expect(() => composeRouteLoadTargetBase(raw, "", carton50)).toThrow();
    },
  );

  it("never silently carries an oversize remainder into a carton", () => {
    expect(() => composeRouteLoadTargetBase("1", "50", carton50)).toThrow(
      "DISPATCH_CARTON_REMAINDER_TOO_LARGE",
    );
    expect(() => composeRouteLoadTargetBase("1", "51", carton50)).toThrow();
  });

  it("supports zero, bounds and large precise quantities without floats", () => {
    expect(composeRouteLoadTargetBase("", "", carton50)).toBe("0");
    expect(splitRouteLoadTargetBase("0", carton50).cartons).toBe("0");
    const nearMax = "99999999999999.999999";
    const six = { quantity_scale: 6, quantity_step: "0.000001", carton_factor_to_base: "50" };
    const parts = splitRouteLoadTargetBase(nearMax, six);
    expect(composeRouteLoadTargetBase(parts.cartons, parts.baseRemainder, six)).toBe(nearMax);
    expect(() => composeRouteLoadTargetBase("2000000000000", "0", six)).toThrow(
      "DISPATCH_TARGET_BASE_OVERFLOW",
    );
    expect(() => composeRouteLoadTargetBase("99999999999999999999999999999", "0", six)).toThrow();
  });

  it("rejects invalid or ambiguous factor data instead of inventing quantity", () => {
    for (const carton_factor_to_base of ["0", "1", "-5", "2.5", "NaN", ""]) {
      expect(() => composeRouteLoadTargetBase("1", "0", {
        ...carton50, carton_factor_to_base,
      })).toThrow();
    }
  });
});
