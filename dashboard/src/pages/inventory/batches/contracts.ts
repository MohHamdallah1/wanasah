export type BatchDisposition =
  | "RELEASED"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED";

export type BatchDispositionMutation = {
  batch_id: number;
  product_variant_id: number;
  batch_number: string;
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

  const batchNumber = row.batch_number;
  const reason = row.disposition_reason;
  const updatedAt = row.updated_at;
  if (
    typeof batchNumber !== "string" ||
    !batchNumber.trim() ||
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
    disposition_reason: reason,
    disposition_revision: positiveInt(
      row.disposition_revision,
    ),
    updated_at: updatedAt,
  };
}
