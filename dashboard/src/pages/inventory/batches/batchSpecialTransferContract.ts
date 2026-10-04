export type BatchSpecialTransferPurpose =
  | "QUARANTINE"
  | "RECALL_RETURN"
  | "RETURN_TO_VENDOR"
  | "DISPOSAL";

export type BatchSpecialTransferResult = {
  transfer_reference: string;
  header_id: number;
  transfer_purpose: BatchSpecialTransferPurpose;
  source_location_id: number;
  destination_location_id: number;
};

const invalid = (): never => {
  const error = new Error(
    "BATCH_SPECIAL_TRANSFER_RESPONSE_INVALID",
  ) as Error & { code: string };
  error.code = "BATCH_SPECIAL_TRANSFER_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown) =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0
    ? value
    : invalid();

export function parseBatchSpecialTransferResult(
  raw: unknown,
): BatchSpecialTransferResult {
  if (
    !raw ||
    typeof raw !== "object" ||
    Array.isArray(raw)
  ) {
    return invalid();
  }
  const row = raw as Record<string, unknown>;
  const purpose = row.transfer_purpose;
  if (
    purpose !== "QUARANTINE" &&
    purpose !== "RECALL_RETURN" &&
    purpose !== "RETURN_TO_VENDOR" &&
    purpose !== "DISPOSAL"
  ) {
    return invalid();
  }
  if (
    typeof row.transfer_reference !== "string" ||
    !row.transfer_reference.trim() ||
    row.transfer_reference.length > 200
  ) {
    return invalid();
  }
  return {
    transfer_reference: row.transfer_reference,
    header_id: positiveInt(row.header_id),
    transfer_purpose: purpose,
    source_location_id: positiveInt(row.source_location_id),
    destination_location_id: positiveInt(
      row.destination_location_id,
    ),
  };
}
