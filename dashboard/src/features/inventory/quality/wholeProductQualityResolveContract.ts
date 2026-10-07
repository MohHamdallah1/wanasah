import { z } from "zod";

export type WholeProductQualityAction = "DISPOSE" | "RETURN_TO_VENDOR";
export type WholeProductPostResolutionHold = "NONE" | "SALES_HOLD";

const positiveId = z.number().int().positive().max(2_147_483_647);
const resultSchema = z.object({
  message: z.string().min(1),
  action: z.enum(["DISPOSE", "RETURN_TO_VENDOR"]),
  product_variant_id: positiveId,
  total_quantity: z.string().regex(/^\d+(?:\.\d{1,6})?$/),
  location_count: z.number().int().min(1).max(100),
  post_resolution_hold: z.enum(["NONE", "SALES_HOLD"]),
  locations: z.array(z.object({
    location_id: positiveId,
    location_name: z.string().min(1),
    quantity: z.string().regex(/^\d+(?:\.\d{1,6})?$/),
  })).min(1).max(100),
});

export function parseWholeProductQualityResult(
  raw: unknown,
  productId: number,
  action: WholeProductQualityAction,
  postResolutionHold: WholeProductPostResolutionHold,
) {
  const parsed = resultSchema.safeParse(raw);
  if (
    !parsed.success
    || parsed.data.product_variant_id !== productId
    || parsed.data.action !== action
    || parsed.data.post_resolution_hold !== postResolutionHold
    || parsed.data.location_count !== parsed.data.locations.length
    || new Set(parsed.data.locations.map((row) => row.location_id)).size !== parsed.data.locations.length
  ) {
    throw Object.assign(new Error(), { code: "PRODUCT_QUALITY_COMMAND_RESPONSE_INVALID" });
  }
  return parsed.data;
}
