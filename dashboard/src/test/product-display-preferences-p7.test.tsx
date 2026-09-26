import {
  cleanup,
  render,
  screen,
  within,
} from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  readFileSync,
} from "node:fs";
import {
  resolve,
} from "node:path";

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (
        key: string,
        options?: {
          defaultValue?: string;
        },
      ) =>
        options?.defaultValue ??
        key,
      i18n: {
        language: "en",
        resolvedLanguage:
          "en-US",
        dir: () => "ltr",
      },
    }),
  }),
);

import {
  clearLocalStoragePreservingLoginHintsAndPreferences,
  rememberLastCompanyCode,
} from "@/lib/authStorage";
import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
  readProductDisplayPreferences,
  writeProductDisplayPreferences,
  type ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import {
  ProductTableRow,
} from "@/pages/products/list/ProductTableRow";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

const read = (...parts: string[]) =>
  readFileSync(
    resolve(
      process.cwd(),
      ...parts,
    ),
    "utf8",
  );

const normalizeWhitespace = (
  value: string,
) =>
  value
    .replace(/\s+/g, " ")
    .trim();

const clonePreferences =
  (): ProductDisplayPreferences => ({
    version:
      DEFAULT_PRODUCT_DISPLAY_PREFERENCES.version,
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

const product: SimpleProduct = {
  id: 10,
  product_id: 4,
  name: "Preference Product",
  family_name:
    "Preference Family",
  sku: "SKU-PREF",
  units_per_package: 50,
  legacy_packs_per_carton: 50,
  base_uom_id: 1,
  base_uom_code: "EACH",
  package_uom_id: 2,
  package_uom_code:
    "CARTON",
  currency_code: "JOD",
  package_price: "13.500000",
  unit_price: "0.270000",
  unit_barcode:
    "1111111111111",
  package_barcode:
    "2222222222222",
  package_uses_base_barcode:
    false,
  version: 3,
  lot_control_mode:
    "OPTIONAL",
  expiry_control_mode:
    "NONE",
  lifecycle_status:
    "ACTIVE",
  operational_hold:
    "NONE",
  simple_compatible: true,
};

describe(
  "Products P7 display preference contracts",
  () => {
    beforeEach(() => {
      localStorage.clear();
    });

    afterEach(() => {
      cleanup();
      localStorage.clear();
    });

    it("scopes persisted display preferences by company and user", () => {
      const custom =
        clonePreferences();
      custom.density = "compact";
      custom.columns.lifecycle =
        true;
      custom.defaultSort = {
        field: "name",
        direction: "desc",
      };
      custom.detailSections.barcodes =
        false;

      expect(
        writeProductDisplayPreferences(
          11,
          101,
          custom,
        ),
      ).toBe(true);

      expect(
        readProductDisplayPreferences(
          11,
          101,
        ),
      ).toEqual(custom);

      expect(
        readProductDisplayPreferences(
          11,
          102,
        ),
      ).toEqual(
        DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
      );

      expect(
        readProductDisplayPreferences(
          12,
          101,
        ),
      ).toEqual(
        DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
      );

      const keys = Array.from(
        {
          length:
            localStorage.length,
        },
        (_, index) =>
          localStorage.key(index),
      ).filter(
        (key): key is string =>
          key !== null,
      );

      expect(keys).toEqual([
        expect.stringContaining(
          ":11:101",
        ),
      ]);
    });

    it("fails closed to defaults for invalid or unsupported stored schemas", () => {
      const custom =
        clonePreferences();
      custom.density = "compact";

      writeProductDisplayPreferences(
        7,
        9,
        custom,
      );

      const key =
        localStorage.key(0);
      expect(key).not.toBeNull();

      localStorage.setItem(
        key as string,
        JSON.stringify({
          ...custom,
          version: 999,
        }),
      );
      expect(
        readProductDisplayPreferences(
          7,
          9,
        ),
      ).toEqual(
        DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
      );

      localStorage.setItem(
        key as string,
        "{not-json",
      );
      expect(
        readProductDisplayPreferences(
          7,
          9,
        ),
      ).toEqual(
        DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
      );
    });

    it("preserves non-sensitive scoped preferences across logout while clearing session credentials", () => {
      const custom =
        clonePreferences();
      custom.columns.lifecycle =
        true;

      writeProductDisplayPreferences(
        3,
        44,
        custom,
      );
      rememberLastCompanyCode(
        "ACME-03",
      );
      localStorage.setItem(
        "admin_token",
        "secret-token",
      );
      localStorage.setItem(
        "refresh_token",
        "secret-refresh",
      );
      localStorage.setItem(
        "company_id",
        "3",
      );
      localStorage.setItem(
        "driver_id",
        "44",
      );

      clearLocalStoragePreservingLoginHintsAndPreferences();

      expect(
        localStorage.getItem(
          "admin_token",
        ),
      ).toBeNull();
      expect(
        localStorage.getItem(
          "refresh_token",
        ),
      ).toBeNull();
      expect(
        localStorage.getItem(
          "company_id",
        ),
      ).toBeNull();
      expect(
        localStorage.getItem(
          "driver_id",
        ),
      ).toBeNull();
      expect(
        localStorage.getItem(
          "wanasah_last_company_code",
        ),
      ).toBe("ACME-03");
      expect(
        readProductDisplayPreferences(
          3,
          44,
        ),
      ).toEqual(custom);
    });

    it("renders only selected Product columns and applies table density", () => {
      const columns = {
        ...DEFAULT_PRODUCT_DISPLAY_PREFERENCES.columns,
        package: false,
        unitsPerPackage: false,
        tracking: false,
        lifecycle: true,
        unitBarcode: true,
        packageBarcode: false,
        packagePrice: false,
        unitPrice: true,
      };

      render(
        <table>
          <tbody>
            <ProductTableRow
              item={product}
              rowNumber={1}
              pricingVisible
              canEditPrice={false}
              canEditTracking={false}
              columns={columns}
              density="compact"
              onOpenDetails={vi.fn()}
              onEditPrice={vi.fn()}
              onEditTracking={vi.fn()}
            />
          </tbody>
        </table>,
      );

      const row =
        screen
          .getByText(
            "Preference Product",
          )
          .closest("tr");
      expect(row).not.toBeNull();

      const scope = within(
        row as HTMLTableRowElement,
      );

      expect(
        scope.getByText(
          "products.details.lifecycleModes.ACTIVE",
        ),
      ).toBeInTheDocument();
      expect(
        scope.getByText(
          "1111111111111",
        ),
      ).toBeInTheDocument();
      expect(
        scope.getByText(
          "JOD 0.270",
        ),
      ).toBeInTheDocument();

      expect(
        scope.queryByText(
          "uom.CARTON",
        ),
      ).not.toBeInTheDocument();
      expect(
        scope.queryByText(
          "13.500 JOD",
        ),
      ).not.toBeInTheDocument();
      expect(
        row?.innerHTML,
      ).toContain(
        "px-4 py-2.5",
      );
    });

    it("keeps display preferences separate from business defaults and permission authority", () => {
      const storage = read(
        "src/lib/productDisplayPreferences.ts",
      );
      const page = read(
        "src/pages/products/ProductsPage.tsx",
      );
      const drawer = read(
        "src/pages/products/detail/ProductDetailDrawer.tsx",
      );
      const detailWorkflow = normalizeWhitespace(
        read(
          "src/pages/products/detail/useProductDetailWorkflow.ts",
        ),
      );
      const editor = read(
        "src/pages/products/display-preferences/ProductDisplayPreferencesModal.tsx",
      );
      const stateOwner = read(
        "src/pages/products/display-preferences/useProductDisplayPreferencesState.ts",
      );
      const actionsOwner = normalizeWhitespace(
        read(
          "src/pages/products/display-preferences/createProductDisplayPreferenceActions.ts",
        ),
      );
      const listViewOwner = read(
        "src/pages/products/list/deriveProductsListViewState.ts",
      );

      expect(storage).toContain(
        "companyId",
      );
      expect(storage).toContain(
        "driverId",
      );
      expect(storage).not.toContain(
        "SystemSetting",
      );
      expect(storage).not.toContain(
        "/tenant/",
      );

      expect(stateOwner).toContain(
        "readProductDisplayPreferences(",
      );
      expect(stateOwner).toContain(
        '"company_id"',
      );
      expect(stateOwner).toContain(
        '"driver_id"',
      );
      expect(actionsOwner).toContain(
        "writeProductDisplayPreferences(",
      );
      expect(actionsOwner).toContain(
        "setSortBy( next.defaultSort.field )",
      );
      expect(actionsOwner).toContain(
        "setSortDir( next.defaultSort.direction )",
      );
      expect(actionsOwner).toContain(
        "resetProductPagination()",
      );
      expect(actionsOwner).toContain(
        "setDisplayPreferencesOpen(false)",
      );
      expect(page).toContain(
        "useProductDisplayPreferencesState()",
      );
      expect(page).toContain(
        "createProductDisplayPreferenceActions({",
      );

      expect(listViewOwner).toContain(
        "pricingVisible &&",
      );
      expect(listViewOwner).toContain(
        "visibleColumns.packagePrice",
      );
      expect(listViewOwner).toContain(
        "visibleColumns.unitPrice",
      );
      expect(listViewOwner).toContain(
        "displayPreferences.defaultSort",
      );
      expect(page).toContain(
        "detailSections:",
      );
      expect(page).toContain(
        ".detailSections",
      );
      expect(detailWorkflow).toContain(
        "detailSections,",
      );

      expect(drawer).toContain(
        "detailSections.package",
      );
      expect(drawer).toContain(
        "detailSections.tracking",
      );
      expect(drawer).toContain(
        "detailSections.barcodes",
      );
      expect(drawer).toContain(
        "detailSections.pricing",
      );
      expect(drawer).toContain(
        "detailSections.compatibility",
      );

      expect(editor).toContain(
        "pricingAvailable",
      );
      expect(editor).toContain(
        "disabled={",
      );
      expect(editor).toContain(
        "DEFAULT_PRODUCT_DISPLAY_PREFERENCES",
      );
    });
  },
);
