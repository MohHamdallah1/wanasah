import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  parseVehicleLoadSnapshot,
  parseVehicleLoadSourcePage,
} from "@/pages/representatives-vehicles/vehicles/load/contracts";

const source = (relative: string) =>
  readFileSync(resolve(process.cwd(), "src", relative), "utf8");

describe("Vehicle Load V1 contract", () => {
  it("keeps direct Vehicle load separate from Vehicle CRUD authority", () => {
    const rowActions = source(
      "pages/representatives-vehicles/vehicles/VehicleRowActions.tsx",
    );
    const command = source(
      "pages/representatives-vehicles/vehicles/load/useVehicleLoadCommand.ts",
    );
    expect(rowActions).toContain("vehicles.load.action");
    expect(command).toContain("principal_id");
    expect(command).not.toContain("driver_id");
    expect(command).toContain("getOrCreateDurableCommand");
  });

  it("routes active Vehicle custody to the existing Dispatch Adjust load owner", () => {
    const modal = source(
      "pages/representatives-vehicles/vehicles/load/VehicleLoadModal.tsx",
    );
    const dispatch = source("pages/DispatchBoard.tsx");
    expect(modal).toContain('kind: "route-load"');
    expect(dispatch).toContain('intent.kind === "route-load"');
    expect(dispatch).toContain("setInventoryRoute(route)");
    expect(dispatch).toContain("setIsInventoryModalOpen(true)");
  });

  it("keeps direct add/unload server-backed and does not expose InventoryLocation IDs", () => {
    const modal = source(
      "pages/representatives-vehicles/vehicles/load/VehicleLoadModal.tsx",
    );
    const api = source(
      "pages/representatives-vehicles/vehicles/load/api.ts",
    );
    expect(api).toContain("/load/source-inventory");
    expect(api).toContain('direction === "ADD" ? "add" : "unload"');
    expect(api).toContain("/load/");
    expect(modal).toContain("snapshot.can_add");
    expect(modal).toContain("snapshot.can_unload");
    expect(modal).not.toContain("InventoryLocation");
    expect(modal).not.toContain("location_id");
  });

  it("strictly parses modes, quantities and bounded source pages", () => {
    expect(
      parseVehicleLoadSnapshot({
        vehicle_id: 7,
        mode: "ROUTE",
        route_id: 9,
        work_session_id: 11,
        vehicle_operational: true,
        can_add: false,
        can_unload: false,
        items: [],
      }),
    ).toMatchObject({ vehicle_id: 7, mode: "ROUTE", route_id: 9 });

    expect(() =>
      parseVehicleLoadSnapshot({
        vehicle_id: 7,
        mode: "MAGIC",
        route_id: null,
        work_session_id: null,
        vehicle_operational: true,
        can_add: true,
        can_unload: true,
        items: [],
      }),
    ).toThrow();

    expect(
      parseVehicleLoadSourcePage({
        items: [
          {
            product_variant_id: 3,
            product_name: "Tea",
            sku: "T-3",
            base_uom_id: 1,
            base_uom_code: "EA",
            base_uom_name: "Each",
            quantity_scale: 0,
            quantity_step: "1",
            available_quantity: "20",
          },
        ],
        next_cursor: null,
        has_more: false,
      }).items[0]?.available_quantity,
    ).toBe("20");

    expect(() =>
      parseVehicleLoadSourcePage({
        items: [],
        next_cursor: 17,
        has_more: false,
      }),
    ).toThrow();
  });
});
