import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  apiErrorCode,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";

const XLSX_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const decimalText = (value: unknown): string => {
  if (
    typeof value !== "string" ||
    !/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value)
  ) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return value;
};

const hex64 = (value: unknown): string => {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{64}$/.test(value)
  ) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return value;
};

const objectRecord = (raw: unknown): Record<string, unknown> => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return raw as Record<string, unknown>;
};

export interface OpeningValuationTemplateArtifact {
  file_name: string;
  content_type: typeof XLSX_CONTENT_TYPE;
  content_base64: string;
  row_count: number;
  snapshot_hash: string;
  currency_code: string;
  method: "FIFO" | "MOVING_AVERAGE";
  total_quantity: string;
}

export const parseOpeningValuationTemplateArtifact = (
  raw: unknown,
): OpeningValuationTemplateArtifact => {
  const record = objectRecord(raw);
  if (
    record.file_name !== "inventory-opening-valuation.xlsx" ||
    record.content_type !== XLSX_CONTENT_TYPE ||
    typeof record.content_base64 !== "string" ||
    record.content_base64.length === 0 ||
    !Number.isInteger(record.row_count) ||
    Number(record.row_count) <= 0 ||
    typeof record.currency_code !== "string" ||
    !/^[A-Z]{3,10}$/.test(record.currency_code) ||
    (record.method !== "FIFO" && record.method !== "MOVING_AVERAGE")
  ) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return {
    file_name: record.file_name,
    content_type: XLSX_CONTENT_TYPE,
    content_base64: record.content_base64,
    row_count: Number(record.row_count),
    snapshot_hash: hex64(record.snapshot_hash),
    currency_code: record.currency_code,
    method: record.method,
    total_quantity: decimalText(record.total_quantity),
  };
};

export const saveOpeningValuationTemplate = (
  artifact: OpeningValuationTemplateArtifact,
): void => {
  let binary: string;
  try {
    binary = window.atob(artifact.content_base64);
  } catch {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const href = URL.createObjectURL(
    new Blob([bytes], { type: artifact.content_type }),
  );
  try {
    const link = document.createElement("a");
    link.href = href;
    link.download = artifact.file_name;
    link.click();
  } finally {
    URL.revokeObjectURL(href);
  }
};

export interface OpeningValuationPreviewItem {
  sku: string;
  name: string;
  base_uom_code: string;
  base_uom_name: string;
  quantity: string;
  unit_cost: string;
  total_value: string;
}

export interface OpeningValuationPreview {
  snapshot_hash: string;
  currency_code: string;
  line_count: number;
  total_quantity: string;
  total_value: string;
  zero_cost_count: number;
  items: OpeningValuationPreviewItem[];
}

export const parseOpeningValuationPreview = (
  raw: unknown,
): OpeningValuationPreview => {
  const record = objectRecord(raw);
  if (
    typeof record.currency_code !== "string" ||
    !/^[A-Z]{3,10}$/.test(record.currency_code) ||
    !Number.isInteger(record.line_count) ||
    Number(record.line_count) <= 0 ||
    !Number.isInteger(record.zero_cost_count) ||
    Number(record.zero_cost_count) < 0 ||
    !Array.isArray(record.items)
  ) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  const items = record.items.map((rawItem) => {
    const item = objectRecord(rawItem);
    if (
      typeof item.sku !== "string" ||
      !item.sku.trim() ||
      typeof item.name !== "string" ||
      typeof item.base_uom_code !== "string" ||
      typeof item.base_uom_name !== "string"
    ) {
      throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
    }
    return {
      sku: item.sku,
      name: item.name,
      base_uom_code: item.base_uom_code,
      base_uom_name: item.base_uom_name,
      quantity: decimalText(item.quantity),
      unit_cost: decimalText(item.unit_cost),
      total_value: decimalText(item.total_value),
    };
  });
  if (items.length !== Number(record.line_count)) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return {
    snapshot_hash: hex64(record.snapshot_hash),
    currency_code: record.currency_code,
    line_count: Number(record.line_count),
    total_quantity: decimalText(record.total_quantity),
    total_value: decimalText(record.total_value),
    zero_cost_count: Number(record.zero_cost_count),
    items,
  };
};

export interface OpeningValuationFinalizeResult {
  message: "OPENING_VALUATION_POSTED";
  method: "FIFO" | "MOVING_AVERAGE";
  currency_code: string;
  snapshot_hash: string;
  line_count: number;
  total_quantity: string;
  total_value: string;
  zero_cost_count: number;
  policy_version: number;
}

export const parseOpeningValuationFinalizeResult = (
  raw: unknown,
): OpeningValuationFinalizeResult => {
  const record = objectRecord(raw);
  if (
    record.message !== "OPENING_VALUATION_POSTED" ||
    (record.method !== "FIFO" && record.method !== "MOVING_AVERAGE") ||
    typeof record.currency_code !== "string" ||
    !/^[A-Z]{3,10}$/.test(record.currency_code) ||
    !Number.isInteger(record.line_count) ||
    Number(record.line_count) <= 0 ||
    !Number.isInteger(record.zero_cost_count) ||
    Number(record.zero_cost_count) < 0 ||
    !Number.isInteger(record.policy_version) ||
    Number(record.policy_version) <= 0
  ) {
    throw new Error("OPENING_VALUATION_RESPONSE_INVALID");
  }
  return {
    message: "OPENING_VALUATION_POSTED",
    method: record.method,
    currency_code: record.currency_code,
    snapshot_hash: hex64(record.snapshot_hash),
    line_count: Number(record.line_count),
    total_quantity: decimalText(record.total_quantity),
    total_value: decimalText(record.total_value),
    zero_cost_count: Number(record.zero_cost_count),
    policy_version: Number(record.policy_version),
  };
};

export interface OpeningValuationFinalizePayload {
  snapshot_hash: string;
  lines: Array<{ sku: string; unit_cost: string }>;
  confirm_zero_costs: boolean;
}

export const finalizePayloadFromPreview = (
  preview: OpeningValuationPreview,
  confirmZeroCosts: boolean,
): OpeningValuationFinalizePayload => ({
  snapshot_hash: preview.snapshot_hash,
  lines: preview.items.map((item) => ({
    sku: item.sku,
    unit_cost: item.unit_cost,
  })),
  confirm_zero_costs: confirmZeroCosts,
});

export const openingValuationScope = (
  companyId: number,
  actorId: number,
) =>
  durableScope(
    companyId,
    actorId,
    "inventory-opening-valuation-v1",
    "company",
  );

export const readPendingOpeningValuation = async (
  companyId: number,
  actorId: number,
): Promise<DurableCommand<OpeningValuationFinalizePayload> | null> =>
  readDurableCommand<OpeningValuationFinalizePayload>(
    openingValuationScope(companyId, actorId),
  );

export const executeOpeningValuationFinalize = async ({
  companyId,
  actorId,
  payload,
  authenticatedFetch,
}: {
  companyId: number;
  actorId: number;
  payload?: OpeningValuationFinalizePayload;
  authenticatedFetch: (
    url: string,
    opts?: RequestInit,
  ) => Promise<unknown>;
}): Promise<unknown> => {
  const scope = openingValuationScope(companyId, actorId);
  const existing =
    await readDurableCommand<OpeningValuationFinalizePayload>(scope);
  const command = payload
    ? await getOrCreateDurableCommand(scope, payload)
    : existing;
  if (!command) {
    throw Object.assign(new Error(), {
      code: "DURABLE_OPERATION_CORRUPT",
    });
  }
  try {
    const result = parseOpeningValuationFinalizeResult(
      await authenticatedFetch(
        "/warehouse/costing/opening-valuation/finalize",
        {
          method: "POST",
          body: JSON.stringify({
            request_id: command.requestId,
            ...command.payload,
          }),
        },
      ),
    );
    completeDurableOperation(scope, command.requestId);
    return result;
  } catch (error) {
    const outcomeIsUncertain =
      isAmbiguousRequestError(error) ||
      apiErrorCode(error) === "OPENING_VALUATION_RESPONSE_INVALID";
    if (!outcomeIsUncertain) {
      abandonDurableOperation(scope);
    }
    throw error;
  }
};

export const isOpeningValuationError = (
  error: unknown,
  code: string,
) => apiErrorCode(error) === code;
