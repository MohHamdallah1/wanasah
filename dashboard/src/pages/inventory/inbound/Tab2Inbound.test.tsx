import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type { CatalogVariant } from "@/features/catalog/contracts";
import i18n, { setAppLanguage } from "@/i18n";
import { inboundStorageKeys } from "./contracts";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("./useInboundPosting", () => ({
  useInboundPosting: () => ({
    post: mocks.post,
    pending: null,
    recoveryError: null,
    online: true,
  }),
}));

vi.mock("@/features/suppliers/SupplierSelector", () => ({
  SupplierSelector: ({ onChange }: { onChange: (value: number) => void }) => (
    <button
      type="button"
      aria-label="choose-supplier"
      onClick={() => onChange(55)}
    >
      supplier
    </button>
  ),
}));

const costPolicy = {
  method: "MOVING_AVERAGE",
  is_selected: true,
  selection_status: "SELECTED",
  selected_at: "2026-10-15T10:00:00Z",
  is_active: false,
  is_locked: false,
  locked_at: null,
  version: 2,
  currency_code: "JOD",
  can_change: true,
};

const makeVariant = (
  id: number,
  name: string,
  lot: CatalogVariant["lot_control_mode"],
  expiry: CatalogVariant["expiry_control_mode"],
): CatalogVariant => ({
  id,
  product_id: id + 100,
  sku: `SKU-${id}`,
  gtin: null,
  name,
  base_uom: { id: 1, code: "EACH", name: "Each" },
  quantity_scale: 0,
  quantity_step: "1",
  lot_control_mode: lot,
  expiry_control_mode: expiry,
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  lifecycle_revision: 1,
  version: 1,
  published_at: "2026-10-01T00:00:00Z",
  retired_at: null,
  archived_at: null,
});

const makeFetch = (
  variants: CatalogVariant[],
  nextCursor: string | null = null,
  purchaseReference: { amount: string; purchase_uom_id: number; currency_code: string; revision: number } | null = null,
) =>
  vi.fn(async (url: string, opts?: RequestInit): Promise<unknown> => {
    if (url.startsWith("/catalog/variants?")) {
      return {
        items: variants,
        next_cursor: nextCursor,
        has_more: nextCursor !== null,
      };
    }
    if (url === "/warehouse/inbound/options") {
      return {
        currency_code: "JOD",
        items: variants.map((item) => ({
          product_variant_id: item.id,
          base_uom_id: 1,
          purchase_cost_reference: purchaseReference,
          uoms: [
            {
              id: 1,
              code: "EACH",
              name: "Each",
              factor_to_base: "1",
            },
          ],
        })),
      };
    }
    if (url === "/warehouse/costing-policy" && !opts?.method) {
      return costPolicy;
    }
    if (url === "/catalog/variants/resolve") {
      const ids = JSON.parse(String(opts?.body)).ids as number[];
      return {
        items: variants.filter((item) => ids.includes(item.id)),
        next_cursor: null,
        has_more: false,
      };
    }
    throw new Error(`Unexpected request: ${url}`);
  });

const renderInbound = (
  variants: CatalogVariant[],
  nextCursor: string | null = null,
  purchaseReference: { amount: string; purchase_uom_id: number; currency_code: string; revision: number } | null = null,
) => {
  const fetch = makeFetch(variants, nextCursor, purchaseReference);
  const view = render(
    <div data-testid="host">
      <Tab2Inbound
        companyId={1}
        actorId={2}
        locationId={3}
        isAuditLocked={false}
        authenticatedFetch={fetch}
        onSuccess={vi.fn()}
      />
    </div>,
  );
  return { ...view, fetch };
};

import { Tab2Inbound } from "../Tab2Inbound";

describe("Checkpoint 1 inbound UI", () => {
  beforeEach(async () => {
    localStorage.clear();
    mocks.post.mockReset();
    mocks.post.mockResolvedValue(true);
    await setAppLanguage("en");
    Object.defineProperty(window, "requestAnimationFrame", {
      configurable: true,
      value: (callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      },
    });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("prefills a pristine receipt cost and does not overwrite the operator's actual edit", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.reference, "INB-PREFILL");
    renderInbound(
      [makeVariant(7, "Reference product", "NONE", "NONE")],
      null,
      { amount: "8.500000", purchase_uom_id: 1, currency_code: "JOD", revision: 2 },
    );
    const row = (await screen.findByText("Reference product")).closest("tr")!;
    const cost = within(row).getByLabelText("Actual cost") as HTMLInputElement;
    await waitFor(() => expect(cost.value).toBe("8.500000"));
    fireEvent.change(cost, { target: { value: "9.250000" } });
    fireEvent.change(within(row).getByLabelText("Quantity"), { target: { value: "2" } });
    await waitFor(() => expect(cost.value).toBe("9.250000"));
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0].items[0].unit_cost).toBe("9.250000");
  });

  it("requires a deliberate future reference choice for distinct receipt-line costs", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.reference, "INB-MIXED");
    localStorage.setItem(keys.drafts, JSON.stringify({
      "7": [
        { row_id: "lot-1", quantity: "2", uom_id: "1", unit_cost: "3.000000",
          batch_number: "LOT1", production_date: "", expiry_date: "" },
        { row_id: "lot-2", quantity: "2", uom_id: "1", unit_cost: "4.000000",
          batch_number: "LOT2", production_date: "", expiry_date: "" },
      ],
    }));
    renderInbound([makeVariant(7, "Mixed product", "OPTIONAL", "NONE")]);
    await screen.findByText("Mixed product");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    expect(mocks.post).not.toHaveBeenCalled();
    const choice = await screen.findByLabelText("Select purchase reference for product 7");
    fireEvent.change(choice, { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0].purchase_reference_selections).toEqual([
      { product_variant_id: 7, uom_id: 1, unit_cost: "4.000000" },
    ]);
    expect(mocks.post.mock.calls[0][0].items.map((x: { unit_cost: string }) => x.unit_cost)).toEqual(["3.000000", "4.000000"]);
  });

  it("renders NONE / OPTIONAL / REQUIRED tracking fields exactly", async () => {
    renderInbound([
      makeVariant(1, "None product", "NONE", "NONE"),
      makeVariant(2, "Optional product", "OPTIONAL", "OPTIONAL"),
      makeVariant(3, "Required product", "REQUIRED", "REQUIRED"),
      makeVariant(4, "Expiry only", "NONE", "OPTIONAL"),
      makeVariant(5, "Lot only", "OPTIONAL", "NONE"),
    ]);

    const noneRow = (await screen.findByText("None product")).closest("tr")!;
    expect(within(noneRow).queryByLabelText("Batch number")).toBeNull();
    expect(within(noneRow).queryByLabelText("Production date")).toBeNull();
    expect(within(noneRow).queryByLabelText("Expiry date")).toBeNull();
    expect(
      within(noneRow).getByText("This product does not use lot or date tracking."),
    ).toBeTruthy();

    const optionalRow = screen.getByText("Optional product").closest("tr")!;
    const optionalLot = within(optionalRow).getByLabelText(
      "Batch number",
    ) as HTMLInputElement;
    const optionalExpiry = within(optionalRow).getByLabelText(
      "Expiry date",
    ) as HTMLInputElement;
    expect(optionalLot.required).toBe(false);
    expect(optionalExpiry.required).toBe(false);
    expect(within(optionalRow).getByLabelText("Production date")).toBeTruthy();

    const requiredRow = screen.getByText("Required product").closest("tr")!;
    expect(
      (within(requiredRow).getByLabelText("Batch number") as HTMLInputElement)
        .required,
    ).toBe(true);
    expect(
      (within(requiredRow).getByLabelText("Expiry date") as HTMLInputElement)
        .required,
    ).toBe(true);
    expect(within(requiredRow).getByLabelText("Production date")).toBeTruthy();

    const expiryOnlyRow = screen.getByText("Expiry only").closest("tr")!;
    expect(within(expiryOnlyRow).queryByLabelText("Batch number")).toBeNull();
    expect(within(expiryOnlyRow).getByLabelText("Production date")).toBeTruthy();
    expect(within(expiryOnlyRow).getByLabelText("Expiry date")).toBeTruthy();

    const lotOnlyRow = screen.getByText("Lot only").closest("tr")!;
    expect(within(lotOnlyRow).getByLabelText("Batch number")).toBeTruthy();
    expect(within(lotOnlyRow).getByLabelText("Production date")).toBeTruthy();
    expect(within(lotOnlyRow).queryByLabelText("Expiry date")).toBeNull();
  });

  it("clears restored hidden tracking values and submits nulls", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(
      keys.drafts,
      JSON.stringify({
        "1": [
          {
            row_id: "persisted-row",
            quantity: "1",
            uom_id: "1",
            unit_cost: "2",
            batch_number: "STALE-LOT",
            production_date: "2026-10-01",
            expiry_date: "2030-01-01",
          },
        ],
      }),
    );
    localStorage.setItem(keys.reference, "INV-1");

    renderInbound([makeVariant(1, "None product", "NONE", "NONE")]);
    await screen.findByText("None product");
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(keys.drafts) ?? "{}");
      expect(saved["1"][0]).toMatchObject({
        batch_number: "",
        production_date: "",
        expiry_date: "",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const payload = mocks.post.mock.calls[0][0];
    expect(payload.items[0]).toMatchObject({
      batch_number: null,
      production_date: null,
      expiry_date: null,
    });
  });

  it("focuses and scrolls the exact invalid row field", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(
      keys.drafts,
      JSON.stringify({
        "1": [
          {
            row_id: "required-row",
            quantity: "1",
            uom_id: "1",
            unit_cost: "2",
            batch_number: "",
            production_date: "",
            expiry_date: "",
          },
        ],
      }),
    );
    localStorage.setItem(keys.reference, "INV-2");
    renderInbound([makeVariant(1, "Required lot", "REQUIRED", "OPTIONAL")]);

    const lot = (await screen.findByLabelText("Batch number")) as HTMLInputElement;
    const row = lot.closest("tr")!;
    const scroll = row.scrollIntoView as ReturnType<typeof vi.fn>;
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));

    await waitFor(() => expect(document.activeElement).toBe(lot));
    expect(scroll).toHaveBeenCalled();
    expect(
      within(row).getByRole("alert").textContent,
    ).toContain("A lot number is required for this product.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("uses deterministic Enter navigation without posting", async () => {
    renderInbound([
      makeVariant(1, "Keyboard", "REQUIRED", "REQUIRED"),
    ]);
    const row = (await screen.findByText("Keyboard")).closest("tr")!;
    const lot = within(row).getByLabelText("Batch number") as HTMLElement;
    const production = within(row).getByLabelText("Production date") as HTMLElement;
    const expiry = within(row).getByLabelText("Expiry date") as HTMLElement;
    const quantity = within(row).getByLabelText("Quantity") as HTMLElement;
    const unit = within(row).getByLabelText("Purchase unit") as HTMLElement;
    const cost = within(row).getByLabelText("Actual cost") as HTMLElement;
    const add = within(row).getByRole("button", {
      name: "Add another quantity/unit for this product",
    });

    lot.focus();
    fireEvent.keyDown(lot, { key: "Enter" });
    expect(document.activeElement).toBe(production);
    fireEvent.keyDown(production, { key: "Enter" });
    expect(document.activeElement).toBe(expiry);
    fireEvent.keyDown(expiry, { key: "Enter" });
    expect(document.activeElement).toBe(quantity);
    fireEvent.keyDown(quantity, { key: "Enter" });
    expect(document.activeElement).toBe(unit);
    fireEvent.keyDown(unit, { key: "Enter" });
    expect(document.activeElement).toBe(cost);
    fireEvent.keyDown(cost, { key: "Enter" });
    expect(document.activeElement).toBe(add);
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.click(add);
    await waitFor(() => {
      const lots = screen.getAllByLabelText("Batch number");
      expect(document.activeElement).toBe(lots[1]);
    });
  });

  it("does not duplicate a receipt while the first post is in flight", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(
      keys.drafts,
      JSON.stringify({
        "1": [
          {
            row_id: "single-flight-row",
            quantity: "1",
            uom_id: "1",
            unit_cost: "2",
            batch_number: "LOT-1",
            production_date: "",
            expiry_date: "",
          },
        ],
      }),
    );
    localStorage.setItem(keys.reference, "INV-SINGLE-FLIGHT");
    let resolvePost: ((value: boolean) => void) | undefined;
    mocks.post.mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          resolvePost = resolve;
        }),
    );

    renderInbound([
      makeVariant(1, "Single flight", "REQUIRED", "OPTIONAL"),
    ]);
    await screen.findByText("Single flight");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    const submit = screen.getByRole("button", { name: "Post receipt" });
    await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    resolvePost?.(true);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  });

  it("updates AR/EN direction and pagination chevrons", async () => {
    const { container } = renderInbound(
      [makeVariant(1, "Locale", "REQUIRED", "OPTIONAL")],
      "next",
    );
    await screen.findByText("Locale");
    const root = container.querySelector(".inventory-inbound")!;
    expect(root.getAttribute("dir")).toBe("ltr");
    expect(screen.getByText("Required")).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Next page" })
        .querySelector("svg")
        ?.classList.contains("lucide-chevron-right"),
    ).toBe(true);

    await act(async () => {
      await setAppLanguage("ar");
    });
    await waitFor(() => expect(root.getAttribute("dir")).toBe("rtl"));
    expect(
      screen.getByText(i18n.t("inventoryInbound.required")),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("button", {
          name: i18n.t("inventoryInbound.nextPage"),
        })
        .querySelector("svg")
        ?.classList.contains("lucide-chevron-left"),
    ).toBe(true);
  });
  it("keeps frozen inbound lot backend codes localized in AR + EN", () => {
    for (const language of ["ar", "en"] as const) {
      for (const code of [
        "INBOUND_LOT_REQUIRED",
        "INBOUND_LOT_NOT_ALLOWED",
        "INBOUND_LOT_RESERVED",
        "INBOUND_ANONYMOUS_BATCH_COLLISION",
      ]) {
        expect(i18n.exists(`errors.codes.${code}`, { lng: language })).toBe(true);
      }
    }
  });
});
