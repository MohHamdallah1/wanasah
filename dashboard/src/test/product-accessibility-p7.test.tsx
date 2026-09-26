import {
  useState,
} from "react";
import {
  cleanup,
  fireEvent,
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

import {
  useDialogFocusTrap,
} from "@/hooks/useDialogFocusTrap";

const read = (...parts: string[]) =>
  readFileSync(
    resolve(
      process.cwd(),
      ...parts,
    ),
    "utf8",
  );

function FocusTrapHarness() {
  const [open, setOpen] =
    useState(false);
  const dialogRef =
    useDialogFocusTrap<HTMLDivElement>(
      open,
      () => setOpen(false),
    );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
      >
        Open
      </button>
      {open ? (
        <div
          ref={dialogRef}
          tabIndex={-1}
          role="dialog"
        >
          <button type="button">
            First
          </button>
          <button type="button">
            Last
          </button>
        </div>
      ) : null}
    </>
  );
}

describe(
  "Products P7 accessibility contracts",
  () => {
    beforeEach(() => {
      vi.spyOn(
        window,
        "requestAnimationFrame",
      ).mockImplementation(
        (callback) => {
          callback(0);
          return 1;
        },
      );
      vi.spyOn(
        window,
        "cancelAnimationFrame",
      ).mockImplementation(
        () => undefined,
      );
    });

    afterEach(() => {
      cleanup();
      vi.restoreAllMocks();
    });

    it("traps keyboard focus, closes on Escape, and restores opener focus", () => {
      render(<FocusTrapHarness />);

      const opener =
        screen.getByRole("button", {
          name: "Open",
        });
      opener.focus();
      expect(opener).toHaveFocus();
      fireEvent.click(opener);

      const first =
        screen.getByRole("button", {
          name: "First",
        });
      const last =
        screen.getByRole("button", {
          name: "Last",
        });

      expect(first).toHaveFocus();

      last.focus();
      fireEvent.keyDown(document, {
        key: "Tab",
      });
      expect(first).toHaveFocus();

      first.focus();
      fireEvent.keyDown(document, {
        key: "Tab",
        shiftKey: true,
      });
      expect(last).toHaveFocus();

      fireEvent.keyDown(document, {
        key: "Escape",
      });
      expect(
        screen.queryByRole("dialog"),
      ).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
    });

    it("keeps Product dialogs, drawer, searches, pagination, and focus styles accessible", () => {
      const modal = read(
        "src/components/ui/modal.tsx",
      );
      const drawer = read(
        "src/pages/products/detail/ProductDetailDrawer.tsx",
      );
      const listToolbar = read(
        "src/pages/products/list/ProductsListToolbar.tsx",
      );
      const listResults = read(
        "src/pages/products/list/ProductsListResults.tsx",
      );
      const familiesToolbar = read(
        "src/pages/products/family/ProductFamiliesToolbar.tsx",
      );
      const advancedUom = read(
        "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
      );
      const css = read(
        "src/index.css",
      );

      expect(modal).toContain(
        "useDialogFocusTrap<HTMLDivElement>",
      );
      expect(drawer).toContain(
        "useDialogFocusTrap<HTMLElement>",
      );
      expect(drawer).toContain(
        'role="dialog"',
      );
      expect(drawer).toContain(
        "tabIndex={-1}",
      );

      expect(listToolbar).toMatch(
        /aria-label=\{t\(\s*"products\.searchPlaceholder"/,
      );
      expect(listResults).toMatch(
        /aria-label=\{t\(\s*"products\.familyPrevious"/,
      );
      expect(listResults).toMatch(
        /aria-label=\{t\(\s*"products\.familyNext"/,
      );
      expect(familiesToolbar).toMatch(
        /aria-label=\{t\(\s*"products\.familySearchPlaceholder"/,
      );
      expect(advancedUom).toMatch(
        /aria-label=\{t\(\s*"products\.advancedUom\.searchPlaceholder"/,
      );

      expect(css).toContain(
        ".products-a11y-scope :where(",
      );
      expect(css).toContain(
        "):focus-visible",
      );
    });

    it("associates client validation errors with fields and focuses the first invalid control", () => {
      const dashboard = read(
        "src/pages/products/ProductsPage.tsx",
      );
      const createIdentity = read(
        "src/pages/products/create/CreateProductIdentitySection.tsx",
      );
      const createCommerce = read(
        "src/pages/products/create/CreateProductCommerceSection.tsx",
      );
      const createMutation = read(
        "src/pages/products/create/useCreateProductMutation.ts",
      );
      const priceModal = read(
        "src/pages/products/pricing/PriceEditModal.tsx",
      );
      const priceMutation = read(
        "src/pages/products/pricing/usePriceEditMutation.ts",
      );
      const families = read(
        "src/pages/products/family/ProductFamiliesManager.tsx",
      );
      const familiesToolbar = read(
        "src/pages/products/family/ProductFamiliesToolbar.tsx",
      );
      const advancedUom = read(
        "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
      );

      expect(createIdentity).toContain(
        "product-name-error",
      );
      for (const id of [
        "product-units-error",
        "product-package-price-error",
        "product-unit-price-error",
      ]) {
        expect(createCommerce).toContain(
          id,
        );
      }
      for (const id of [
        "edit-package-price-error",
        "edit-unit-price-error",
      ]) {
        expect(priceModal).toContain(
          id,
        );
      }
      expect(createMutation).toContain(
        "createNameRef.current?.focus()",
      );
      expect(createMutation).toContain(
        "createUnitsRef.current?.focus()",
      );
      expect(priceMutation).toContain(
        "setPriceFieldError",
      );
      expect(priceMutation).toContain(
        "editPackagePriceRef",
      );
      expect(priceMutation).toContain(
        "editUnitPriceRef",
      );
      expect(priceMutation).toContain(
        ".current?.focus()",
      );

      expect(familiesToolbar).toContain(
        "product-family-name-error",
      );
      expect(families).toContain(
        "newFamilyRef.current?.focus()",
      );

      for (const id of [
        "advanced-uom-from-error",
        "advanced-uom-to-error",
        "advanced-uom-numerator-error",
        "advanced-uom-denominator-error",
        "advanced-uom-scale-error",
      ]) {
        expect(advancedUom).toContain(
          id,
        );
      }
      expect(advancedUom).toContain(
        "fromUomRef.current?.focus()",
      );
      expect(advancedUom).toContain(
        "numeratorRef.current?.focus()",
      );
      expect(advancedUom).toContain(
        "scaleRef.current?.focus()",
      );
    });

    it("keeps Product status meaning available as text rather than color alone", () => {
      const row = read(
        "src/pages/products/list/ProductTableRow.tsx",
      );
      const drawer = read(
        "src/pages/products/detail/ProductDetailDrawer.tsx",
      );
      const barcodes = read(
        "src/pages/products/barcode/ProductBarcodeList.tsx",
      );
      const advancedUom = read(
        "src/pages/products/advanced-uom/AdvancedUomDashboard.tsx",
      );

      expect(row).toContain(
        "products.tracking.shortModes.",
      );
      expect(drawer).toContain(
        "products.details.lifecycleModes.",
      );
      expect(barcodes).toContain(
        "products.barcodeManager.primary",
      );
      expect(barcodes).toContain(
        "products.barcodeManager.inactive",
      );
      expect(advancedUom).toContain(
        "products.advancedUom.lockedAfterPublish",
      );
      expect(advancedUom).toContain(
        "products.advancedUom.draftEditable",
      );
      expect(advancedUom).toContain(
        "products.advancedUom.readOnly",
      );
    });
  },
);
