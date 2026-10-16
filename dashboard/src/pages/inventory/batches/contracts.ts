import { parsePublicBatchNumber } from "../publicBatchNumber";

export type BatchDisposition =
  | "RELEASED"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED";

export type BatchActionSnapshot = {
  batch_id: number;
  batch_number: string | null;
  production_date: string | null;
  expiry_date: string | null;
  disposition: BatchDisposition;
  disposition_reason: string | null;
  disposition_revision: number;
  allowed_disposition_targets: BatchDisposition[];
  days_to_expiry: number | null;
};

export type BatchDispositionMutation = {
  batch_id: number;
  product_variant_id: number;
  batch_number: string | null;
  disposition: BatchDisposition;
  disposition_reason: string | null;
  disposition_revision: number;
  updated_at: string;
};

const invalid = (): never => {
  const error = new Error(
    "BATCH_DISPOSITION_RESPONSE_INVALID",
  ) as Error & { code: string };
  error.code =
    "BATCH_DISPOSITION_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown) =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0
    ? value
    : invalid();

export function parseBatchDispositionMutation(
  raw: unknown,
): BatchDispositionMutation {
  if (
    raw === null ||
    typeof raw !== "object" ||
    Array.isArray(raw)
  ) {
    return invalid();
  }

  const row = raw as Record<string, unknown>;
  const disposition = row.disposition;
  if (
    disposition !== "RELEASED" &&
    disposition !== "QUARANTINED" &&
    disposition !== "BLOCKED" &&
    disposition !== "RECALLED"
  ) {
    return invalid();
  }

  const batchNumber = parsePublicBatchNumber(row.batch_number, invalid);
  const reason = row.disposition_reason;
  const updatedAt = row.updated_at;
  if (
    (reason !== null &&
      typeof reason !== "string") ||
    typeof updatedAt !== "string" ||
    !updatedAt.trim()
  ) {
    return invalid();
  }

  return {
    batch_id: positiveInt(row.batch_id),
    product_variant_id: positiveInt(
      row.product_variant_id,
    ),
    batch_number: batchNumber,
    disposition,
    disposition_reason: reason as string | null,
    disposition_revision: positiveInt(
      row.disposition_revision,
    ),
    updated_at: updatedAt,
  };
}
