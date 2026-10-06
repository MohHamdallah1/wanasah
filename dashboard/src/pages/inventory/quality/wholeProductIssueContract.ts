import {
  parseQualityInventorySummary,
  type QualityInventorySummary,
} from "@/features/inventory/quality/qualityInventorySummaryContract";
import {
  parseBatchStockSources,
  type BatchStockSources,
} from "../batches/batchStockSourcesContract";

export type WholeProductIssueSourcesPage = {
  product_variant_id: number;
  variant_version: number;
  operational_hold: "RECALL";
  base_uom_id: number;
  base_uom_code: string;
  inventory_summary: QualityInventorySummary;
  batches: BatchStockSources[];
  next_cursor: number | null;
  has_more: boolean;
  ready_to_resume_sales: boolean;
  company_requirements_remaining: boolean;
};

const invalid = (): never => {
  const error = new Error("WHOLE_PRODUCT_ISSUE_RESPONSE_INVALID") as Error & { code: string };
  error.code = "WHOLE_PRODUCT_ISSUE_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) return invalid();
  return value;
};

export function parseWholeProductIssueSourcesPage(raw: unknown): WholeProductIssueSourcesPage {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const variantId = positiveInt(row.product_variant_id);
  const version = positiveInt(row.variant_version);
  const baseUomId = positiveInt(row.base_uom_id);
  if (
    row.operational_hold !== "RECALL" ||
    typeof row.base_uom_code !== "string" ||
    !row.base_uom_code.trim() ||
    row.base_uom_code.length > 20 ||
    !Array.isArray(row.batches) ||
    row.batches.length > 50 ||
    typeof row.has_more !== "boolean" ||
    typeof row.ready_to_resume_sales !== "boolean" ||
    typeof row.company_requirements_remaining !== "boolean"
  ) return invalid();

  let inventorySummary: QualityInventorySummary;
  let batches: BatchStockSources[];
  try {
    inventorySummary = parseQualityInventorySummary(row.inventory_summary);
    batches = row.batches.map((item) => parseBatchStockSources(item));
  } catch {
    return invalid();
  }
  const seen = new Set<number>();
  for (const batch of batches) {
    if (
      batch.product_variant_id !== variantId ||
      batch.base_uom_id !== baseUomId ||
      batch.base_uom_code !== row.base_uom_code.trim() ||
      batch.operational_hold !== "RECALL" ||
      seen.has(batch.batch_id)
    ) return invalid();
    seen.add(batch.batch_id);
  }

  const nextCursor = row.next_cursor === null ? null : positiveInt(row.next_cursor);
  if (
    (row.has_more && nextCursor === null) ||
    (!row.has_more && nextCursor !== null) ||
    row.ready_to_resume_sales === row.company_requirements_remaining
  ) return invalid();

  return {
    product_variant_id: variantId,
    variant_version: version,
    operational_hold: "RECALL",
    base_uom_id: baseUomId,
    base_uom_code: row.base_uom_code.trim(),
    inventory_summary: inventorySummary,
    batches,
    next_cursor: nextCursor,
    has_more: row.has_more,
    ready_to_resume_sales: row.ready_to_resume_sales,
    company_requirements_remaining: row.company_requirements_remaining,
  };
}
