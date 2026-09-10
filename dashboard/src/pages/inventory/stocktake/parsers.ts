import type {
  CountSheetItem,
  CycleBatchCursorPage,
  CycleBatchOption,
  CycleProductCursorPage,
  CycleProductOption,
  ReviewAttempt,
  ReviewLine,
  StocktakeReview,
  StocktakeSessionContext,
  StocktakeSessionCursorPage,
  StocktakeSessionSummary,
  StocktakeStatus,
  StocktakeType,
  VehicleReconCandidate,
  VehicleReconCandidateCursorPage,
} from "./types";
import type { StocktakeStockStatus } from "../inventoryUtils";

const STOCKTAKE_TYPES: readonly StocktakeType[] = [
  "FULL_COUNT",
  "CYCLE_COUNT",
  "VEHICLE_RECON",
];

const STOCKTAKE_STATUSES: readonly StocktakeStatus[] = [
  "DRAFT",
  "COUNTING",
  "PENDING_REVIEW",
  "RECOUNT_REQUIRED",
  "APPROVED",
  "POSTED",
  "CANCELLED",
];

const isRecord = (
  value: unknown
): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

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

const nonNegativeInt = (
  value: unknown,
  field: string
): number => {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const requiredString = (
  value: unknown,
  field: string
): string => {
  if (typeof value !== "string" || !value) {
    throw new Error(`حقل ${field} غير صالح.`);
  }
  return value;
};

const optionalString = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

const optionalPositiveInt = (value: unknown): number | null =>
  value === null || value === undefined
    ? null
    : positiveInt(value, "optional_id");

const parseStockStatus = (
  value: unknown
): StocktakeStockStatus => {
  if (value !== "AVAILABLE" && value !== "DAMAGED") {
    throw new Error("حالة مخزون سطر الجرد غير صالحة.");
  }
  return value;
};

const parseStocktakeType = (
  value: unknown
): StocktakeType => {
  if (
    typeof value !== "string" ||
    !STOCKTAKE_TYPES.includes(value as StocktakeType)
  ) {
    throw new Error("نوع جلسة الجرد غير صالح.");
  }
  return value as StocktakeType;
};

const parseStocktakeStatus = (
  value: unknown
): StocktakeStatus => {
  if (
    typeof value !== "string" ||
    !STOCKTAKE_STATUSES.includes(value as StocktakeStatus)
  ) {
    throw new Error("حالة جلسة الجرد غير صالحة.");
  }
  return value as StocktakeStatus;
};

export const getErrorMessage = (
  error: unknown,
  fallback: string
): string =>
  error instanceof Error && error.message
    ? error.message
    : fallback;

export const parseCycleProductPage = (
  raw: unknown
): CycleProductCursorPage => {
  if (!isRecord(raw) || !Array.isArray(raw.items) || typeof raw.has_more !== "boolean") {
    throw new Error("استجابة أصناف الجرد الدوري غير صالحة.");
  }
  const items: CycleProductOption[] = raw.items.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`صنف الجرد الدوري #${index + 1} غير صالح.`);
    }
    return {
      id: positiveInt(item.id, "product.id"),
      name: requiredString(item.name, "product.name"),
      sku: optionalString(item.sku),
      packs_per_carton: positiveInt(item.packs_per_carton, "product.packs_per_carton"),
    };
  });
  return {
    items,
    next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    has_more: raw.has_more,
    total: raw.total === null || raw.total === undefined ? null : nonNegativeInt(raw.total, "product.total"),
  };
};

export const parseCycleBatchPage = (
  raw: unknown,
  expectedProductId: number
): CycleBatchCursorPage => {
  if (!isRecord(raw) || !Array.isArray(raw.items) || typeof raw.has_more !== "boolean") {
    throw new Error("استجابة دفعات الجرد الدوري غير صالحة.");
  }
  const items: CycleBatchOption[] = raw.items.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`دفعة الجرد الدوري #${index + 1} غير صالحة.`);
    }
    const productVariantId = positiveInt(item.product_variant_id, "batch.product_variant_id");
    if (productVariantId !== expectedProductId) {
      throw new Error("مرفوض: السيرفر أعاد دفعة لا تتبع الصنف المختار.");
    }
    return {
      id: positiveInt(item.id, "batch.id"),
      product_variant_id: productVariantId,
      batch_number: requiredString(item.batch_number, "batch.batch_number"),
      production_date: optionalString(item.production_date),
      expiry_date: requiredString(item.expiry_date, "batch.expiry_date"),
      is_active: item.is_active === true,
    };
  });
  return {
    items,
    next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    has_more: raw.has_more,
    total: raw.total === null || raw.total === undefined ? null : nonNegativeInt(raw.total, "batch.total"),
  };
};

export const parseStocktakeSessionContext = (
  raw: unknown,
  expectedAnchorLocationId: number
): StocktakeSessionContext => {
  if (!isRecord(raw)) {
    throw new Error("استجابة سياق جلسة الجرد غير صالحة.");
  }

  const sourceLocationId = positiveInt(
    raw.source_location_id,
    "context.source_location_id"
  );
  if (sourceLocationId !== expectedAnchorLocationId) {
    throw new Error(
      "مرفوض: جلسة الجرد لا تتبع المستودع المحدد."
    );
  }

  return {
    session_id: positiveInt(
      raw.session_id,
      "context.session_id"
    ),
    stocktake_type: parseStocktakeType(
      raw.stocktake_type
    ),
    status: parseStocktakeStatus(raw.status),
    location_id: positiveInt(
      raw.location_id,
      "context.location_id"
    ),
    related_work_session_id: optionalPositiveInt(
      raw.related_work_session_id
    ),
    source_location_id: sourceLocationId,
  };
};

export const parseVehicleReconCandidatePage = (
  raw: unknown
): VehicleReconCandidateCursorPage => {
  if (
    !isRecord(raw) ||
    !Array.isArray(raw.items) ||
    typeof raw.has_more !== "boolean"
  ) {
    throw new Error(
      "استجابة جلسات تسوية السيارات غير صالحة."
    );
  }

  const items: VehicleReconCandidate[] =
    raw.items.map((item, index) => {
      if (!isRecord(item)) {
        throw new Error(
          `جلسة تسوية السيارة #${index + 1} غير صالحة.`
        );
      }

      const existingStatus =
        item.existing_stocktake_status === null ||
        item.existing_stocktake_status === undefined
          ? null
          : parseStocktakeStatus(
              item.existing_stocktake_status
            );

      return {
        work_session_id: positiveInt(
          item.work_session_id,
          "vehicle_recon.work_session_id"
        ),
        driver_id: positiveInt(
          item.driver_id,
          "vehicle_recon.driver_id"
        ),
        driver_name: requiredString(
          item.driver_name,
          "vehicle_recon.driver_name"
        ),
        session_date: requiredString(
          item.session_date,
          "vehicle_recon.session_date"
        ),
        end_time: requiredString(
          item.end_time,
          "vehicle_recon.end_time"
        ),
        vehicle_id: positiveInt(
          item.vehicle_id,
          "vehicle_recon.vehicle_id"
        ),
        vehicle_location_id: positiveInt(
          item.vehicle_location_id,
          "vehicle_recon.vehicle_location_id"
        ),
        vehicle_location_name: requiredString(
          item.vehicle_location_name,
          "vehicle_recon.vehicle_location_name"
        ),
        vehicle_location_code: requiredString(
          item.vehicle_location_code,
          "vehicle_recon.vehicle_location_code"
        ),
        existing_stocktake_session_id:
          optionalPositiveInt(
            item.existing_stocktake_session_id
          ),
        existing_stocktake_reference:
          optionalString(
            item.existing_stocktake_reference
          ),
        existing_stocktake_status:
          existingStatus,
      };
    });

  for (const item of items) {
    const hasId =
      item.existing_stocktake_session_id !== null;
    const hasStatus =
      item.existing_stocktake_status !== null;

    if (hasId !== hasStatus) {
      throw new Error(
        "استجابة VEHICLE_RECON غير متسقة: معرّف الجرد وحالته يجب أن يظهرا معاً."
      );
    }
  }

  return {
    items,
    next_cursor:
      typeof raw.next_cursor === "string"
        ? raw.next_cursor
        : null,
    has_more: raw.has_more,
    total:
      raw.total === null || raw.total === undefined
        ? null
        : nonNegativeInt(
            raw.total,
            "vehicle_recon.total"
          ),
  };
};

export const parseCountSheet = (
  raw: unknown
): CountSheetItem[] => {
  if (!Array.isArray(raw)) {
    throw new Error("استجابة ورقة الجرد غير صالحة.");
  }

  return raw.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(
        `سطر ورقة الجرد #${index + 1} غير صالح.`
      );
    }

    const batchId =
      item.batch_id === null
        ? null
        : positiveInt(item.batch_id, "batch_id");

    return {
      product_variant_id: positiveInt(
        item.product_variant_id,
        "product_variant_id"
      ),
      batch_id: batchId,
      stock_status: parseStockStatus(item.stock_status),
      product_name: requiredString(
        item.product_name,
        "product_name"
      ),
      packs_per_carton: positiveInt(
        item.packs_per_carton,
        "packs_per_carton"
      ),
      batch_number: optionalString(item.batch_number),
      expiry_date: optionalString(item.expiry_date),
    };
  });
};

const parseReviewAttempt = (
  raw: unknown
): ReviewAttempt => {
  if (!isRecord(raw)) {
    throw new Error("بيانات محاولة الجرد غير صالحة.");
  }

  return {
    id: positiveInt(raw.id, "attempt.id"),
    attempt_number: positiveInt(
      raw.attempt_number,
      "attempt.attempt_number"
    ),
    counted_by: positiveInt(
      raw.counted_by,
      "attempt.counted_by"
    ),
    counted_by_name: requiredString(
      raw.counted_by_name,
      "attempt.counted_by_name"
    ),
    authorized_by:
      raw.authorized_by === null
        ? null
        : positiveInt(
            raw.authorized_by,
            "attempt.authorized_by"
          ),
    authorized_by_name: optionalString(
      raw.authorized_by_name
    ),
    recount_of_attempt_id:
      raw.recount_of_attempt_id === null ||
      raw.recount_of_attempt_id === undefined
        ? null
        : positiveInt(
            raw.recount_of_attempt_id,
            "attempt.recount_of_attempt_id"
          ),
    recount_reason: optionalString(raw.recount_reason),
    requires_independent_recount:
      raw.requires_independent_recount === true,
    submitted_at: optionalString(raw.submitted_at),
  };
};

const parseReviewLine = (raw: unknown): ReviewLine => {
  if (!isRecord(raw)) {
    throw new Error("سطر مراجعة الجرد غير صالح.");
  }

  const lineOrigin = raw.line_origin;
  if (
    lineOrigin !== "SNAPSHOT" &&
    lineOrigin !== "DISCOVERED"
  ) {
    throw new Error("مصدر سطر الجرد غير صالح.");
  }

  const variance = raw.variance_quantity;
  if (
    typeof variance !== "number" ||
    !Number.isInteger(variance)
  ) {
    throw new Error("حقل variance_quantity غير صالح.");
  }

  return {
    attempt_line_id: positiveInt(
      raw.attempt_line_id,
      "attempt_line_id"
    ),
    product_variant_id: positiveInt(
      raw.product_variant_id,
      "product_variant_id"
    ),
    batch_id:
      raw.batch_id === null
        ? null
        : positiveInt(raw.batch_id, "batch_id"),
    stock_status: parseStockStatus(raw.stock_status),
    line_origin: lineOrigin,
    product_name: requiredString(
      raw.product_name,
      "product_name"
    ),
    packs_per_carton: positiveInt(
      raw.packs_per_carton,
      "packs_per_carton"
    ),
    batch_number: optionalString(raw.batch_number),
    expiry_date: optionalString(raw.expiry_date),
    expected_quantity: nonNegativeInt(
      raw.expected_quantity,
      "expected_quantity"
    ),
    actual_quantity: nonNegativeInt(
      raw.actual_quantity,
      "actual_quantity"
    ),
    variance_quantity: variance,
    notes: optionalString(raw.notes),
  };
};

export const parseStocktakeReview = (
  raw: unknown
): StocktakeReview => {
  if (
    !isRecord(raw) ||
    !Array.isArray(raw.attempt_history) ||
    !Array.isArray(raw.lines)
  ) {
    throw new Error("استجابة مراجعة الجرد غير صالحة.");
  }

  return {
    session_id: positiveInt(raw.session_id, "session_id"),
    reference_number: requiredString(
      raw.reference_number,
      "reference_number"
    ),
    stocktake_type: parseStocktakeType(raw.stocktake_type),
    status: parseStocktakeStatus(raw.status),
    location_id: positiveInt(
      raw.location_id,
      "location_id"
    ),
    independent_recount_satisfied:
      raw.independent_recount_satisfied === true,
    latest_attempt: parseReviewAttempt(raw.latest_attempt),
    attempt_history: raw.attempt_history.map(
      parseReviewAttempt
    ),
    lines: raw.lines.map(parseReviewLine),
  };
};

export const parseStartSessionId = (
  raw: unknown
): number => {
  if (!isRecord(raw)) {
    throw new Error("استجابة بدء الجرد غير صالحة.");
  }
  return positiveInt(raw.session_id, "session_id");
};

export const readMessage = (
  raw: unknown
): string | null =>
  isRecord(raw) && typeof raw.message === "string"
    ? raw.message
    : null;

export const parseRecountRequiresIndependent = (
  raw: unknown
): boolean => {
  if (
    !isRecord(raw) ||
    typeof raw.requires_independent_counter !== "boolean"
  ) {
    throw new Error(
      "استجابة تفويض إعادة العد غير صالحة."
    );
  }
  return raw.requires_independent_counter;
};

export const rowKey = (
  productVariantId: number,
  batchId: number | null,
  stockStatus: StocktakeStockStatus
): string =>
  `${productVariantId}:${batchId ?? "NO_BATCH"}:${stockStatus}`;

const parseSessionSummary = (
  raw: unknown
): StocktakeSessionSummary => {
  if (!isRecord(raw)) {
    throw new Error("عنصر جلسة جرد غير صالح.");
  }

  return {
    id: positiveInt(raw.id, "session.id"),
    reference_number: requiredString(
      raw.reference_number,
      "session.reference_number"
    ),
    stocktake_type: parseStocktakeType(raw.stocktake_type),
    status: parseStocktakeStatus(raw.status),
    location_id: positiveInt(
      raw.location_id,
      "session.location_id"
    ),
    scope_product_variant_id: optionalPositiveInt(
      raw.scope_product_variant_id
    ),
    scope_product_name: optionalString(
      raw.scope_product_name
    ),
    scope_batch_id: optionalPositiveInt(
      raw.scope_batch_id
    ),
    scope_batch_number: optionalString(
      raw.scope_batch_number
    ),
    related_work_session_id: optionalPositiveInt(
      raw.related_work_session_id
    ),
    started_by: positiveInt(
      raw.started_by,
      "session.started_by"
    ),
    started_by_name: requiredString(
      raw.started_by_name,
      "session.started_by_name"
    ),
    pending_independent_recount_required:
      raw.pending_independent_recount_required === true,
    snapshot_cutoff_at: optionalString(
      raw.snapshot_cutoff_at
    ),
    created_at: requiredString(
      raw.created_at,
      "session.created_at"
    ),
    updated_at: requiredString(
      raw.updated_at,
      "session.updated_at"
    ),
  };
};

export const parseStocktakeSessionPage = (
  raw: unknown,
  expectedLocationId: number
): StocktakeSessionCursorPage => {
  if (
    !isRecord(raw) ||
    !Array.isArray(raw.items) ||
    typeof raw.has_more !== "boolean"
  ) {
    throw new Error(
      "استجابة مركز جلسات الجرد غير صالحة."
    );
  }

  const items = raw.items.map(parseSessionSummary);

  if (
    items.some(
      (item) => item.location_id !== expectedLocationId
    )
  ) {
    throw new Error(
      "مرفوض: السيرفر أعاد جلسة جرد خارج الموقع المحدد."
    );
  }

  return {
    items,
    next_cursor:
      typeof raw.next_cursor === "string"
        ? raw.next_cursor
        : null,
    has_more: raw.has_more,
    total:
      raw.total === null || raw.total === undefined
        ? null
        : nonNegativeInt(raw.total, "total"),
  };
};
