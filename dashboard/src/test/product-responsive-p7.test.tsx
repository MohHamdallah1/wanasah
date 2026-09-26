import {
  act,
  cleanup,
  render,
  screen,
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
        `LONG_TRANSLATED_LABEL_${key}_ABCDEFGHIJKLMNOPQRSTUVWXYZ`,
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
  useMediaQuery,
} from "@/hooks/useMediaQuery";
import {
  ProductMobileCard,
} from "@/pages/products/list/ProductMobileCard";
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

function MediaHarness() {
  const narrow =
    useMediaQuery(
      "(max-width: 767px)",
    );
  return (
    <span>
      {narrow ? "narrow" : "wide"}
    </span>
  );
}

const product: SimpleProduct = {
  id: 77,
  product_id: 7,
  name:
    "Extremely Long Product Name For Narrow Viewport Verification",
  family_name:
    "Extremely Long Family Name For Narrow Viewport Verification",
  sku:
    "SKU-VERY-LONG-UNBROKEN-IDENTITY-1234567890",
  units_per_package: 50,
  legacy_packs_per_carton: 50,
  base_uom_id: 1,
  package_uom_id: 2,
  package_uom_code:
    "CARTON",
  currency_code: "JOD",
  package_price:
    "1000000000000.123456",
  unit_price:
    "20000000000.002469",
  unit_barcode: null,
  package_barcode: null,
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
  "Products P7 responsive contracts",
  () => {
    const listeners =
      new Set<() => void>();
    let matches = false;

    beforeEach(() => {
      matches = false;
      listeners.clear();
      vi.stubGlobal(
        "matchMedia",
        vi.fn().mockImplementation(
          (query: string) => ({
            media: query,
            get matches() {
              return matches;
            },
            onchange: null,
            addEventListener: (
              event: string,
              listener: () => void,
            ) => {
              if (
                event === "change"
              ) {
                listeners.add(
                  listener,
                );
              }
            },
            removeEventListener: (
              event: string,
              listener: () => void,
            ) => {
              if (
                event === "change"
              ) {
                listeners.delete(
                  listener,
                );
              }
            },
            dispatchEvent: () =>
              true,
          }),
        ),
      );
    });

    afterEach(() => {
      cleanup();
      vi.unstubAllGlobals();
    });

    it("reacts to viewport media-query changes without requiring reload", () => {
      render(<MediaHarness />);

      expect(
        screen.getByText("wide"),
      ).toBeInTheDocument();

      act(() => {
        matches = true;
        listeners.forEach(
          (listener) =>
            listener(),
        );
      });

      expect(
        screen.getByText(
          "narrow",
        ),
      ).toBeInTheDocument();

      act(() => {
        matches = false;
        listeners.forEach(
          (listener) =>
            listener(),
        );
      });

      expect(
        screen.getByText("wide"),
      ).toBeInTheDocument();
    });

    it("uses mobile Product cards instead of the wide table on narrow screens", () => {
      const page = read(
        "src/pages/products/ProductsPage.tsx",
      );
      const listResults = read(
        "src/pages/products/list/ProductsListResults.tsx",
      );
      const header = read(
        "src/pages/products/ProductsPageHeader.tsx",
      );

      expect(page).toMatch(
        /useMediaQuery\(\s*["']\(max-width: 767px\)["']\s*\)/,
      );
      expect(page).toMatch(
        /results=\{\{[\s\S]*?listWorkflow\.section\.results,[\s\S]*?\bisNarrowViewport,[\s\S]*?\bcanEditPrice:/,
      );
      expect(listResults).toContain(
        "{isNarrowViewport ? (",
      );
      expect(listResults).toContain(
        "<ProductMobileCard",
      );
      expect(listResults).toContain(
        "<ProductTableRow",
      );
      expect(listResults).not.toContain(
        'min-w-[260px]',
      );
      expect(header).toContain(
        "flex w-full min-w-0 items-center gap-2",
      );
      expect(header).toContain(
        "sm:w-auto sm:justify-end",
      );
    });

    it("keeps narrow Product content and long translated labels wrap-safe", () => {
      const files = [
        read(
          "src/pages/products/ProductsPage.tsx",
        ),
        read(
          "src/pages/products/list/ProductMobileCard.tsx",
        ),
        read(
          "src/pages/products/detail/ProductDetailDrawer.tsx",
        ),
        read(
          "src/pages/products/family/ProductFamiliesManager.tsx",
        ),
        read(
          "src/pages/products/barcode/ProductBarcodeManager.tsx",
        ),
        read(
          "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
        ),
        read(
          "src/pages/products/list/ProductsListResults.tsx",
        ),
        read(
          "src/pages/products/create/CreateProductModal.tsx",
        ),
        read(
          "src/pages/products/import/ImportProductModal.tsx",
        ),
        read(
          "src/pages/products/pricing/PriceEditModal.tsx",
        ),
        read(
          "src/pages/products/display-preferences/ProductDisplayPreferencesModal.tsx",
        ),
        read(
          "src/pages/products/ProductsPageHeader.tsx",
        ),
      ];

      for (const source of files) {
        expect(source).not.toContain(
          "whitespace-nowrap",
        );
      }

      const card = files[1];
      expect(card).toContain(
        "break-words",
      );
      expect(card).toContain(
        "break-all",
      );
      expect(card).toContain(
        "min-[360px]:grid-cols-2",
      );

      const families =
        files[3];
      expect(families).toContain(
        "break-words text-sm text-slate-900 sm:truncate",
      );

      const advanced =
        files[5];
      expect(advanced).toContain(
        "break-all font-mono",
      );
    });

    it("renders long translated Product labels without replacing or truncating their text", () => {
      render(
        <ProductMobileCard
          item={product}
          pricingVisible
          canEditPrice
          canEditTracking
          onOpenDetails={vi.fn()}
          onEditPrice={vi.fn()}
          onEditTracking={vi.fn()}
        />,
      );

      expect(
        screen.getByText(
          "Extremely Long Product Name For Narrow Viewport Verification",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "Extremely Long Family Name For Narrow Viewport Verification",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole(
          "button",
          {
            name:
              "LONG_TRANSLATED_LABEL_products.details.open_ABCDEFGHIJKLMNOPQRSTUVWXYZ",
          },
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole(
          "button",
          {
            name:
              "LONG_TRANSLATED_LABEL_products.trackingEditor.action_ABCDEFGHIJKLMNOPQRSTUVWXYZ",
          },
        ),
      ).toBeInTheDocument();
    });

    it("keeps Product modal, drawer, managers, and Advanced UOM usable on narrow viewports", () => {
      const modal = read(
        "src/components/ui/modal.tsx",
      );
      const drawer = read(
        "src/pages/products/detail/ProductDetailDrawer.tsx",
      );
      const families = read(
        "src/pages/products/family/ProductFamiliesManager.tsx",
      );
      const barcodes = read(
        "src/pages/products/barcode/ProductBarcodeManager.tsx",
      );
      const advanced = read(
        "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
      );

      expect(modal).toContain(
        "max-h-[calc(100dvh-1rem)]",
      );
      expect(modal).toContain(
        "flex-col-reverse",
      );
      expect(modal).toContain(
        "[&>button]:w-full",
      );

      expect(drawer).toContain(
        "grid shrink-0 grid-cols-1",
      );
      expect(drawer).toContain(
        "sm:w-auto",
      );

      expect(families).toContain(
        "flex flex-col items-stretch",
      );
      expect(barcodes).toContain(
        "flex flex-col items-stretch",
      );

      expect(advanced).toContain(
        "overflow-y-auto",
      );
      expect(advanced).toContain(
        "max-h-[45dvh]",
      );
      expect(advanced).toContain(
        "lg:overflow-hidden",
      );
    });
  },
);
