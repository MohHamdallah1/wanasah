import { z } from "zod";
import type { SettlementAuthFetch } from "./api";

// M04 is merged: use this per-car signed count sheet only after the
// authoritative S1 membership read. Never infer cars from a historic route.
const vehicleCountLine = z.object({
  line_key: z.string().regex(/^[a-f0-9]{24}$/),
  product_name: z.string(),
  sku: z.string(),
  batch_number: z.string().nullable(),
  expiry_date: z.string().nullable(),
  stock_status: z.string(),
  uom: z.string(),
  expected_quantity: z.string(),
});

export const vehicleCountSheetSchema = z.object({
  work_session_id: z.number().int().positive(),
  vehicle_id: z.number().int().positive(),
  vehicle_plate: z.string(),
  snapshot_token: z.string().regex(/^[a-f0-9]{64}$/),
  epoch_count: z.number().int().positive(),
  lines: z.array(vehicleCountLine),
});

export type VehicleCountSheet = z.infer<typeof vehicleCountSheetSchema>;

export async function readAuthorizedVehicleCount(
  fetch: SettlementAuthFetch, sessionId: number, vehicleId: number,
  signal?: AbortSignal,
): Promise<VehicleCountSheet> {
  if (![sessionId, vehicleId].every(id => Number.isSafeInteger(id) && id > 0)) {
    throw new Error("M05_VEHICLE_SCOPE_INVALID");
  }
  const result = vehicleCountSheetSchema.safeParse(
    await fetch(`/admin/sessions/${sessionId}/inventory-custody/vehicles/${vehicleId}`,
      { signal, cache: "no-store" }),
  );
  if (!result.success || result.data.work_session_id !== sessionId ||
      result.data.vehicle_id !== vehicleId) {
    throw new Error("M05_VEHICLE_COUNT_RESPONSE_INVALID");
  }
  return result.data;
}

// M04's real signed count writer is bound separately in vehicleCountCommand.
// This reader never posts a count or converts a snapshot into a settlement.
