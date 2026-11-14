import { z } from "zod";
import type { AuthorizedFetch } from "./command";
import type { Receipt } from "./contract";

const uuid = z.string().uuid();
const vehicleId = z.number().int().positive();
const states = z.enum(["PENDING", "CONFIRMED", "DECLINED", "CANCELLED", "EXPIRED", "COMMITTED"]);
const currentSchema = z.object({
  handoff_id: uuid, state: states, target_driver_id: vehicleId,
  recipient_label: z.string().min(1), expires_at: z.string().min(1),
  vehicle_id: vehicleId, context_revision: z.number().int(),
  reason_code: z.string().nullable().optional(),
  reason_text: z.string().nullable().optional(),
}).passthrough();

export type HandoffRecord = z.infer<typeof currentSchema>;
export type HandoffState = HandoffRecord["state"];
const root = (vehicle: string) => {
  if (!/^[1-9][0-9]*$/.test(vehicle) || !Number.isSafeInteger(Number(vehicle))) {
    throw new Error("CUSTODY_INVALID_VEHICLE");
  }
  return `/vehicles/${vehicle}/custody/handoffs`;
};
const post = (body: unknown): RequestInit => ({
  method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
  body: JSON.stringify(body),
});
const validateRecord = (raw: unknown, vehicle: string): HandoffRecord => {
  const record = currentSchema.parse(raw);
  if (record.vehicle_id !== Number(vehicle)) throw new Error("CUSTODY_WRONG_VEHICLE");
  return record;
};
export async function getCurrentHandoff(fetch: AuthorizedFetch, vehicle: string, signal?: AbortSignal) {
  const value = await fetch(root(vehicle) + "/current", {cache: "no-store", signal});
  return value == null ? null : validateRecord(value, vehicle);
}
export async function sendHandoff(fetch: AuthorizedFetch, vehicle: string, body: {
  request_id: string; target_driver_id: number; expected_context_revision: number;
  expected_stock_snapshot: string;
}): Promise<HandoffRecord> {
  uuid.parse(body.request_id);
  if (!/^[a-f0-9]{64}$/.test(body.expected_stock_snapshot)) throw Error("CUSTODY_STOCK_SNAPSHOT_STALE");
  return validateRecord(await fetch(root(vehicle), post(body)), vehicle);
}
export async function cancelHandoff(fetch: AuthorizedFetch, vehicle: string, handoff: string, id: string) {
  uuid.parse(handoff); uuid.parse(id);
  return validateRecord(await fetch(root(vehicle) + "/" + handoff + "/cancel", post({request_id: id})), vehicle);
}
const commitSchema = z.object({
  vehicle_id: vehicleId, epoch_id: vehicleId, context_revision: z.number().int(),
  state: z.enum(["ACCEPTED", "COMMITTED"]), replayed: z.boolean().optional(),
  stock_movements: z.literal(0),
});
/** Approvals never use a receiver proof in client JSON. */
export async function approveHandoff(fetch: AuthorizedFetch, vehicle: string, handoff: string, id: string):
  Promise<Receipt> {
  uuid.parse(handoff); uuid.parse(id);
  const raw = await fetch(root(vehicle) + "/" + handoff + "/approve", post({request_id: id}));
  const shape = z.object({receipt: z.unknown()}).passthrough().safeParse(raw);
  const parsed = commitSchema.parse(shape.success && shape.data.receipt != null ? shape.data.receipt : raw);
  if (parsed.vehicle_id !== Number(vehicle)) throw Error("CUSTODY_WRONG_VEHICLE");
  return {...parsed, state: "ACCEPTED", replayed: parsed.replayed ?? false};
}

const historyRowSchema = z.object({
  recipient_label: z.string().nullable().optional(),
  custodian_label: z.string().nullable().optional(),
  manager_label: z.string().nullable().optional(),
  approved_by_label: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  accepted_at: z.string().nullable().optional(),
  ended_at: z.string().nullable().optional(),
  evidence_origin: z.string().nullable().optional(),
  state: z.string().nullable().optional(),
}).passthrough();
export type HandoffHistoryRow = z.infer<typeof historyRowSchema>;
export async function loadCustodyHistory(fetch: AuthorizedFetch, vehicle: string, signal?: AbortSignal):
  Promise<HandoffHistoryRow[]> {
  const raw = await fetch(`/vehicles/${vehicle}/custody/history?limit=20`, {cache:"no-store", signal});
  const obj = z.object({items:z.unknown().optional(), entries:z.unknown().optional(),
    history:z.unknown().optional()}).passthrough().safeParse(raw);
  const list = Array.isArray(raw) ? raw :
    obj.success ? (obj.data.items ?? obj.data.entries ?? obj.data.history) : undefined;
  return z.array(historyRowSchema).max(20).parse(list);
}
