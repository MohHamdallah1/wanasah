import { describe, expect, it } from "vitest";
import type { SettlementAuthFetch } from "@/features/operations/representativeSettlement/api";
import {
  readSignedVehicleResponsibilities, signedSessionVehicleResponsibilities,
} from "@/features/operations/representativeSettlement/vehicleResponsibilityRead";

const one = {
  vehicle_id: 5, vehicle_location_id: 15, plate_number: "A",
  period_ids: [10, 12], custody_epoch_ids: [30, 32],
  checkpoint_status: "COUNT_SIGNED" as const,
  checkpoint_id: 35, checkpoint_mode: "COUNT_IN_PLACE" as const,
};
const two = {
  vehicle_id: 6, vehicle_location_id: 16, plate_number: "B",
  period_ids: [11], custody_epoch_ids: [31],
  checkpoint_status: "NOT_COUNTED" as const,
  checkpoint_id: null, checkpoint_mode: null,
};
const fixture = {
  work_session_id: 100, work_session_ended: true, financially_settled: false,
  all_vehicle_counts_signed: false, vehicles: [one, two],
};

describe("M05 signed M04 S1 A/B vehicle responsibility list", () => {
  it("parses exact period/epoch lineage once; physical A/B remain distinct", async () => {
    const requested: string[] = [];
    const fetch = (async (url: string) => {
      requested.push(url);
      return fixture;
    }) as SettlementAuthFetch;
    const signed = await readSignedVehicleResponsibilities(fetch, 100);
    expect(requested).toEqual([
      "/admin/sessions/100/inventory-custody/vehicles",
    ]);
    expect(signed.vehicles.map(vehicle => vehicle.vehicle_location_id)).toEqual([15, 16]);
    expect(signed.vehicles[0].period_ids).toEqual([10, 12]);
    expect(signed.all_vehicle_counts_signed).toBe(false);
    expect(signed.financially_settled).toBe(false);
    expect(signed.vehicles[0].checkpoint_mode).toBe("COUNT_IN_PLACE");
  });

  it("denies duplicate vehicle/location, missing period, fake all-car clearance", () => {
    expect(signedSessionVehicleResponsibilities.safeParse({
      ...fixture, vehicles: [one, { ...two, vehicle_location_id: 15 }],
    }).success).toBe(false);
    expect(signedSessionVehicleResponsibilities.safeParse({
      ...fixture, vehicles: [{ ...one, period_ids: [] }],
    }).success).toBe(false);
    expect(signedSessionVehicleResponsibilities.safeParse({
      ...fixture, financially_settled: true,
    }).success).toBe(false);
    expect(signedSessionVehicleResponsibilities.safeParse({
      ...fixture, all_vehicle_counts_signed: true,
    }).success).toBe(false);
  });

  it("refuses session mismatch and propagates unauthorized 403/404 (no fake fallback)", async () => {
    const wrong = (async () => ({ ...fixture, work_session_id: 101 })) as SettlementAuthFetch;
    await expect(readSignedVehicleResponsibilities(wrong, 100)).rejects.toThrow(
      "M05_SIGNED_S1_VEHICLE_MEMBERSHIP_INVALID",
    );
    const denied = (async () => { throw new Error("HTTP_403"); }) as SettlementAuthFetch;
    await expect(readSignedVehicleResponsibilities(denied, 100)).rejects.toThrow("HTTP_403");
    const missing = (async () => { throw new Error("HTTP_404"); }) as SettlementAuthFetch;
    await expect(readSignedVehicleResponsibilities(missing, 100)).rejects.toThrow("HTTP_404");
  });
});
