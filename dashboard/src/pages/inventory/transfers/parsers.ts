import { isTransferPurpose, isTransferStatus } from "./constants";
import { parseQuantity } from "../quantity";
import { parsePublicBatchNumber } from "../publicBatchNumber";
import { parsePublicBatchDate } from "../publicBatchDate";
import type {
  TransferBatchOptions,
  TransferLocationOption,
  TransferOverrideBatch,
  TransferOverrideOptions,
  TransferOverrideReason,
  TransferSourceInventoryItem,
  TransferSourceInventoryPage,
  WarehouseTransferCursorPage,
  WarehouseTransferDetail,
  WarehouseTransferLine,
  WarehouseTransferListItem,
} from "./types";

const invalid = (field = "response") => Object.assign(new Error(), { code: "TRANSFER_RESPONSE_INVALID", context: { field } });

const positiveInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value <= 0
  ) {
    throw invalid(field);
  }
  return value;
};

const nonNegativeInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw invalid(field);
  }
  return value;
};

const requiredString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || !value) {
    throw invalid(field);
  }
  return value;
};

const optionalString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;
const publicBatchNumber = (value: unknown, field: string): string | null =>
  parsePublicBatchNumber(value, () => {
    throw invalid(field);
  });


const optionalPositiveInt = (value: unknown): number | null =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value > 0
    ? value
    : null;

const parseTransfer = (raw: unknown): WarehouseTransferListItem => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  if (!isTransferPurpose(row.transfer_purpose)) throw invalid("transfer_purpose");
  if (!isTransferStatus(row.status)) {
    throw invalid();
  }

  return {
    id: positiveInt(row.id, "id"),
    reference_number: requiredString(
      row.reference_number,
      "reference_number"
    ),
    source_location_id: positiveInt(
      row.source_location_id,
      "source_location_id"
    ),
    source_location_name: requiredString(
      row.source_location_name,
      "source_location_name"
    ),
    destination_location_id: positiveInt(
      row.destination_location_id,
      "destination_location_id"
    ),
    destination_location_name: requiredString(
      row.destination_location_name,
      "destination_location_name"
    ),
    status: row.status,
    transfer_purpose: row.transfer_purpose,
    dispatched_by: positiveInt(row.dispatched_by, "dispatched_by"),
    dispatched_by_name: requiredString(
      row.dispatched_by_name,
      "dispatched_by_name"
    ),
    received_by: optionalPositiveInt(row.received_by),
    received_by_name: optionalString(row.received_by_name),
    cancelled_by: optionalPositiveInt(row.cancelled_by),
    cancelled_by_name: optionalString(row.cancelled_by_name),
    line_count: nonNegativeInt(row.line_count, "line_count"),
    total_quantity: parseQuantity(
      row.total_quantity,
      "total_quantity",
      { allowZero: true }
    ),
    notes: optionalString(row.notes),
    decision_reason: optionalString(row.decision_reason),
    created_at: requiredString(row.created_at, "created_at"),
    updated_at: requiredString(row.updated_at, "updated_at"),
    accepted_at: optionalString(row.accepted_at),
    rejected_at: optionalString(row.rejected_at),
    cancelled_at: optionalString(row.cancelled_at),
    posted_at: optionalString(row.posted_at),
  };
};

export const parseTransferPage = (raw: unknown): WarehouseTransferCursorPage => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { items?: unknown }).items)
  ) {
    throw invalid();
  }

  const page = raw as Record<string, unknown>;

  return {
    items: (page.items as unknown[]).map(parseTransfer),
    next_cursor:
      typeof page.next_cursor === "string" ? page.next_cursor : null,
    has_more: page.has_more === true,
    total: typeof page.total === "number" ? page.total : null,
  };
};

const parseTransferLine = (raw: unknown): WarehouseTransferLine => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;

  return {
    id: positiveInt(row.id, "line.id"),
    product_variant_id: positiveInt(
      row.product_variant_id,
      "product_variant_id"
    ),
    product_name: requiredString(row.product_name, "product_name"),
    batch_id: positiveInt(row.batch_id, "batch_id"),
    batch_number: publicBatchNumber(row.batch_number, "batch_number"),
    expiry_date: parsePublicBatchDate(row.expiry_date, () => {
      throw invalid();
    }),
    quantity: parseQuantity(row.quantity, "quantity"),
    uom_id: positiveInt(row.uom_id, "uom_id"),
    fefo_override_reason_id: optionalPositiveInt(
      row.fefo_override_reason_id
    ),
    fefo_overridden_by: optionalPositiveInt(row.fefo_overridden_by),
    fefo_override_note: optionalString(row.fefo_override_note),
  };
};

export const parseTransferDetail = (
  raw: unknown
): WarehouseTransferDetail => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !("transfer" in raw) ||
    !("lines" in raw) ||
    !Array.isArray((raw as { lines?: unknown }).lines)
  ) {
    throw invalid();
  }

  const record = raw as Record<string, unknown>;
  const transfer = parseTransfer(record.transfer);

  const lines = (record.lines as unknown[]).map(parseTransferLine);
  if (lines.length === 0) {
    throw invalid();
  }

  return { transfer, lines };
};


const parseTransferLocation = (raw: unknown): TransferLocationOption => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  const locationType = row.location_type;
  if (locationType !== "WAREHOUSE" && locationType !== "VEHICLE") {
    throw invalid();
  }

  return {
    id: positiveInt(row.id, "location.id"),
    name: requiredString(row.name, "location.name"),
    code: requiredString(row.code, "location.code"),
    location_type: locationType,
    vehicle_id: optionalPositiveInt(row.vehicle_id),
  };
};

export const parseTransferLocations = (raw: unknown): TransferLocationOption[] => {
  if (!Array.isArray(raw)) {
    throw invalid();
  }

  return raw.map(parseTransferLocation);
};

const parseSourceInventoryItem = (
  raw: unknown
): TransferSourceInventoryItem => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;

  return {
    id: positiveInt(row.id, "product.id"),
    name: requiredString(row.name, "product.name"),
    sku: optionalString(row.sku),
    base_uom_id: positiveInt(row.base_uom_id, "base_uom_id"),
    base_uom_code: requiredString(row.base_uom_code, "base_uom_code"),
    base_uom_name: requiredString(row.base_uom_name, "base_uom_name"),
    display_uom_id: positiveInt(row.display_uom_id, "display_uom_id"),
    display_uom_code: requiredString(row.display_uom_code, "display_uom_code"),
    display_uom_name: requiredString(row.display_uom_name, "display_uom_name"),
    display_factor_to_base: parseQuantity(row.display_factor_to_base, "display_factor_to_base"),
    display_quantity_scale: nonNegativeInt(row.display_quantity_scale, "display_quantity_scale"),
    quantity_scale: nonNegativeInt(row.quantity_scale, "quantity_scale"),
    quantity_step: parseQuantity(row.quantity_step, "quantity_step"),
    available_quantity: parseQuantity(row.available_quantity, "available_quantity", { allowZero: true }),
  };
};

export const parseSourceInventoryPage = (
  raw: unknown
): TransferSourceInventoryPage => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { items?: unknown }).items)
  ) {
    throw invalid();
  }

  const page = raw as Record<string, unknown>;

  return {
    items: (page.items as unknown[]).map(parseSourceInventoryItem),
    next_cursor:
      typeof page.next_cursor === "string" ? page.next_cursor : null,
    has_more: page.has_more === true,
    total: typeof page.total === "number" ? page.total : null,
  };
};

const parseOverrideReason = (raw: unknown): TransferOverrideReason => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  return {
    id: positiveInt(row.id, "override_reason.id"),
    code: requiredString(row.code, "override_reason.code"),
    description: requiredString(
      row.description,
      "override_reason.description"
    ),
  };
};

const parseOverrideBatch = (raw: unknown): TransferOverrideBatch => {
  if (typeof raw !== "object" || raw === null) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  if (typeof row.is_fefo_head !== "boolean") {
    throw invalid();
  }

  return {
    id: positiveInt(row.id, "batch.id"),
    batch_number: publicBatchNumber(row.batch_number, "batch.batch_number"),
    production_date: parsePublicBatchDate(row.production_date, () => {
      throw invalid();
    }),
    expiry_date: parsePublicBatchDate(row.expiry_date, () => {
      throw invalid();
    }),
    available_quantity: parseQuantity(row.available_quantity, "batch.available_quantity", { allowZero: true }),
    is_fefo_head: row.is_fefo_head,
  };
};

export const parseBatchOptions = (
  raw: unknown,
  expectedLocationId: number,
  expectedProductId: number
): TransferBatchOptions => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { batches?: unknown }).batches)
  ) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  const locationId = positiveInt(row.location_id, "location_id");
  const productId = positiveInt(
    row.product_variant_id,
    "product_variant_id"
  );

  if (
    locationId !== expectedLocationId ||
    productId !== expectedProductId
  ) {
    throw new Error(
      "مرفوض: خيارات الدفعات لا تطابق مصدر الحوالة أو الصنف المحدد."
    );
  }

  const batches = (row.batches as unknown[]).map(parseOverrideBatch);
  const recommendedBatchId = optionalPositiveInt(
    row.recommended_batch_id
  );

  if (
    recommendedBatchId !== null &&
    !batches.some((batch) => batch.id === recommendedBatchId)
  ) {
    throw invalid();
  }

  return {
    location_id: locationId,
    product_variant_id: productId,
    recommended_batch_id: recommendedBatchId,
    batches,
  };
};


export const parseOverrideOptions = (
  raw: unknown,
  expectedLocationId: number,
  expectedProductId: number
): TransferOverrideOptions => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !Array.isArray((raw as { batches?: unknown }).batches) ||
    !Array.isArray((raw as { reasons?: unknown }).reasons)
  ) {
    throw invalid();
  }

  const row = raw as Record<string, unknown>;
  const locationId = positiveInt(row.location_id, "location_id");
  const productId = positiveInt(
    row.product_variant_id,
    "product_variant_id"
  );

  if (
    locationId !== expectedLocationId ||
    productId !== expectedProductId
  ) {
    throw new Error(
      "مرفوض: خيارات FEFO لا تطابق مصدر الحوالة أو الصنف المحدد."
    );
  }

  const batches = (row.batches as unknown[]).map(parseOverrideBatch);
  const reasons = (row.reasons as unknown[]).map(parseOverrideReason);
  const fefoBatchId = optionalPositiveInt(row.fefo_batch_id);

  if (
    fefoBatchId !== null &&
    !batches.some((batch) => batch.id === fefoBatchId)
  ) {
    throw invalid();
  }

  return {
    location_id: locationId,
    product_variant_id: productId,
    fefo_batch_id: fefoBatchId,
    batches,
    reasons,
  };
};
