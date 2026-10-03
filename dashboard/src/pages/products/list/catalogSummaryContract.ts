import { z } from "zod";

const count = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const schema = z.object({
  schema_version: z.literal(1),
  company_id: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
  total: count,
  families: count,
  available: count,
  retiring: count,
  archived: count,
  sales_restricted: count,
}).refine((value) =>
  value.available + value.retiring + value.archived <= value.total &&
  value.sales_restricted <= value.total,
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
