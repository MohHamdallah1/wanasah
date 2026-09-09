import { isTransferStatus } from "./constants";
import type {
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

const positiveInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value <= 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const nonNegativeInt = (value: unknown, field: string): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const requiredString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || !value) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const optionalString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

const optionalPositiveInt = (value: unknown): number | null =>
  typeof value === "number" &&
  Number.isInteger(value) &&
  value > 0
    ? value
    : null;

const parseTransfer = (raw: unknown): WarehouseTransferListItem => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("بيانات الحوالة غير صالحة.");
  }

  const row = raw as Record<string, unknown>;
  if (!isTransferStatus(row.status)) {
    throw new Error("حالة الحوالة غير معروفة.");
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
    total_quantity: nonNegativeInt(
      row.total_quantity,
      "total_quantity"
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
    throw new Error("تنسيق صفحة الحوالات غير صالح.");
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
    throw new Error("سطر حوالة غير صالح.");
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
    batch_number: requiredString(row.batch_number, "batch_number"),
    expiry_date: requiredString(row.expiry_date, "expiry_date"),
    quantity: positiveInt(row.quantity, "quantity"),
    fefo_override_reason_id: optionalPositiveInt(
      row.fefo_override_reason_id
    ),
    fefo_overridden_by: optionalPositiveInt(row.fefo_overridden_by),
    fefo_override_note: optionalString(row.fefo_override_note),
  };
};

export const parseTransferDetail = (
  raw: unknown,
  expectedLocationId: number
): WarehouseTransferDetail => {
  if (
    typeof raw !== "object" ||
    raw === null ||
    !("transfer" in raw) ||
    !("lines" in raw) ||
    !Array.isArray((raw as { lines?: unknown }).lines)
  ) {
    throw new Error("تنسيق تفاصيل الحوالة غير صالح.");
  }

  const record = raw as Record<string, unknown>;
  const transfer = parseTransfer(record.transfer);

  if (
    transfer.source_location_id !== expectedLocationId &&
    transfer.destination_location_id !== expectedLocationId
  ) {
    throw new Error(
      "مرفوض: تفاصيل الحوالة لا تطابق المستودع المحدد حالياً."
    );
  }

  const lines = (record.lines as unknown[]).map(parseTransferLine);
  if (lines.length === 0) {
    throw new Error("الحوالة لا تحتوي على أسطر مخزون.");
  }

  return { transfer, lines };
};


const parseTransferLocation = (raw: unknown): TransferLocationOption => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("موقع حوالة غير صالح.");
  }

  const row = raw as Record<string, unknown>;
  const locationType = row.location_type;
  if (locationType !== "WAREHOUSE" && locationType !== "VEHICLE") {
    throw new Error("نوع موقع الحوالة غير صالح.");
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
    throw new Error("تنسيق مواقع الحوالة غير صالح.");
  }

  return raw.map(parseTransferLocation);
};

const parseSourceInventoryItem = (
  raw: unknown
): TransferSourceInventoryItem => {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("صنف مصدر الحوالة غير صالح.");
  }

  const row = raw as Record<string, unknown>;

  return {
    id: positiveInt(row.id, "product.id"),
    name: requiredString(row.name, "product.name"),
    sku: optionalString(row.sku),
    packs_per_carton: positiveInt(
      row.packs_per_carton,
      "packs_per_carton"
    ),
    available_packs: nonNegativeInt(
      row.available_packs,
      "available_packs"
    ),
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
    throw new Error("تنسيق مخزون مصدر الحوالة غير صالح.");
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
    throw new Error("سبب تجاوز FEFO غير صالح.");
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
    throw new Error("دفعة تجاوز FEFO غير صالحة.");
  }

  const row = raw as Record<string, unknown>;
  if (typeof row.is_fefo_head !== "boolean") {
    throw new Error("حالة FEFO للدفعة غير صالحة.");
  }

  return {
    id: positiveInt(row.id, "batch.id"),
    batch_number: requiredString(row.batch_number, "batch.batch_number"),
    production_date: optionalString(row.production_date),
    expiry_date: requiredString(row.expiry_date, "batch.expiry_date"),
    available_packs: nonNegativeInt(
      row.available_packs,
      "batch.available_packs"
    ),
    is_fefo_head: row.is_fefo_head,
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
    throw new Error("تنسيق خيارات تجاوز FEFO غير صالح.");
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
    throw new Error("دفعة FEFO المرجعية غير موجودة ضمن الخيارات.");
  }

  return {
    location_id: locationId,
    product_variant_id: productId,
    fefo_batch_id: fefoBatchId,
    batches,
    reasons,
  };
};
