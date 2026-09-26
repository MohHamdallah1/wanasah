import {
  forwardRef,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { Modal } from "@/components/ui/modal";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductRowActions } from "@/pages/products/list/ProductRowActions";

vi.mock(
  "framer-motion",
  () => ({
    AnimatePresence: ({
      children,
    }: {
      children: ReactNode;
    }) => <>{children}</>,
    motion: {
      div: forwardRef<
        HTMLDivElement,
        HTMLAttributes<HTMLDivElement> & {
          initial?: unknown;
          animate?: unknown;
          exit?: unknown;
        }
      >(
        (
          {
            initial: _initial,
            animate: _animate,
            exit: _exit,
            ...props
          },
          ref,
        ) => (
          <div
            ref={ref}
            {...props}
          />
        ),
      ),
    },
  }),
);

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (key: string) => key,
      i18n: {
        dir: () => "rtl",
      },
    }),
  }),
);

const product: SimpleProduct = {
  id: 10,
  product_id: 1,
  name: "Product",
  family_name: "Family",
  sku: "SKU-10",
  units_per_package: 1,
  legacy_packs_per_carton: 1,
  base_uom_id: 1,
  package_uom_id: null,
  package_uom_code: null,
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 1,
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
};

type Surface =
  | "details"
  | "price"
  | "family"
  | "tracking";

function HandoffHarness() {
  const [
    surface,
    setSurface,
  ] = useState<Surface | null>(
    null,
  );
  const insideRef =
    useRef<HTMLButtonElement | null>(
      null,
    );

  return (
    <>
      <ProductRowActions
        item={product}
        canEditPrice
        canReassignFamily
        canEditTracking
        onOpenDetails={() =>
          setSurface("details")
        }
        onEditPrice={() =>
          setSurface("price")
        }
        onReassignFamily={() =>
          setSurface("family")
        }
        onEditTracking={() =>
          setSurface("tracking")
        }
      />

      <Modal
        isOpen={surface !== null}
        onClose={() =>
          setSurface(null)
        }
        title={
          surface ?? "closed"
        }
        initialFocusRef={
          insideRef
        }
      >
        <button
          ref={insideRef}
          type="button"
        >
          inside-surface
        </button>
      </Modal>
    </>
  );
}

describe(
  "Product row action focus handoff",
  () => {
    const originalResizeObserver =
      globalThis.ResizeObserver;
    const originalRaf =
      window.requestAnimationFrame;
    const originalCancelRaf =
      window.cancelAnimationFrame;

    beforeAll(() => {
      class ResizeObserverMock {
        observe() {}
        unobserve() {}
        disconnect() {}
      }

      globalThis.ResizeObserver =
        ResizeObserverMock as typeof ResizeObserver;
    });

    afterAll(() => {
      globalThis.ResizeObserver =
        originalResizeObserver;
      window.requestAnimationFrame =
        originalRaf;
      window.cancelAnimationFrame =
        originalCancelRaf;
    });

    beforeEach(() => {
      window.requestAnimationFrame = (
        callback: FrameRequestCallback,
      ) =>
        window.setTimeout(
          () =>
            callback(
              performance.now(),
            ),
          0,
        ) as unknown as number;
      window.cancelAnimationFrame = (
        id: number,
      ) =>
        window.clearTimeout(id);
    });

    afterEach(() => {
      cleanup();
    });

    it.each([
      [
        "products.details.open",
        "details",
      ],
      [
        "products.editPrice",
        "price",
      ],
      [
        "products.familyReassign.action",
        "family",
      ],
      [
        "products.trackingEditor.action",
        "tracking",
      ],
    ] as const)(
      "fully closes the row menu before opening %s and moves focus inside",
      async (
        actionLabel,
        expectedTitle,
      ) => {
        render(
          <HandoffHarness />,
        );

        const trigger =
          screen.getByRole(
            "button",
            {
              name:
                "products.columns.action",
            },
          );
        trigger.focus();
        fireEvent.click(trigger);

        const item =
          await screen.findByRole(
            "menuitem",
            {
              name:
                actionLabel,
            },
          );
        fireEvent.click(item);

        const dialog =
          await screen.findByRole(
            "dialog",
          );

        await waitFor(() => {
          expect(
            screen.queryByRole(
              "menu",
            ),
          ).not.toBeInTheDocument();
          expect(
            screen.getByText(
              expectedTitle,
            ),
          ).toBeInTheDocument();
          expect(
            screen.getByRole(
              "button",
              {
                name:
                  "inside-surface",
              },
            ),
          ).toHaveFocus();
          expect(
            dialog.contains(
              document.activeElement,
            ),
          ).toBe(true);
        });
      },
    );
  },
);
