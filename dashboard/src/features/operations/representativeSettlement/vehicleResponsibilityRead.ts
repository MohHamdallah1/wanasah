import { z } from "zod";
import type { SettlementAuthFetch } from "./api";

// Exact M04 PR #944 signed S1 vehicle responsibility GET. No historical
// DispatchRoute.vehicleId lookup and no inferred financial clearance.
const vehicle = z.object({
  vehicle_id: z.number().int().positive(),
  vehicle_location_id: z.number().int().positive(),
  plate_number: z.string().min(1),
  period_ids: z.array(z.number().int().positive()).min(1).max(128),
  custody_epoch_ids: z.array(z.number().int().positive()).min(1).max(128),
  checkpoint_status: z.enum(["NOT_COUNTED", "REVIEW_REQUIRED", "RECOUNT_AND_SIGN_REQUIRED", "COUNT_SIGNED"]),
  checkpoint_id: z.number().int().positive().nullable(),
  checkpoint_mode: z.enum(["COUNT_IN_PLACE", "PHYSICAL_HANDOFF"]).nullable(),
}).strict();

export const signedSessionVehicleResponsibilities = z.object({
  work_session_id: z.number().int().positive(),
  work_session_ended: z.boolean(),
  financially_settled: z.boolean(),
  all_vehicle_counts_signed: z.boolean(),
  vehicles: z.array(vehicle).min(1).max(128),
}).strict().superRefine((data, ctx) => {
  const vehicleIds = new Set<number>();
  const locationIds = new Set<number>();
  for (const v of data.vehicles) {
    if (vehicleIds.has(v.vehicle_id) || locationIds.has(v.vehicle_location_id)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "M05_DUPLICATE_VEHICLE_RESPONSIBILITY" });
    }
    vehicleIds.add(v.vehicle_id);
    locationIds.add(v.vehicle_location_id);
    if (new Set(v.period_ids).size !== v.period_ids.length ||
        new Set(v.custody_epoch_ids).size !== v.custody_epoch_ids.length) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "M05_AMBIGUOUS_PERIOD_EPOCH" });
    }
    if (v.checkpoint_status === "COUNT_SIGNED" &&
        (v.checkpoint_id === null || v.checkpoint_mode === null)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "M05_UNSIGNED_CHECKPOINT" });
    }
    if (v.checkpoint_status !== "COUNT_SIGNED" &&
        (v.checkpoint_id !== null || v.checkpoint_mode !== null)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "M05_NONFINAL_CHECKPOINT_CONFLICT" });
    }
  }
  const derivedSigned = data.vehicles.every(v => v.checkpoint_status === "COUNT_SIGNED");
  if (data.all_vehicle_counts_signed !== derivedSigned ||
      (data.financially_settled && !derivedSigned)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "M05_ALL_VEHICLE_READINESS_MISMATCH" });
  }
});

export type SignedSessionVehicleResponsibilities = z.infer<typeof signedSessionVehicleResponsibilities>;

export async function readSignedVehicleResponsibilities(
  fetch: SettlementAuthFetch, sessionId: number, signal?: AbortSignal,
): Promise<SignedSessionVehicleResponsibilities> {
  if (!Number.isSafeInteger(sessionId) || sessionId <= 0) throw new Error("M05_SESSION_INVALID");
  const response = await fetch(
    `/admin/sessions/${sessionId}/inventory-custody/vehicles`,
    { signal, cache: "no-store" },
  );
  const parsed = signedSessionVehicleResponsibilities.safeParse(response);
  if (!parsed.success || parsed.data.work_session_id !== sessionId) {
    throw new Error("M05_SIGNED_S1_VEHICLE_MEMBERSHIP_INVALID");
  }
  return parsed.data; // Not permission to POST count or to financially settle.
}
