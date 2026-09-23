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

export interface SimpleProduct {
  id: number;
  product_id: number;
  name: string;
  family_name: string;
  sku: string;
  units_per_package: number;
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

    return {
      id,
      product_id: int(row.product_id, code, 1),
      name: str(row.name, code, 200),
      family_name: str(row.family_name, code, 150),
      sku: str(row.sku, code, 100),
      units_per_package: int(
        row.units_per_package,
        code,
        1,
      ),
      package_uom_code: nullableStr(
        row.package_uom_code,
        code,
        30,
      ),
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
      simple_compatible: bool(
        row.simple_compatible,
        code,
      ),
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
