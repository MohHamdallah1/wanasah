import { describe, expect, it } from "vitest";
import {
  createLifecycleIntent, parseLifecycleReceipt, parseRouteAssignmentProof,
} from "@/features/dispatch/routeLifecycle/contract";
import { vehicleCountSheetSchema } from "@/features/operations/representativeSettlement/vehicleCountRead";

const route = {
  id: "17",
  driverId: "3", vehicleId: "5", workSessionId: "88",
  assignmentContextRevision: 4,
  currentPeriodId: null,
  currentDriverId: null,
  currentVehicleId: null,
};

describe("M05 exact read and lifecycle intent", () => {
  it("refuses the legacy last-route driver/vehicle as live M02 authority", () => {
    expect(parseRouteAssignmentProof({
      id: "17", driverId: "3", vehicleId: "5",
      adjustmentContextRevision: 5, sessionBound: true,
    })).toBeNull();
  });

  it("freezes exact route revision, both destination IDs and signed custody", () => {
    const proof = parseRouteAssignmentProof(route);
    expect(proof).not.toBeNull();
    const intent = createLifecycleIntent("RESUME", proof!, {
      vehicleId: 6, driverId: 7, custodyRevision: 12,
      accepted: true, authorized: true,
    });
    expect(intent).toEqual({
      action: "RESUME", expected_context_revision: 4,
      expected_period_id: null, expected_vehicle_custody_revision: 12,
      target_driver_id: 7, target_vehicle_id: 6,
    });
    expect(() => createLifecycleIntent("RESUME", proof!)).toThrow();
    const live = parseRouteAssignmentProof({
      ...route, assignmentContextRevision: 5,
      currentPeriodId: 37, currentDriverId: 7, currentVehicleId: 6,
    });
    expect(createLifecycleIntent("POSTPONE", live!).expected_period_id).toBe(37);
    expect(createLifecycleIntent("CLOSE", live!).expected_context_revision).toBe(5);
    expect(() => createLifecycleIntent("RESUME", live!, {
      vehicleId: 6, driverId: 7, custodyRevision: 12, accepted: true, authorized: true,
    })).toThrow();
  });

  it("rejects receipt with changed UUID/action/route or counterfeit success", () => {
    const valid = {
      request_id: "original", state: "COMMITTED", route_id: 17,
      action: "POSTPONE", status: "postponed", context_revision: 5,
      zone_reserved: true, live_assets_reserved: false,
    };
    expect(parseLifecycleReceipt(valid, 17, "POSTPONE", "original")).toEqual(valid);
    expect(() => parseLifecycleReceipt({ ...valid, request_id: "new" },
      17, "POSTPONE", "original")).toThrow();
    expect(() => parseLifecycleReceipt({ ...valid, live_assets_reserved: true },
      17, "POSTPONE", "original")).toThrow();
  });
});

describe("M05 M04 vehicle read is never an in-place write", () => {
  it("accepts only signed scoped per-vehicle count sheets", () => {
    const value = {
      work_session_id: 11, vehicle_id: 6, vehicle_plate: "A",
      snapshot_token: "a".repeat(64), epoch_count: 2,
      lines: [{
        line_key: "b".repeat(24), product_name: "Snack",
        sku: "S", batch_number: null, expiry_date: null,
        stock_status: "AVAILABLE", uom: "EACH",
        expected_quantity: "83",
      }],
    };
    expect(vehicleCountSheetSchema.safeParse(value).success).toBe(true);
    expect(vehicleCountSheetSchema.safeParse({
      ...value, snapshot_token: "invalid",
    }).success).toBe(false);
  });
});
