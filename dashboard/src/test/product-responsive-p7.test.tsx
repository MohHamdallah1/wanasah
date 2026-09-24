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

import {
  useMediaQuery,
} from "@/hooks/useMediaQuery";

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
        "src/pages/ProductsDashboard.tsx",
      );

      expect(page).toContain(
        'useMediaQuery(\n      "(max-width: 767px)"',
      );
      expect(page).toContain(
        "{isNarrowViewport ? (",
      );
      expect(page).toContain(
        "<ProductMobileCard",
      );
      expect(page).toContain(
        "<ProductTableRow",
      );
      expect(page).not.toContain(
        'min-w-[260px]',
      );
      expect(page).toContain(
        "grid w-full grid-cols-2",
      );
    });

    it("keeps narrow Product content and long translated labels wrap-safe", () => {
      const files = [
        read(
          "src/pages/ProductsDashboard.tsx",
        ),
        read(
          "src/pages/products/ProductMobileCard.tsx",
        ),
        read(
          "src/pages/products/ProductDetailDrawer.tsx",
        ),
        read(
          "src/pages/products/ProductFamiliesManager.tsx",
        ),
        read(
          "src/pages/products/ProductBarcodeManager.tsx",
        ),
        read(
          "src/pages/products/AdvancedUomDashboard.tsx",
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

    it("keeps Product modal, drawer, managers, and Advanced UOM usable on narrow viewports", () => {
      const modal = read(
        "src/components/ui/modal.tsx",
      );
      const drawer = read(
        "src/pages/products/ProductDetailDrawer.tsx",
      );
      const families = read(
        "src/pages/products/ProductFamiliesManager.tsx",
      );
      const barcodes = read(
        "src/pages/products/ProductBarcodeManager.tsx",
      );
      const advanced = read(
        "src/pages/products/AdvancedUomDashboard.tsx",
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
