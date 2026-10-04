import type { CatalogVariant } from "@/features/catalog/contracts";

const DB_INT_MAX = 2_147_483_647;
const MAX_CURSOR_LENGTH = 512;

type ProductLocationContractError = Error & { code: string };

const contractError = (
  code: string,
  message: string,
): ProductLocationContractError => {
  const error = new Error(message) as ProductLocationContractError;
  error.code = code;
  return error;
};

const invalid = (message: string): ProductLocationContractError =>
  contractError("CATALOG_CONTRACT_INVALID", message);

const record = (
  value: unknown,
  message: string,
): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw invalid(message);
  }
  return value as Record<string, unknown>;
};

const integer = (
  value: unknown,
  field: string,
  min = 0,
): number => {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < min ||
    value > DB_INT_MAX
  ) {
    throw invalid(`PRODUCT_LOCATION_INTEGER_INVALID:${field}`);
  }
  return value;
};

const requiredString = (
  value: unknown,
  field: string,
  max: number,
): string => {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value.length > max
  ) {
    throw invalid(`PRODUCT_LOCATION_STRING_INVALID:${field}`);
  }
  return value;
};

const lifecycleStatus = (
  value: unknown,
): CatalogVariant["lifecycle_status"] => {
  if (!["DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"].includes(String(value))) {
    throw invalid("PRODUCT_LOCATION_LIFECYCLE_INVALID");
  }
  return value as CatalogVariant["lifecycle_status"];
};

export interface ProductLocationAssignment {
  id: number;
  location: {
    id: number;
    code: string;
    name: string;
    location_type: string;
  };
  product_variant: {
    id: number;
    sku: string;
    name: string;
    lifecycle_status: CatalogVariant["lifecycle_status"];
  };
  operational_flags: {
    inbound_enabled: boolean;
    outbound_enabled: boolean;
  };
  version: number;
  created_by: number;
  created_at: string;
  updated_at: string;
}

export interface ProductLocationCursorPage {
  items: ProductLocationAssignment[];
  next_cursor: string | null;
  has_more: boolean;
}

const parseProductLocation = (
  value: unknown,
): ProductLocationAssignment => {
  const row = record(value, "PRODUCT_LOCATION_CONTRACT_INVALID");
  const location = record(row.location, "PRODUCT_LOCATION_LOCATION_INVALID");
  const variant = record(row.product_variant, "PRODUCT_LOCATION_VARIANT_INVALID");
  const flags = record(row.operational_flags, "PRODUCT_LOCATION_FLAGS_INVALID");
  if (
    typeof flags.inbound_enabled !== "boolean" ||
    typeof flags.outbound_enabled !== "boolean"
  ) {
    throw invalid("PRODUCT_LOCATION_FLAGS_INVALID");
  }

  return {
    id: integer(row.id, "product_location.id", 1),
    location: {
      id: integer(location.id, "location.id", 1),
      code: requiredString(location.code, "location.code", 100),
      name: requiredString(location.name, "location.name", 150),
      location_type: requiredString(
        location.location_type,
        "location.location_type",
        30,
      ),
    },
    product_variant: {
      id: integer(variant.id, "variant.id", 1),
      sku: requiredString(variant.sku, "variant.sku", 100),
      name: requiredString(variant.name, "variant.name", 200),
      lifecycle_status: lifecycleStatus(variant.lifecycle_status),
    },
    operational_flags: {
      inbound_enabled: flags.inbound_enabled,
      outbound_enabled: flags.outbound_enabled,
    },
    version: integer(row.version, "product_location.version", 1),
    created_by: integer(row.created_by, "created_by", 1),
    created_at: requiredString(row.created_at, "created_at", 64),
    updated_at: requiredString(row.updated_at, "updated_at", 64),
  };
};

export const parseProductLocations = (
  raw: unknown,
): ProductLocationCursorPage => {
  const row = record(raw, "PRODUCT_LOCATION_PAGE_INVALID");
  if (
    !Array.isArray(row.items) ||
    row.items.length > 200 ||
    typeof row.has_more !== "boolean"
  ) {
    throw invalid("PRODUCT_LOCATION_PAGE_INVALID");
  }

  const next =
    row.next_cursor === null
      ? null
      : requiredString(
          row.next_cursor,
          "next_cursor",
          MAX_CURSOR_LENGTH,
        );
  if (row.has_more !== (next !== null)) {
    throw invalid("PRODUCT_LOCATION_CURSOR_INVALID");
  }

  return {
    items: row.items.map(parseProductLocation),
    next_cursor: next,
    has_more: row.has_more,
  };
};

const mutationRecord = (
  raw: unknown,
): Record<string, unknown> => {
  const row = record(raw, "PRODUCT_LOCATION_MUTATION_INVALID");
  requiredString(row.message, "message", 1000);
  return row;
};

export const parseProductLocationMutation = (
  raw: unknown,
  options: {
    variantId: number;
    locationId: number;
    assignmentId?: number;
  },
): ProductLocationAssignment => {
  const row = mutationRecord(raw);
  const page = parseProductLocations({
    items: [row.product_location],
    next_cursor: null,
    has_more: false,
  });
  const item = page.items[0];
  if (
    item.product_variant.id !== options.variantId ||
    item.location.id !== options.locationId ||
    (options.assignmentId !== undefined && item.id !== options.assignmentId)
  ) {
    throw contractError(
      "CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH",
      "PRODUCT_LOCATION_SCOPE_MISMATCH",
    );
  }
  return item;
};

export const parseProductLocationDelete = (
  raw: unknown,
  options: {
    assignmentId: number;
    locationId: number;
  },
): void => {
  const row = mutationRecord(raw);
  if (
    row.product_location_id !== options.assignmentId ||
    (row.location_id !== undefined && row.location_id !== options.locationId)
  ) {
    throw contractError(
      "CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH",
      "PRODUCT_LOCATION_SCOPE_MISMATCH",
    );
  }
};
