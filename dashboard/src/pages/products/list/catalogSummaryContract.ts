import { z } from "zod";

const count = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const schema = z.object({
  schema_version: z.literal(2),
  company_id: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
  total: count,
  families: count,
  available: count,
  stopped: count,
  archived: count,
}).refine((value) =>
  value.available + value.stopped + value.archived === value.total,
);

export type CatalogSummary = z.infer<typeof schema>;

export function parseCatalogSummary(value: unknown, companyId: number): CatalogSummary {
  const parsed = schema.safeParse(value);
  if (!parsed.success || parsed.data.company_id !== companyId) {
    throw Object.assign(new Error("SIMPLE_PRODUCT_SUMMARY_CONTRACT_INVALID"), {
      code: "SIMPLE_PRODUCT_SUMMARY_CONTRACT_INVALID",
    });
  }
  return parsed.data;
}
