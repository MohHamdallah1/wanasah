import { describe, expect, it } from "vitest";
import {
  buildRouteLoadBaseTargets, formatRouteLoadQuantity,
  parseRouteLoadVehicleInventory, routeLoadReview,
} from "@/features/dispatch/routeLoadUom";

const item = {
  product_id: "701",
  product_name: "Chips",
  current_quantity: 2,          // Legacy complete packs
  current_loose_packs: 4,        // Legacy remainder
  current_base_quantity: "20",  // Canonical truth
  base_uom_id: 1,
  base_uom_code: "PCS",
  base_uom_name: "حبات",
  quantity_scale: 0,
  quantity_step: "1",
  display_uom_name: "باكيت",
  display_factor_to_base: "8",
};

describe("Dispatch Route Launch base UOM reconciliation", () => {
  it("prefills all twenty pieces rather than two complete packs", () => {
    const { current, units } = parseRouteLoadVehicleInventory([item]);
    expect(current).toEqual({ "701": "20" });
    expect(formatRouteLoadQuantity(current["701"], units["701"])).toBe("2 باكيت + 4 حبات");
    expect(buildRouteLoadBaseTargets(current, units)).toEqual({ "701": "20" });
    expect(routeLoadReview(current["701"], current["701"], units["701"])).toMatchObject({
      delta: "0", direction: "UNCHANGED",
    });
  });

  it("changes only the difference in the correct direction", () => {
    const { units } = parseRouteLoadVehicleInventory([item]);
    expect(routeLoadReview("20", "24", units["701"])).toMatchObject({
      delta: "4", direction: "ADD",
    });
    expect(routeLoadReview("20", "16", units["701"])).toMatchObject({
      delta: "-4", direction: "UNLOAD",
    });
    expect(buildRouteLoadBaseTargets({ "701": "16" }, units)).toEqual({ "701": "16" });
  });

  it("rejects invalid base steps and missing conversion authority", () => {
    const { units } = parseRouteLoadVehicleInventory([item]);
    expect(() => buildRouteLoadBaseTargets({ "701": "20.5" }, units)).toThrow();
    expect(() => buildRouteLoadBaseTargets({ "702": "2" }, units)).toThrow();
  });

  it("never derives a target from legacy complete-pack fields", () => {
    const legacy = { ...item, current_quantity: 0, current_loose_packs: 0 };
    const { current } = parseRouteLoadVehicleInventory([legacy]);
    expect(current["701"]).toBe("20");
  });
});
