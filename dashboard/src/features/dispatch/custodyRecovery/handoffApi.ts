import { z } from "zod";
import type { AuthorizedFetch } from "./command";
import type { Receipt } from "./contract";

const uuid = z.string().uuid();
const positiveId = z.number().int().positive().refine(Number.isSafeInteger);
const states = z.enum(["PENDING","CONFIRMED","DECLINED","CANCELLED","EXPIRED","COMMITTED"]);
const currentSchema = z.object({
  handoff_id: positiveId, vehicle_id: positiveId,
  state: states, target_driver_id: positiveId,
  recipient_label: z.string().min(1), expires_at: z.string().min(1),
  context_revision: z.number().int().nonnegative(),
  reason_code: z.string().nullable().optional(),
  reason_text: z.string().nullable().optional(),
}).passthrough();

export type HandoffRecord = z.infer<typeof currentSchema>;
export type HandoffState = HandoffRecord["state"];
const root = (vehicle: string) => {
  if (!/^[1-9][0-9]*$/.test(vehicle) ||
      !Number.isSafeInteger(Number(vehicle))) throw Error("CUSTODY_INVALID_VEHICLE");
  return `/vehicles/${vehicle}/custody/handoffs`;
};
const post = (body: unknown): RequestInit => ({
  method: "POST", cache:"no-store",
  headers: {"Content-Type":"application/json"}, body:JSON.stringify(body),
});
const validateRecord = (raw: unknown, vehicle: string): HandoffRecord => {
  const record=currentSchema.parse(raw);
  if(record.vehicle_id!==Number(vehicle))throw Error("CUSTODY_WRONG_VEHICLE");
  return record;
};
export async function getCurrentHandoff(fetch: AuthorizedFetch, vehicle: string, signal?: AbortSignal) {
  const value=await fetch(root(vehicle)+"/current",{cache:"no-store",signal});
  return value==null?null:validateRecord(value,vehicle);
}
export async function sendHandoff(fetch: AuthorizedFetch, vehicle: string, body: {
  request_id:string;target_driver_id:number;expected_context_revision:number;
  expected_stock_snapshot:string;
}):Promise<HandoffRecord>{
  uuid.parse(body.request_id);
  positiveId.parse(body.target_driver_id);
  z.number().int().nonnegative().parse(body.expected_context_revision);
  if(!/^[a-f0-9]{64}$/.test(body.expected_stock_snapshot))throw Error("CUSTODY_STOCK_SNAPSHOT_STALE");
  return validateRecord(await fetch(root(vehicle),post(body)),vehicle);
}
export async function cancelHandoff(fetch:AuthorizedFetch,vehicle:string,handoff:number,id:string){
  positiveId.parse(handoff);uuid.parse(id);
  return validateRecord(await fetch(root(vehicle)+"/"+handoff+"/cancel",post({request_id:id})),vehicle);
}
const commitSchema=z.object({
  vehicle_id:positiveId, handoff_id:positiveId, epoch_id:positiveId,
  context_revision:z.number().int().nonnegative(),
  state:z.literal("COMMITTED"), replayed:z.boolean(),
  stock_movements:z.literal(0),
});
/** Approval never sends a FIELD HMAC proof, and only a real committed epoch counts. */
export async function approveHandoff(
  fetch:AuthorizedFetch,vehicle:string,handoff:number,id:string,
):Promise<Receipt>{
  positiveId.parse(handoff);uuid.parse(id);
  const raw=await fetch(root(vehicle)+"/"+handoff+"/approve",post({request_id:id}));
  const parsed=commitSchema.parse(raw);
  if(parsed.vehicle_id!==Number(vehicle)||parsed.handoff_id!==handoff)
    throw Error("CUSTODY_RECEIPT_MISMATCH");
  return {state:"ACCEPTED",vehicle_id:parsed.vehicle_id,epoch_id:parsed.epoch_id,
    context_revision:parsed.context_revision,replayed:parsed.replayed,stock_movements:0};
}
const historyRowSchema=z.object({
  epoch_id:positiveId,
  state:z.string(),
  recipient_label:z.string().nullable().optional(),
  approved_by_label:z.string().nullable().optional(),
  started_at:z.string().nullable().optional(),
  ended_at:z.string().nullable().optional(),
  legacy_review_logged_at:z.string().nullable().optional(),
  evidence_origin:z.string().nullable().optional(),
  legacy_unconfirmed:z.boolean().optional(),
}).passthrough();
export type HandoffHistoryRow=z.infer<typeof historyRowSchema>;
export async function loadCustodyHistory(
  fetch:AuthorizedFetch,vehicle:string,signal?:AbortSignal,
):Promise<HandoffHistoryRow[]>{
  const raw=await fetch(`/vehicles/${vehicle}/custody/history?limit=20`,{cache:"no-store",signal});
  const response=z.object({vehicle_id:positiveId,items:z.array(historyRowSchema).max(20)}).parse(raw);
  if(response.vehicle_id!==Number(vehicle))throw Error("CUSTODY_WRONG_VEHICLE");
  return response.items;
}
