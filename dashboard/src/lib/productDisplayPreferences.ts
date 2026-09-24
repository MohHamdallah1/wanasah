export const PRODUCT_DISPLAY_PREFERENCES_VERSION =
  1 as const;

export type ProductDisplayColumn =
  | "package"
  | "unitsPerPackage"
  | "tracking"
  | "lifecycle"
  | "unitBarcode"
  | "packageBarcode"
  | "packagePrice"
  | "unitPrice";

export type ProductDisplayDensity =
  | "comfortable"
  | "compact";

export type ProductDisplaySortField =
  | "id"
  | "name"
  | "family"
  | "sku"
  | "lifecycle";

export type ProductDisplaySortDirection =
  | "asc"
  | "desc";

export type ProductDetailSection =
  | "package"
  | "tracking"
  | "barcodes"
  | "pricing"
  | "compatibility";

export type ProductDisplayPreferences = {
  version: typeof PRODUCT_DISPLAY_PREFERENCES_VERSION;
  columns: Record<
    ProductDisplayColumn,
    boolean
  >;
  density: ProductDisplayDensity;
  defaultSort: {
    field: ProductDisplaySortField;
    direction: ProductDisplaySortDirection;
  };
  detailSections: Record<
    ProductDetailSection,
    boolean
  >;
};

export const DEFAULT_PRODUCT_DISPLAY_PREFERENCES: ProductDisplayPreferences =
  {
    version:
      PRODUCT_DISPLAY_PREFERENCES_VERSION,
    columns: {
      package: true,
      unitsPerPackage: true,
      tracking: true,
      lifecycle: false,
      unitBarcode: false,
      packageBarcode: false,
      packagePrice: true,
      unitPrice: true,
    },
    density: "comfortable",
    defaultSort: {
      field: "id",
      direction: "asc",
    },
    detailSections: {
      package: true,
      tracking: true,
      barcodes: true,
      pricing: true,
      compatibility: true,
    },
  };

const DISPLAY_COLUMNS =
  new Set<ProductDisplayColumn>([
    "package",
    "unitsPerPackage",
    "tracking",
    "lifecycle",
    "unitBarcode",
    "packageBarcode",
    "packagePrice",
    "unitPrice",
  ]);

const DETAIL_SECTIONS =
  new Set<ProductDetailSection>([
    "package",
    "tracking",
    "barcodes",
    "pricing",
    "compatibility",
  ]);

const SORT_FIELDS =
  new Set<ProductDisplaySortField>([
    "id",
    "name",
    "family",
    "sku",
    "lifecycle",
  ]);

const SORT_DIRECTIONS =
  new Set<ProductDisplaySortDirection>([
    "asc",
    "desc",
  ]);

const DENSITIES =
  new Set<ProductDisplayDensity>([
    "comfortable",
    "compact",
  ]);

const scopedKey = (
  companyId: number,
  driverId: number,
) =>
  `wanasah:products:display:v${PRODUCT_DISPLAY_PREFERENCES_VERSION}:${companyId}:${driverId}`;

const positiveSafeInteger = (
  value: number,
): boolean =>
  Number.isSafeInteger(value) &&
  value > 0;

const cloneDefaults =
  (): ProductDisplayPreferences => ({
    version:
      PRODUCT_DISPLAY_PREFERENCES_VERSION,
    columns: {
      ...DEFAULT_PRODUCT_DISPLAY_PREFERENCES.columns,
    },
    density:
      DEFAULT_PRODUCT_DISPLAY_PREFERENCES.density,
    defaultSort: {
      ...DEFAULT_PRODUCT_DISPLAY_PREFERENCES.defaultSort,
    },
    detailSections: {
      ...DEFAULT_PRODUCT_DISPLAY_PREFERENCES.detailSections,
    },
  });

const record = (
  value: unknown,
): Record<string, unknown> | null =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value)
    ? (value as Record<
        string,
        unknown
      >)
    : null;

export const parseProductDisplayPreferences =
  (
    value: unknown,
  ): ProductDisplayPreferences => {
    const root = record(value);
    if (
      !root ||
      root.version !==
        PRODUCT_DISPLAY_PREFERENCES_VERSION
    ) {
      return cloneDefaults();
    }

    const columnsRaw =
      record(root.columns);
    const detailRaw =
      record(root.detailSections);
    const sortRaw =
      record(root.defaultSort);

    if (
      !columnsRaw ||
      !detailRaw ||
      !sortRaw ||
      typeof root.density !==
        "string" ||
      !DENSITIES.has(
        root.density as ProductDisplayDensity,
      ) ||
      typeof sortRaw.field !==
        "string" ||
      !SORT_FIELDS.has(
        sortRaw.field as ProductDisplaySortField,
      ) ||
      typeof sortRaw.direction !==
        "string" ||
      !SORT_DIRECTIONS.has(
        sortRaw.direction as ProductDisplaySortDirection,
      )
    ) {
      return cloneDefaults();
    }

    const parsed =
      cloneDefaults();

    for (const key of DISPLAY_COLUMNS) {
      const candidate =
        columnsRaw[key];
      if (
        typeof candidate !==
        "boolean"
      ) {
        return cloneDefaults();
      }
      parsed.columns[key] =
        candidate;
    }

    for (const key of DETAIL_SECTIONS) {
      const candidate =
        detailRaw[key];
      if (
        typeof candidate !==
        "boolean"
      ) {
        return cloneDefaults();
      }
      parsed.detailSections[key] =
        candidate;
    }

    parsed.density =
      root.density as ProductDisplayDensity;
    parsed.defaultSort = {
      field:
        sortRaw.field as ProductDisplaySortField,
      direction:
        sortRaw.direction as ProductDisplaySortDirection,
    };

    return parsed;
  };

export const readProductDisplayPreferences =
  (
    companyId: number,
    driverId: number,
  ): ProductDisplayPreferences => {
    if (
      !positiveSafeInteger(companyId) ||
      !positiveSafeInteger(driverId)
    ) {
      return cloneDefaults();
    }

    try {
      const raw =
        localStorage.getItem(
          scopedKey(
            companyId,
            driverId,
          ),
        );
      if (!raw) {
        return cloneDefaults();
      }
      return parseProductDisplayPreferences(
        JSON.parse(raw) as unknown,
      );
    } catch {
      return cloneDefaults();
    }
  };

export const writeProductDisplayPreferences =
  (
    companyId: number,
    driverId: number,
    preferences: ProductDisplayPreferences,
  ): boolean => {
    if (
      !positiveSafeInteger(companyId) ||
      !positiveSafeInteger(driverId)
    ) {
      return false;
    }

    const parsed =
      parseProductDisplayPreferences(
        preferences,
      );

    try {
      localStorage.setItem(
        scopedKey(
          companyId,
          driverId,
        ),
        JSON.stringify(parsed),
      );
      return true;
    } catch {
      return false;
    }
  };

export const resetProductDisplayPreferences =
  (
    companyId: number,
    driverId: number,
  ): ProductDisplayPreferences => {
    if (
      positiveSafeInteger(companyId) &&
      positiveSafeInteger(driverId)
    ) {
      try {
        localStorage.removeItem(
          scopedKey(
            companyId,
            driverId,
          ),
        );
      } catch {
        // Display preferences are non-critical.
      }
    }
    return cloneDefaults();
  };
