import { z } from "zod";
import type { SettlementAuthFetch } from "./api";
import { executeRepresentativeSettlementCommand } from "./durableCommand";
import { readAuthorizedVehicleCount } from "./vehicleCountRead";

const countResponse = z.object({
  status: z.string(),
  mode: z.enum(["COUNT_IN_PLACE", "PHYSICAL_HANDOFF"]).optional(),
  vehicle_id: z.number().int().positive().optional(),
  checkpoint_id: z.number().int().positive().optional(),
  review_required: z.boolean().optional(),
  inventory_reconciled: z.boolean().optional(),
  financial_ready: z.boolean().optional(),
  movement_count: z.number().int().nonnegative().optional(),
}).passthrough();

const line = z.object({
  line_key: z.string().regex(/^[0-9a-f]{24}$/),
  actual_quantity: z.string().min(1).max(50),
}).strict();
const positive = z.number().int().positive();

export type VehicleCountMode = "COUNT_IN_PLACE" | "PHYSICAL_HANDOFF";

export async function submitSignedVehicleCount(
  fetch: SettlementAuthFetch, sessionId: number, vehicleId: number,
  input: {
    mode: VehicleCountMode;
    snapshot_token: string;
    receiver_confirms_count: true;
    destination_location_id: number | null;
    receiver_confirms_handoff: boolean;
    items: Array<{ line_key: string; actual_quantity: string }>;
    notes: string | null;
  },
) {
  positive.parse(sessionId);
  positive.parse(vehicleId);
  z.string().regex(/^[0-9a-f]{64}$/).parse(input.snapshot_token);
  z.array(line).max(1000).parse(input.items);
  if (new Set(input.items.map(x => x.line_key)).size !== input.items.length) {
    throw new Error("M05_DUPLICATE_COUNT_LINES");
  }
  if ((input.mode === "COUNT_IN_PLACE" &&
      (input.destination_location_id !== null || input.receiver_confirms_handoff)) ||
      (input.mode === "PHYSICAL_HANDOFF" &&
      (!input.receiver_confirms_handoff || !positive.safeParse(input.destination_location_id).success))) {
    throw new Error("M05_UNCONFIRMED_PHYSICAL_HANDOFF");
  }
  // The car ID is part of the durable scope: an uncertain count of car A can
  // never be replaced by a count of B using the same request identity.
  const raw = await executeRepresentativeSettlementCommand({
    operation: "vehicle-count-" + vehicleId,
    sessionId,
    payload: input,
    send: (body) => fetch(
      "/admin/sessions/" + sessionId + "/inventory-custody/vehicles/" + vehicleId + "/count",
      { method: "POST", body: JSON.stringify(body) },
    ),
  });
  const result = countResponse.parse(raw);
  if (result.vehicle_id !== undefined && result.vehicle_id !== vehicleId) {
    throw new Error("M05_COUNT_VEHICLE_MISMATCH");
  }
  return result; // NEVER reinterpret financial_ready=false as a settlement grant.
}

const variance = z.object({
  status: z.string(),
  reconciliation_reference: z.string(),
  review_token: z.string().regex(/^[0-9a-f]{64}$/),
  requires_independent_recount: z.boolean(),
  independent_recount_satisfied: z.boolean(),
  lines: z.array(z.object({
    product_name: z.string(), batch_number: z.string().nullable(),
    stock_status: z.string(), expected_quantity: z.string(),
    actual_quantity: z.string(), variance_quantity: z.string(),
    expiry_date: z.string().nullable(),
  })),
});
const recount = z.object({
  status: z.string(), count_token: z.string().regex(/^[0-9a-f]{64}$/),
  lines: z.array(z.object({
    line_key: z.string().regex(/^[0-9a-f]{24}$/),
    product_name: z.string(), stock_status: z.string(),
    batch_number: z.string().nullable(), expiry_date: z.string().nullable(),
    uom: z.string(),
  })),
});
export type SignedVehicleVariance = z.infer<typeof variance>;
export type SignedVehicleRecount = z.infer<typeof recount>;

const variancePath = (sessionId: number, vehicleId: number) =>
  "/admin/sessions/" + sessionId + "/inventory-custody/vehicles/" + vehicleId + "/variance";

export async function readVehicleVariance(fetch: SettlementAuthFetch, sessionId: number, vehicleId: number) {
  return variance.parse(await fetch(variancePath(sessionId, vehicleId), { cache: "no-store" }));
}
export async function readVehicleRecount(fetch: SettlementAuthFetch, sessionId: number, vehicleId: number) {
  return recount.parse(await fetch(variancePath(sessionId, vehicleId) + "/count-sheet", { cache: "no-store" }));
}

export async function submitVehicleVariance(
  fetch: SettlementAuthFetch, sessionId: number, vehicleId: number,
  action: "approve" | "recount" | "count",
  payload: Record<string, unknown>,
) {
  const path = variancePath(sessionId, vehicleId) + "/" + action;
  return executeRepresentativeSettlementCommand({
    operation: "vehicle-variance-" + action + "-" + vehicleId,
    sessionId,
    payload,
    send: body => fetch(path, { method: "POST", body: JSON.stringify(body) }),
  });
}

// A count response is NOT proof that all cars signed. Refetch the signed
// membership, then the operations status. No shortcut to Financial Settlement.
export async function rereadVehicleCountEvidence(
  fetch: SettlementAuthFetch, sessionId: number, vehicleId: number,
) {
  return readAuthorizedVehicleCount(fetch, sessionId, vehicleId);
}
