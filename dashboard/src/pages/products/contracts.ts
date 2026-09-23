type CodedContractError = Error & { code: string };

const contractError = (code: string): never => {
  const error = new Error(code) as CodedContractError;
  error.code = code;
  throw error;
};

const record = (
  value: unknown,
  code: string,
): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return contractError(code);
  }
  return value as Record<string, unknown>;
};

const int = (
  value: unknown,
  code: string,
  min = 0,
): number => {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < min
  ) {
    return contractError(code);
  }
  return value;
};

const str = (
  value: unknown,
  code: string,
  max = 200,
): string => {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value.length > max
  ) {
    return contractError(code);
  }
  return value;
};

const nullableStr = (
  value: unknown,
  code: string,
  max = 200,
): string | null =>
  value === null ? null : str(value, code, max);

const bool = (
  value: unknown,
  code: string,
): boolean => {
  if (typeof value !== "boolean") {
    return contractError(code);
  }
  return value;
};

const moneyOrNull = (
  value: unknown,
  code: string,
): string | null => {
  if (value === null) return null;
  const text = str(value, code, 64);
  if (!/^\d+(?:\.\d{1,6})?$/.test(text)) {
    return contractError(code);
  }
  return text;
};

export type ProductTrackingMode =
  | "NONE"
  | "OPTIONAL"
  | "REQUIRED";

export type ProductTrackingSource =
  | "COMPANY"
  | "PLATFORM_FALLBACK";

const trackingMode = (
  value: unknown,
  code: string,
): ProductTrackingMode => {
  if (
    value !== "NONE" &&
    value !== "OPTIONAL" &&
    value !== "REQUIRED"
  ) {
    return contractError(code);
  }
  return value;
};

const trackingSource = (
  value: unknown,
  code: string,
): ProductTrackingSource => {
  if (
    value !== "COMPANY" &&
    value !== "PLATFORM_FALLBACK"
  ) {
    return contractError(code);
  }
  return value;
};

const uuid = (
  value: unknown,
  code: string,
): string => {
  const text = str(value, code, 36);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      text,
    )
  ) {
    return contractError(code);
  }
  return text;
};

const stringArray = (
  value: unknown,
  code: string,
  maxItems = 1000,
  maxItemLength = 255,
): string[] => {
  if (
    !Array.isArray(value) ||
    value.length > maxItems
  ) {
    return contractError(code);
  }
  return value.map((item) =>
    str(item, code, maxItemLength),
  );
};

const stringRecord = (
  value: unknown,
  code: string,
  maxEntries = 1000,
): Record<string, string> => {
  const raw = record(value, code);
  const entries = Object.entries(raw);
  if (entries.length > maxEntries) {
    return contractError(code);
  }
  const result: Record<string, string> = {};
  for (const [key, item] of entries) {
    if (
      !key.trim() ||
      key.length > 100
    ) {
      return contractError(code);
    }
    result[key] = str(item, code, 255);
  }
  return result;
};

export type ProductImportStatus =
  | "QUEUED"
  | "PARSING"
  | "NEEDS_MAPPING"
  | "VALIDATING"
  | "VALIDATION_FAILED"
  | "IMPORTING"
  | "RETRYING"
  | "COMPLETED"
  | "FAILED";

const importStatus = (
  value: unknown,
  code: string,
): ProductImportStatus => {
  if (
    value !== "QUEUED" &&
    value !== "PARSING" &&
    value !== "NEEDS_MAPPING" &&
    value !== "VALIDATING" &&
    value !== "VALIDATION_FAILED" &&
    value !== "IMPORTING" &&
    value !== "RETRYING" &&
    value !== "COMPLETED" &&
    value !== "FAILED"
  ) {
    return contractError(code);
  }
  return value;
};

export interface SimpleProduct {
  id: number;
  product_id: number;
  name: string;
  family_name: string;
  sku: string;
  units_per_package: number | null;
  legacy_packs_per_carton: number;
  base_uom_id: number;
  package_uom_id: number | null;
  package_uom_code: string | null;
  currency_code: string;
  package_price: string | null;
  unit_price: string | null;
  unit_barcode: string | null;
  package_barcode: string | null;
  package_uses_base_barcode: boolean;
  version: number;
  lot_control_mode: ProductTrackingMode;
  expiry_control_mode: ProductTrackingMode;
  lifecycle_status: "ACTIVE" | "RETIRING";
  simple_compatible: boolean;
}

export interface SimpleProductPage {
  currency_code: string;
  pricing_visible: boolean;
  items: SimpleProduct[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ProductTrackingDefaults {
  lot_control_mode: ProductTrackingMode;
  expiry_control_mode: ProductTrackingMode;
  lot_control_source: ProductTrackingSource;
  expiry_control_source: ProductTrackingSource;
}

export interface ProductTrackingMutationResponse {
  product_variant_id: number;
  version: number;
  lot_control_mode: ProductTrackingMode;
  expiry_control_mode: ProductTrackingMode;
  changed: boolean;
}

export interface ProductFamily {
  id: number;
  name: string;
  version: number;
  variant_count: number;
}

export interface PackageUom {
  id: number;
  code: string;
}

export interface ProductImportAccepted {
  job_id: string;
  status: ProductImportStatus;
  replayed: boolean;
  default_lot_control_mode: ProductTrackingMode;
  default_expiry_control_mode: ProductTrackingMode;
}

export interface ProductImportError {
  row_number: number;
  code: string | null;
  message: string | null;
}

export interface ProductImportState {
  job_id: string;
  status: ProductImportStatus;
  file_name: string;
  total_rows: number;
  processed_rows: number;
  valid_rows: number;
  failed_rows: number;
  detected_headers: string[];
  suggested_mapping: Record<string, string>;
  column_mapping: Record<string, string>;
  default_lot_control_mode: ProductTrackingMode;
  default_expiry_control_mode: ProductTrackingMode;
  error_summary: Record<string, unknown>;
  errors: ProductImportError[];
}

export interface ProductImportErrorPage {
  items: ProductImportError[];
  next_after_row: number | null;
}

export function parseSimpleProductPage(
  raw: unknown,
): SimpleProductPage {
  const code = "SIMPLE_PRODUCTS_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 200 ||
    typeof page.has_more !== "boolean"
  ) {
    return contractError(code);
  }

  const pricingVisible = bool(
    page.pricing_visible,
    code,
  );
  const ids = new Set<number>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const id = int(row.id, code, 1);
    if (ids.has(id)) {
      return contractError(code);
    }
    ids.add(id);

    const lifecycle = str(
      row.lifecycle_status,
      code,
      20,
    );
    if (
      lifecycle !== "ACTIVE" &&
      lifecycle !== "RETIRING"
    ) {
      return contractError(code);
    }

    const simpleCompatible = bool(
      row.simple_compatible,
      code,
    );
    const unitsPerPackage =
      row.units_per_package === null
        ? null
        : int(
            row.units_per_package,
            code,
            1,
          );
    const legacyPacksPerCarton = int(
      row.legacy_packs_per_carton,
      code,
      1,
    );
    const baseUomId = int(
      row.base_uom_id,
      code,
      1,
    );
    const packageUomId =
      row.package_uom_id === null
        ? null
        : int(
            row.package_uom_id,
            code,
            1,
          );
    const packageUomCode = nullableStr(
      row.package_uom_code,
      code,
      30,
    );
    if (
      (packageUomId === null) !==
      (packageUomCode === null)
    ) {
      return contractError(code);
    }
    if (
      simpleCompatible &&
      unitsPerPackage === null
    ) {
      return contractError(code);
    }
    if (
      !simpleCompatible &&
      packageUomId === null &&
      packageUomCode === null &&
      unitsPerPackage !== null
    ) {
      return contractError(code);
    }
    if (
      packageUomId === null &&
      simpleCompatible &&
      unitsPerPackage !== 1
    ) {
      return contractError(code);
    }
    if (
      packageUomId !== null &&
      (
        packageUomId === baseUomId ||
        unitsPerPackage === null ||
        unitsPerPackage < 2
      )
    ) {
      return contractError(code);
    }

    return {
      id,
      product_id: int(row.product_id, code, 1),
      name: str(row.name, code, 200),
      family_name: str(row.family_name, code, 150),
      sku: str(row.sku, code, 100),
      units_per_package: unitsPerPackage,
      legacy_packs_per_carton:
        legacyPacksPerCarton,
      base_uom_id: baseUomId,
      package_uom_id: packageUomId,
      package_uom_code: packageUomCode,
      currency_code: str(
        row.currency_code,
        code,
        10,
      ),
      package_price: (() => {
        const value = moneyOrNull(
          row.package_price,
          code,
        );
        if (!pricingVisible && value !== null) {
          return contractError(code);
        }
        return value;
      })(),
      unit_price: (() => {
        const value = moneyOrNull(
          row.unit_price,
          code,
        );
        if (!pricingVisible && value !== null) {
          return contractError(code);
        }
        return value;
      })(),
      unit_barcode: nullableStr(
        row.unit_barcode,
        code,
        128,
      ),
      package_barcode: nullableStr(
        row.package_barcode,
        code,
        128,
      ),
      package_uses_base_barcode: bool(
        row.package_uses_base_barcode,
        code,
      ),
      version: int(row.version, code, 1),
      lot_control_mode: trackingMode(
        row.lot_control_mode,
        code,
      ),
      expiry_control_mode: trackingMode(
        row.expiry_control_mode,
        code,
      ),
      lifecycle_status: lifecycle as
        | "ACTIVE"
        | "RETIRING",
      simple_compatible:
        simpleCompatible,
    };
  });

  const next =
    page.next_cursor === null
      ? null
      : str(page.next_cursor, code, 512);
  if (page.has_more !== (next !== null)) {
    return contractError(code);
  }

  return {
    currency_code: str(
      page.currency_code,
      code,
      10,
    ),
    pricing_visible: pricingVisible,
    items,
    next_cursor: next,
    has_more: page.has_more,
  };
}

export function parseProductTrackingDefaults(
  raw: unknown,
): ProductTrackingDefaults {
  const code = "PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID";
  const row = record(raw, code);
  return {
    lot_control_mode: trackingMode(
      row.lot_control_mode,
      code,
    ),
    expiry_control_mode: trackingMode(
      row.expiry_control_mode,
      code,
    ),
    lot_control_source: trackingSource(
      row.lot_control_source,
      code,
    ),
    expiry_control_source: trackingSource(
      row.expiry_control_source,
      code,
    ),
  };
}

export function parseProductTrackingMutation(
  raw: unknown,
): ProductTrackingMutationResponse {
  const code = "PRODUCT_TRACKING_MUTATION_RESPONSE_INVALID";
  const row = record(raw, code);
  return {
    product_variant_id: int(
      row.product_variant_id,
      code,
      1,
    ),
    version: int(row.version, code, 1),
    lot_control_mode: trackingMode(
      row.lot_control_mode,
      code,
    ),
    expiry_control_mode: trackingMode(
      row.expiry_control_mode,
      code,
    ),
    changed: bool(row.changed, code),
  };
}


export function parseProductFamilies(
  raw: unknown,
): { items: ProductFamily[] } {
  const code = "PRODUCT_FAMILIES_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 200
  ) {
    return contractError(code);
  }

  const ids = new Set<number>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const id = int(row.id, code, 1);
    if (ids.has(id)) {
      return contractError(code);
    }
    ids.add(id);
    return {
      id,
      name: str(row.name, code, 150),
      version: int(row.version, code, 1),
      variant_count: int(
        row.variant_count,
        code,
        0,
      ),
    };
  });

  return { items };
}

export function parsePackageUoms(
  raw: unknown,
): { items: PackageUom[] } {
  const code = "PACKAGE_UOMS_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 32
  ) {
    return contractError(code);
  }

  const ids = new Set<number>();
  const codes = new Set<string>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const id = int(row.id, code, 1);
    const itemCode = str(
      row.code,
      code,
      30,
    );
    if (
      ids.has(id) ||
      codes.has(itemCode)
    ) {
      return contractError(code);
    }
    ids.add(id);
    codes.add(itemCode);
    return {
      id,
      code: itemCode,
    };
  });

  return { items };
}

const parseImportError = (
  raw: unknown,
  code: string,
): ProductImportError => {
  const row = record(raw, code);
  return {
    row_number: int(
      row.row_number,
      code,
      2,
    ),
    code: nullableStr(
      row.code,
      code,
      120,
    ),
    message: nullableStr(
      row.message,
      code,
      1000,
    ),
  };
};

export function parseProductImportAccepted(
  raw: unknown,
): ProductImportAccepted {
  const code = "PRODUCT_IMPORT_ACCEPTED_RESPONSE_INVALID";
  const row = record(raw, code);
  return {
    job_id: uuid(row.job_id, code),
    status: importStatus(row.status, code),
    replayed: bool(row.replayed, code),
    default_lot_control_mode: trackingMode(
      row.default_lot_control_mode,
      code,
    ),
    default_expiry_control_mode: trackingMode(
      row.default_expiry_control_mode,
      code,
    ),
  };
}

export function parseProductImportState(
  raw: unknown,
): ProductImportState {
  const code = "PRODUCT_IMPORT_STATE_RESPONSE_INVALID";
  const row = record(raw, code);
  if (
    !Array.isArray(row.errors) ||
    row.errors.length > 50
  ) {
    return contractError(code);
  }

  return {
    job_id: uuid(row.job_id, code),
    status: importStatus(row.status, code),
    file_name: str(row.file_name, code, 255),
    total_rows: int(row.total_rows, code, 0),
    processed_rows: int(
      row.processed_rows,
      code,
      0,
    ),
    valid_rows: int(row.valid_rows, code, 0),
    failed_rows: int(row.failed_rows, code, 0),
    detected_headers: stringArray(
      row.detected_headers,
      code,
      500,
      255,
    ),
    suggested_mapping: stringRecord(
      row.suggested_mapping,
      code,
    ),
    column_mapping: stringRecord(
      row.column_mapping,
      code,
    ),
    default_lot_control_mode: trackingMode(
      row.default_lot_control_mode,
      code,
    ),
    default_expiry_control_mode: trackingMode(
      row.default_expiry_control_mode,
      code,
    ),
    error_summary: record(
      row.error_summary,
      code,
    ),
    errors: row.errors.map((item) =>
      parseImportError(item, code),
    ),
  };
}

export function parseProductImportErrorPage(
  raw: unknown,
): ProductImportErrorPage {
  const code = "PRODUCT_IMPORT_ERRORS_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 1000
  ) {
    return contractError(code);
  }
  const items = page.items.map((item) =>
    parseImportError(item, code),
  );
  const next =
    page.next_after_row === null
      ? null
      : int(
          page.next_after_row,
          code,
          2,
        );
  if (
    next !== null &&
    items.length === 0
  ) {
    return contractError(code);
  }
  return {
    items,
    next_after_row: next,
  };
}


export type ProductBarcodeType =
  | "EAN8"
  | "EAN13"
  | "UPC_A"
  | "GTIN14"
  | "GS1_128"
  | "INTERNAL";

export interface ProductBarcodeRecord {
  id: number;
  product_variant_id: number;
  uom: {
    id: number;
    code: string;
    name: string;
  };
  barcode: string;
  barcode_type: ProductBarcodeType;
  is_primary: boolean;
  valid_from: string;
  valid_to: string | null;
  is_active: boolean;
  version: number;
}

export function parseProductBarcodes(
  raw: unknown,
): { items: ProductBarcodeRecord[] } {
  const code = "PRODUCT_BARCODES_RESPONSE_INVALID";
  const page = record(raw, code);
  if (!Array.isArray(page.items) || page.items.length > 500) {
    return contractError(code);
  }

  const ids = new Set<number>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const uom = record(row.uom, code);
    const id = int(row.id, code, 1);
    if (ids.has(id)) return contractError(code);
    ids.add(id);

    const barcodeType = row.barcode_type;
    if (
      barcodeType !== "EAN8" &&
      barcodeType !== "EAN13" &&
      barcodeType !== "UPC_A" &&
      barcodeType !== "GTIN14" &&
      barcodeType !== "GS1_128" &&
      barcodeType !== "INTERNAL"
    ) {
      return contractError(code);
    }

    return {
      id,
      product_variant_id: int(
        row.product_variant_id,
        code,
        1,
      ),
      uom: {
        id: int(uom.id, code, 1),
        code: str(uom.code, code, 30),
        name: str(uom.name, code, 100),
      },
      barcode: str(row.barcode, code, 128),
      barcode_type: barcodeType,
      is_primary: bool(row.is_primary, code),
      valid_from: str(row.valid_from, code, 64),
      valid_to: nullableStr(row.valid_to, code, 64),
      is_active: bool(row.is_active, code),
      version: int(row.version, code, 1),
    };
  });

  return { items };
}


export function parseProductBarcodeMutation(
  raw: unknown,
): {
  message: string;
  barcode: ProductBarcodeRecord;
} {
  const code = "PRODUCT_BARCODE_MUTATION_RESPONSE_INVALID";
  const row = record(raw, code);
  return {
    message: str(row.message, code, 500),
    barcode: parseProductBarcodes({
      items: [row.barcode],
    }).items[0],
  };
}
