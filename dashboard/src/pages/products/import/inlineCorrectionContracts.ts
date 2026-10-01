import { IMPORT_MAPPING_FIELDS, type ImportMappingField } from "@/pages/products/import/importFields";

export const MAX_INLINE_CORRECTION_REJECTIONS = 25;
export const MAX_INLINE_CORRECTION_BODY_BYTES = 256 * 1024;

export type InlineCorrectionError = {
  code: string | null;
  field: string | null;
};

export type InlineCorrectionRow = {
  row_identity: string;
  row_number: number;
  version: number;
  status: "INVALID" | "IMPORT_FAILED";
  values: Partial<Record<ImportMappingField, string | number | boolean | null>>;
  errors: InlineCorrectionError[];
  editable: boolean;
  unavailable_reason: string | null;
};

export type InlineCorrectionPage = {
  job_id: string;
  job_version: number;
  fields: ImportMappingField[];
  items: InlineCorrectionRow[];
  next_after_row: number | null;
};

export type InlineCorrectionPatch = {
  row_identity: string;
  expected_version: number;
  values: Partial<Record<ImportMappingField, string | null>>;
};

export type InlineCorrectionIntent = {
  jobId: string;
  expected_job_version: number;
  rows: InlineCorrectionPatch[];
};

export type InlineCorrectionAck = {
  job_id: string;
  status: "VALIDATING";
  corrected_rows: number;
  replayed: boolean;
};

const KNOWN_FIELDS = new Set<string>(IMPORT_MAPPING_FIELDS);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function fail(): never {
  throw new Error("PRODUCT_IMPORT_INLINE_RESPONSE_INVALID");
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail();
  return value as Record<string, unknown>;
}
function positiveInt(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 1) return fail();
  return value as number;
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !UUID.test(value)) return fail();
  return value;
}

/** Validate the entire bounded server projection before any cells become editable. */
export function parseInlineCorrectionPage(
  raw: unknown, jobId: string,
): InlineCorrectionPage {
  const page = object(raw);
  if (uuid(page.job_id) !== jobId) return fail();
  const jobVersion = positiveInt(page.job_version);
  if (!Array.isArray(page.fields) || page.fields.length > IMPORT_MAPPING_FIELDS.length) return fail();
  const fields: ImportMappingField[] = page.fields.map((field: unknown) => {
    if (typeof field !== "string" || !KNOWN_FIELDS.has(field)) return fail();
    return field as ImportMappingField;
  });
  if (new Set(fields).size !== fields.length) return fail();
  if (!Array.isArray(page.items) || page.items.length > MAX_INLINE_CORRECTION_REJECTIONS) return fail();
  const rows: InlineCorrectionRow[] = [];
  let previous = 1;
  const seen = new Set<string>();
  for (const rawRow of page.items) {
    const row = object(rawRow);
    const rowIdentity = uuid(row.row_identity);
    const rowNumber = positiveInt(row.row_number);
    const version = positiveInt(row.version);
    if (rowNumber < 2 || rowNumber <= previous || seen.has(rowIdentity)) return fail();
    if (row.status !== "INVALID" && row.status !== "IMPORT_FAILED") return fail();
    if (typeof row.editable !== "boolean") return fail();
    if (row.unavailable_reason !== null && typeof row.unavailable_reason !== "string") return fail();
    const values = object(row.values);
    const allowed = new Set(fields);
    if (Object.keys(values).some((field) => !allowed.has(field as ImportMappingField))) return fail();
    for (const value of Object.values(values)) {
      if (value !== null && typeof value !== "string" && typeof value !== "boolean" &&
          !(typeof value === "number" && Number.isFinite(value))) return fail();
    }
    if (!Array.isArray(row.errors) || row.errors.length > 20) return fail();
    const errors = row.errors.map((item: unknown) => {
      const error = object(item);
      if ((error.code !== null && typeof error.code !== "string") ||
          (error.field !== null && typeof error.field !== "string")) return fail();
      return { code: error.code as string | null, field: error.field as string | null };
    });
    rows.push({
      row_identity: rowIdentity,
      row_number: rowNumber,
      version,
      status: row.status,
      values: values as InlineCorrectionRow["values"],
      errors,
      editable: row.editable,
      unavailable_reason: row.unavailable_reason as string | null,
    });
    previous = rowNumber;
    seen.add(rowIdentity);
  }
  if (page.next_after_row !== null &&
      (!Number.isSafeInteger(page.next_after_row) || (page.next_after_row as number) < previous)) return fail();
  return {
    job_id: jobId,
    job_version: jobVersion,
    fields,
    items: rows,
    next_after_row: page.next_after_row as number | null,
  };
}

export function parseInlineCorrectionAck(raw: unknown, jobId: string): InlineCorrectionAck {
  const ack = object(raw);
  if (ack.job_id !== jobId || ack.status !== "VALIDATING" ||
      !Number.isSafeInteger(ack.corrected_rows) || (ack.corrected_rows as number) < 1 ||
      (ack.corrected_rows as number) > MAX_INLINE_CORRECTION_REJECTIONS ||
      typeof ack.replayed !== "boolean") return fail();
  return ack as InlineCorrectionAck;
}

export function formatInlineValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(value);
}
