import { z } from "zod";

export const line = z.object({
  product_name: z.string(), sku: z.string(), batch_number: z.string(),
  expiry_date: z.string().nullable(), base_uom: z.string(),
  base_uom_name: z.string().min(1), display_uom_name: z.string().nullable(),
  display_factor_to_base: z.string().regex(/^[1-9]\d*$/).nullable(),
  stock_status: z.string(), on_hand_base: z.string(), reserved_base: z.string(),
}).strict();
const stock = z.array(line).max(1000);
const hex = z.string().regex(/^[a-f0-9]{64}$/);
export const readiness = z.object({
  vehicle_id: z.number(), vehicle_location_id: z.number(),
  context_revision: z.number().int(), state: z.string(),
  custodian_kind: z.string().nullable(), stocked: z.boolean(),
  stock_snapshot: hex, stock_line_count: z.number().int(),
  recovery_action: z.enum(["CUSTODY_FIRST_ACCEPT","CUSTODY_REASSIGN","CUSTODY_INVESTIGATE"]),
});
export const review = z.object({
  vehicle_id: z.number(), context_revision: z.number().int(),
  stock_snapshot: hex, stock_lines: stock,
});
export const offer = z.object({
  offer_token: z.string().min(50), expires_in_seconds: z.number().int(),
  action: z.enum(["FIRST_ACCEPT","REASSIGN"]),
  stock_snapshot: hex, stock_line_count: z.number().int(),
  vehicle_location_id: z.number(),
});
export const accepted = z.object({
  vehicle_id: z.number(), epoch_id: z.number(), context_revision: z.number(),
  state: z.literal("ACCEPTED"), replayed: z.boolean(), stock_movements: z.literal(0),
});
export const lookup = z.discriminatedUnion("state",[
  z.object({state:z.literal("UNKNOWN")}),
  z.object({state:z.literal("COMMITTED"),context_revision:z.number(),epoch_id:z.number()}),
]);
export type Readiness=z.infer<typeof readiness>;
export type StockReview=z.infer<typeof review>;
export type StockLine=z.infer<typeof line>;
export type Offer=z.infer<typeof offer>;
export type Receipt=z.infer<typeof accepted>;
