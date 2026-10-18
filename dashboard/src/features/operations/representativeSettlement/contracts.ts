import { z } from "zod";

const quantity = z.string().min(1);
const nullableText = z.string().nullable();

export const custodyLineSchema = z.object({
  line_key: z.string().length(24),
  product_name: z.string().min(1),
  sku: z.string(),
  batch_number: nullableText,
  expiry_date: nullableText,
  stock_status: z.string().min(1),
  uom: z.string().min(1),
  expected_quantity: quantity,
});

export const custodySnapshotSchema = z.object({
  work_session_id: z.number().int().positive(),
  vehicle_location_id: z.number().int().positive(),
  inventory_reconciled: z.boolean(),
  custody_received: z.boolean(),
  review_required: z.boolean(),
  reconciliation_reference: nullableText,
  lines: z.array(custodyLineSchema),
});

export const custodyReceiveResultSchema = z.object({
  status: z.string(),
  review_required: z.boolean().optional(),
  inventory_reconciled: z.boolean().optional(),
  reconciliation_reference: nullableText.optional(),
  requires_independent_recount: z.boolean().optional(),
  movement_count: z.number().int().nonnegative().optional(),
  financial_ready: z.boolean().optional(),
});

export const varianceLineSchema = z.object({
  product_name: z.string().min(1),
  batch_number: nullableText,
  stock_status: z.string().min(1),
  uom: z.string().min(1),
  expected_quantity: quantity,
  actual_quantity: quantity,
  variance_quantity: quantity,
  expiry_date: nullableText,
});

export const varianceReviewSchema = z.object({
  status: z.string(),
  reconciliation_reference: z.string().nullable().optional(),
  independent_recount_satisfied: z.boolean(),
  requires_independent_recount: z.boolean(),
  attempt_number: z.number().int().positive(),
  lines: z.array(varianceLineSchema),
});

export const recountSheetLineSchema = z.object({
  line_key: z.string().length(24),
  product_name: z.string().min(1),
  stock_status: z.string().min(1),
  batch_number: nullableText,
  expiry_date: nullableText,
  uom: z.string().min(1),
});

export const recountSheetSchema = z.object({
  status: z.string(),
  reconciliation_reference: z.string().nullable().optional(),
  lines: z.array(recountSheetLineSchema),
});

export const warehousePageSchema = z.object({
  items: z.array(z.object({
    id: z.number().int().positive(),
    name: z.string().min(1),
    code: z.string().min(1),
  })),
  next_cursor: z.string().nullable(),
  has_more: z.boolean(),
  total: z.number().int().nonnegative().nullable(),
});

export type CustodyLine = z.infer<typeof custodyLineSchema>;
export type CustodySnapshot = z.infer<typeof custodySnapshotSchema>;
export type CustodyReceiveResult = z.infer<typeof custodyReceiveResultSchema>;
export type VarianceReview = z.infer<typeof varianceReviewSchema>;
export type RecountSheet = z.infer<typeof recountSheetSchema>;
export type ReceivingWarehouse = z.infer<typeof warehousePageSchema>["items"][number];

export interface CustodyCountInput {
  line_key: string;
  actual_quantity: string;
}
