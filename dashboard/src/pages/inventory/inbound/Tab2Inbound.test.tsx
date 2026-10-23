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
import { inboundStorageKeys, type CostPolicy } from "./contracts";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("./useInboundPosting", () => ({
  useInboundPosting: () => ({
    post: mocks.post,
    pending: null,
    recoveryRequired: false,
    recoveryError: null,
    online: true,
  }),
}));

vi.mock("@/features/suppliers/SupplierSelector", () => ({
  SupplierSelector: ({
    onChange,
    required,
    invalid,
  }: {
    onChange: (value: number) => void;
    required?: boolean;
    invalid?: boolean;
  }) => (
    <button
      type="button"
      aria-label="choose-supplier"
      aria-required={required}
      aria-invalid={invalid}
      onClick={() => onChange(55)}
    >
      supplier
    </button>
  ),
}));

const costPolicy: CostPolicy = {
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
  policy: CostPolicy = costPolicy,
  resolvedVariants: CatalogVariant[] = variants,
  suggestedCost: string | null = null,
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
        as_of_date: "2026-10-22",
        items: [...variants, ...resolvedVariants]
          .filter((item) => (JSON.parse(String(opts?.body)).ids as number[]).includes(item.id))
          .map((item) => ({
          product_variant_id: item.id,
          base_uom_id: 1,
          purchase_cost_reference: suggestedCost === null ? null : {
            amount: suggestedCost, purchase_uom_id: 1, currency_code: "JOD", revision: 2,
          },
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
    if (url === "/warehouse/costing-policy") {
      if (opts?.method === "PUT") {
        const body = JSON.parse(String(opts.body)) as { method: "MOVING_AVERAGE" | "FIFO" };
        return {
          ...policy,
          method: body.method,
          is_selected: true,
          selection_status: "SELECTED",
          selected_at: "2026-10-20T00:00:00Z",
        };
      }
      return policy;
    }
    if (url === "/catalog/variants/resolve") {
      const ids = JSON.parse(String(opts?.body)).ids as number[];
      return {
        items: resolvedVariants.filter((item) => ids.includes(item.id)),
        next_cursor: null,
        has_more: false,
      };
    }
    throw new Error(`Unexpected request: ${url}`);
  });

const renderInbound = (
  variants: CatalogVariant[],
  nextCursor: string | null = null,
  policy: CostPolicy = costPolicy,
  resolvedVariants: CatalogVariant[] = variants,
  suggestedCost: string | null = null,
  isAuditLocked = false,
  auditLockReference: string | null = null,
) => {
  const fetch = makeFetch(variants, nextCursor, policy, resolvedVariants, suggestedCost);
  const view = render(
    <div data-testid="host">
      <Tab2Inbound
        companyId={1}
        actorId={2}
        locationId={3}
        isAuditLocked={isAuditLocked}
        auditLockReference={auditLockReference}
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
    Object.defineProperty(globalThis, "ResizeObserver", {
      configurable: true,
      value: class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    });
  });

  it("prefills the default purchase reference but preserves the operator's actual edit", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.reference, "INV-REFERENCE");
    renderInbound([makeVariant(7, "Reference product", "NONE", "NONE")], null,
      costPolicy, [makeVariant(7, "Reference product", "NONE", "NONE")], "4.250000");
    const row = (await screen.findByText("Reference product")).closest("tr")!;
    const cost = within(row).getByLabelText("Actual cost") as HTMLInputElement;
    await waitFor(() => expect(cost.value).toBe("4.25"));
    expect(cost.disabled).toBe(false);
    expect(within(row).queryByRole("button", { name: "Edit actual purchase cost" })).toBeNull();
    const referenceButton = within(row).getByRole("button", { name: "Use reference cost 4.25 JOD" });
    expect(referenceButton).toHaveTextContent("Reference");
    expect(referenceButton).not.toHaveAttribute("title");
    expect(referenceButton).toHaveAttribute("data-state", "closed");
    expect(referenceButton.closest(".inventory-inbound-cost-control"))
      .toBe(cost.closest(".inventory-inbound-cost-control"));
    fireEvent.change(cost, { target: { value: "5.100000" } });
    fireEvent.change(within(row).getByLabelText("Quantity"), { target: { value: "2" } });
    expect(cost.value).toBe("5.100000");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0].items[0].unit_cost).toBe("5.100000");
  });

  it("keeps post actionable and guides the operator to the first missing required field", async () => {
    renderInbound([makeVariant(1, "Validation product", "NONE", "NONE")]);
    const row = (await screen.findByText("Validation product")).closest("tr")!;
    const submit = screen.getByRole("button", { name: "Post receipt" }) as HTMLButtonElement;
    const supplier = screen.getByRole("button", { name: "choose-supplier" });
    const reference = screen.getByLabelText("Invoice / reference number") as HTMLInputElement;
    const quantity = within(row).getByLabelText("Quantity") as HTMLInputElement;
    const cost = within(row).getByLabelText("Actual cost") as HTMLInputElement;
    await waitFor(() =>
      expect((within(row).getByLabelText("Purchase unit") as HTMLSelectElement).disabled).toBe(false)
    );

    expect(submit.disabled).toBe(false);
    expect(supplier).toHaveAttribute("aria-required", "true");
    expect(reference).toHaveAttribute("aria-required", "true");

    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(supplier));
    expect(supplier).toHaveAttribute("aria-invalid", "true");

    fireEvent.click(supplier);
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(reference));
    expect(reference).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(reference, { target: { value: "INV-VALIDATE-1" } });
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(quantity));
    expect(quantity).toHaveAttribute("aria-invalid", "true");

    fireEvent.change(quantity, { target: { value: "1" } });
    fireEvent.click(submit);
    await waitFor(() => expect(document.activeElement).toBe(cost));
    expect(cost).toHaveAttribute("aria-invalid", "true");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("keeps audit-lock UX informative but lets the backend own rejection", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.reference, "INV-AUDIT-LOCK");
    localStorage.setItem(
      keys.drafts,
      JSON.stringify({
        "1": [{
          row_id: "audit-lock-row",
          quantity: "2",
          uom_id: "1",
          unit_cost: "3.000000",
          batch_number: "",
          production_date: "",
          expiry_date: "",
        }],
      }),
    );
    renderInbound(
      [makeVariant(1, "Audit locked product", "NONE", "NONE")],
      null,
      costPolicy,
      [makeVariant(1, "Audit locked product", "NONE", "NONE")],
      null,
      true,
      "STK-LOCK-123",
    );
    const row = (await screen.findByText("Audit locked product")).closest("tr")!;
    await waitFor(() =>
      expect((within(row).getByLabelText("Purchase unit") as HTMLSelectElement).disabled).toBe(false)
    );
    const submit = screen.getByRole("button", { name: "Post receipt" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    expect(
      i18n.t("inventoryInbound.errors.auditLockTooltip", {
        reference: " (STK-LOCK-123)",
      }),
    ).toContain("STK-LOCK-123");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  });

  it("requires explicit selection when a receipt has two prices for the same product", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.reference, "INV-MIXED");
    localStorage.setItem(keys.drafts, JSON.stringify({
      "7": [
        {row_id:"lot-1", quantity:"2", uom_id:"1", unit_cost:"3.000000",
          batch_number:"LOT1", production_date:"", expiry_date:""},
        {row_id:"lot-2", quantity:"2", uom_id:"1", unit_cost:"4.000000",
          batch_number:"LOT2", production_date:"", expiry_date:""},
      ],
    }));
    renderInbound([makeVariant(7, "Mixed product", "OPTIONAL", "NONE")]);
    await screen.findAllByText("Mixed product");
    await waitFor(() => expect(
      (screen.getAllByLabelText("Purchase unit")[0] as HTMLSelectElement).disabled
    ).toBe(false));
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
    expect(mocks.post.mock.calls[0][0].items.map((item: {unit_cost:string}) => item.unit_cost))
      .toEqual(["3.000000", "4.000000"]);
  });

  it("keeps purchase cost directly editable for mouse-free entry", async () => {
    renderInbound([makeVariant(17, "Direct cost product", "NONE", "NONE")]);
    const row = (await screen.findByText("Direct cost product")).closest("tr")!;
    const input = within(row).getByLabelText("Actual cost") as HTMLInputElement;
    expect(input.disabled).toBe(false);
    expect(within(row).queryByRole("button", { name: "Edit actual purchase cost" })).toBeNull();
    input.focus();
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: "4.25" } });
    expect(input.value).toBe("4.25");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.disabled).toBe(false);
  });

  it("renders NONE / OPTIONAL / REQUIRED tracking fields directly", async () => {
    renderInbound([
      makeVariant(1, "None product", "NONE", "NONE"),
      makeVariant(2, "Optional product", "OPTIONAL", "OPTIONAL"),
      makeVariant(3, "Required product", "REQUIRED", "REQUIRED"),
      makeVariant(4, "Expiry only", "NONE", "OPTIONAL"),
      makeVariant(5, "Lot only", "OPTIONAL", "NONE"),
    ]);

    await screen.findByText("None product");
    const rows = [
      "None product",
      "Optional product",
      "Required product",
      "Expiry only",
      "Lot only",
    ].map((name) => screen.getByText(name).closest("tr")!);

    const [noneRow, optionalRow, requiredRow, expiryOnlyRow, lotOnlyRow] = rows;
    expect(within(noneRow).queryByLabelText("Lot / batch number")).toBeNull();
    expect(within(noneRow).queryByLabelText("Production date")).toBeNull();
    expect(within(noneRow).queryByLabelText("Expiry date")).toBeNull();
    expect(within(noneRow).getAllByText("—")).toHaveLength(3);

    const optionalLot = within(optionalRow).getByLabelText(
      "Lot / batch number",
    ) as HTMLInputElement;
    const optionalExpiry = within(optionalRow).getByLabelText(
      "Expiry date",
    ) as HTMLInputElement;
    expect(optionalLot.required).toBe(false);
    expect(optionalExpiry.required).toBe(false);
    expect(within(optionalRow).getByLabelText("Production date")).toBeTruthy();

    expect(
      (within(requiredRow).getByLabelText("Lot / batch number") as HTMLInputElement)
        .required,
    ).toBe(true);
    expect(
      (within(requiredRow).getByLabelText("Expiry date") as HTMLInputElement)
        .required,
    ).toBe(true);
    expect(within(requiredRow).getByLabelText("Production date")).toBeTruthy();

    expect(within(expiryOnlyRow).queryByLabelText("Lot / batch number")).toBeNull();
    expect(within(expiryOnlyRow).getByLabelText("Production date")).toBeTruthy();
    expect(within(expiryOnlyRow).getByLabelText("Expiry date")).toBeTruthy();

    expect(within(lotOnlyRow).getByLabelText("Lot / batch number")).toBeTruthy();
    expect(within(lotOnlyRow).getByLabelText("Production date")).toBeTruthy();
    expect(within(lotOnlyRow).queryByLabelText("Expiry date")).toBeNull();
  });

  it("supports fast typed dates and a native calendar picker in the same field", async () => {
    renderInbound([
      makeVariant(1, "Fast entry", "REQUIRED", "REQUIRED"),
      makeVariant(2, "Second row", "REQUIRED", "REQUIRED"),
    ]);

    const row = (await screen.findByText("Fast entry")).closest("tr")!;
    const secondRow = screen.getByText("Second row").closest("tr")!;
    const quantity = within(row).getByLabelText("Quantity") as HTMLInputElement;
    expect(quantity.value).toBe("");

    fireEvent.change(quantity, { target: { value: "05" } });
    expect(quantity.value).toBe("5");

    const production = within(row).getByLabelText("Production date") as HTMLInputElement;
    const expiry = within(row).getByLabelText("Expiry date") as HTMLInputElement;
    const expiryCalendar = within(row).getByLabelText(
      "Expiry date calendar",
    ) as HTMLInputElement;

    expect(production.type).toBe("text");
    expect(expiry.type).toBe("text");
    expect(expiryCalendar.type).toBe("date");
    expect(production.placeholder).toBe("25082026");
    expect(expiry.placeholder).toBe("25082026");
    expect(
      (within(secondRow).getByLabelText("Production date") as HTMLInputElement)
        .placeholder,
    ).toBe("");

    fireEvent.change(expiry, { target: { value: "25082026" } });
    fireEvent.blur(expiry);
    expect(expiry.value).toBe("2026-08-25");

    fireEvent.change(expiry, { target: { value: "01072026" } });
    fireEvent.blur(expiry);
    expect(expiry.value).toBe("2026-07-01");

    fireEvent.change(expiry, { target: { value: "20102026" } });
    fireEvent.blur(expiry);
    expect(expiry.value).toBe("2026-10-20");

    fireEvent.change(production, { target: { value: "25/08/2026" } });
    fireEvent.blur(production);
    expect(production.value).toBe("2026-08-25");

    fireEvent.change(production, { target: { value: "8122026" } });
    fireEvent.blur(production);
    expect(production.value).toBe("2026-12-08");

    fireEvent.change(production, { target: { value: "1122026" } });
    fireEvent.blur(production);
    expect(production.value).toBe("1122026");

    fireEvent.change(expiryCalendar, { target: { value: "2026-12-31" } });
    expect(expiry.value).toBe("2026-12-31");
  });

  it("numbers products and keeps costing setup out of the daily screen", async () => {
    renderInbound([
      makeVariant(1, "Number one", "NONE", "NONE"),
      makeVariant(2, "Number two", "NONE", "NONE"),
    ]);
    const firstRow = (await screen.findByText("Number one")).closest("tr")!;
    const secondRow = screen.getByText("Number two").closest("tr")!;
    expect(firstRow.cells[0]?.textContent?.trim()).toBe("1");
    expect(secondRow.cells[0]?.textContent?.trim()).toBe("2");
    expect(screen.queryByText("SKU-1")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: "Add another quantity/unit for this product",
      }),
    ).toBeNull();
    expect(screen.queryByLabelText("Costing method")).toBeNull();
  });

  it("opens one-time costing setup only when an unconfigured company tries to post", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(
      keys.drafts,
      JSON.stringify({
        "1": [
          {
            row_id: "first-cost-policy",
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
    localStorage.setItem(keys.reference, "INV-FIRST-COST");

    const unselectedPolicy: CostPolicy = {
      ...costPolicy,
      method: null,
      is_selected: false,
      selection_status: "UNSELECTED",
      selected_at: null,
      is_active: false,
      is_locked: false,
      locked_at: null,
      can_change: true,
    };
    const { fetch } = renderInbound(
      [makeVariant(1, "First costing receipt", "NONE", "NONE")],
      null,
      unselectedPolicy,
    );
    await screen.findByText("First costing receipt");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));

    expect(await screen.findByText("Inventory costing setup")).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Moving average/ }));
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(
          ([url, opts]) =>
            url === "/warehouse/costing-policy" && opts?.method === "PUT",
        ),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
  });

  it("opens opening valuation on the backend guard and preserves the receipt draft", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    const savedDraft = {
      "1": [
        {
          row_id: "opening-valuation-row",
          quantity: "2",
          uom_id: "1",
          unit_cost: "3.000000",
          batch_number: "",
          production_date: "",
          expiry_date: "",
        },
      ],
    };
    localStorage.setItem(keys.drafts, JSON.stringify(savedDraft));
    localStorage.setItem(keys.reference, "INV-OPENING");
    mocks.post.mockRejectedValueOnce(
      Object.assign(new Error("opening valuation required"), {
        code: "COST_OPENING_BALANCE_REQUIRED",
        status: 409,
      }),
    );

    renderInbound([
      makeVariant(1, "Existing stock product", "NONE", "NONE"),
    ]);
    await screen.findByText("Existing stock product");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));

    expect(
      await screen.findByText("Opening inventory valuation"),
    ).toBeTruthy();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(keys.reference)).toBe("INV-OPENING");
    expect(JSON.parse(localStorage.getItem(keys.drafts) ?? "{}")).toEqual(
      savedDraft,
    );
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

    const lot = (await screen.findByLabelText("Lot / batch number")) as HTMLInputElement;
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

  it("follows the visible column order with Enter for keyboard-first receiving", async () => {
    renderInbound([
      makeVariant(1, "Keyboard", "REQUIRED", "REQUIRED"),
      makeVariant(2, "Next product", "NONE", "NONE"),
    ]);
    const row = (await screen.findByText("Keyboard")).closest("tr")!;
    const nextRow = screen.getByText("Next product").closest("tr")!;
    const quantity = within(row).getByLabelText("Quantity") as HTMLElement;
    const unit = within(row).getByLabelText("Purchase unit") as HTMLElement;
    const cost = within(row).getByLabelText("Actual cost") as HTMLElement;
    const nextCost = within(nextRow).getByLabelText("Actual cost") as HTMLElement;

    fireEvent.change(quantity, { target: { value: "1" } });
    const lot = within(row).getByLabelText("Lot / batch number") as HTMLElement;
    const production = within(row).getByLabelText("Production date") as HTMLElement;
    const expiry = within(row).getByLabelText("Expiry date") as HTMLElement;

    cost.focus();
    fireEvent.keyDown(cost, { key: "ArrowRight" });
    expect(document.activeElement).toBe(quantity);
    fireEvent.keyDown(quantity, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(cost);
    fireEvent.keyDown(cost, { key: "ArrowDown" });
    expect(document.activeElement).toBe(nextCost);
    fireEvent.keyDown(nextCost, { key: "ArrowUp" });
    expect(document.activeElement).toBe(cost);

    fireEvent.keyDown(cost, { key: "Enter" });
    expect(document.activeElement).toBe(quantity);

    fireEvent.keyDown(quantity, { key: "Enter" });
    expect(document.activeElement).toBe(unit);

    fireEvent.keyDown(unit, { key: "Enter" });
    expect(document.activeElement).toBe(production);

    fireEvent.keyDown(production, { key: "Enter" });
    expect(document.activeElement).toBe(expiry);

    fireEvent.keyDown(expiry, { key: "Enter" });
    expect(document.activeElement).toBe(lot);

    fireEvent.keyDown(lot, { key: "Enter" });
    expect(document.activeElement).toBe(nextCost);
    expect(mocks.post).not.toHaveBeenCalled();
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

  it("keeps AR/EN direction and loads the next catalog page by scroll", async () => {
    const { container, fetch } = renderInbound(
      [makeVariant(1, "Locale", "REQUIRED", "OPTIONAL")],
      "next",
    );
    await screen.findByText("Locale");
    const root = container.querySelector(".inventory-inbound")!;
    const scroller = container.querySelector(
      ".inventory-inbound-table-wrap",
    ) as HTMLDivElement;
    expect(root.getAttribute("dir")).toBe("ltr");
    const localeRow = screen.getByText("Locale").closest("tr")!;
    expect(
      (within(localeRow).getByLabelText("Lot / batch number") as HTMLInputElement)
        .required,
    ).toBe(true);
    expect(
      screen.getByRole("columnheader", { name: "Lot / batch number" }),
    ).toBeTruthy();
    const headers = [...container.querySelectorAll(".inventory-inbound-table thead th")]
      .map((header) => header.textContent?.replace(/\s+/g, " ").trim());
    expect(headers).toEqual([
      "#",
      "Product",
      "Purchase cost*",
      "Quantity & purchase unit*",
      "Production date",
      "Expiry date",
      "Lot / batch number",
    ]);
    expect(localeRow.querySelectorAll(".inventory-inbound-required-marker")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();

    Object.defineProperties(scroller, {
      scrollTop: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 500 },
      scrollHeight: { configurable: true, value: 1300 },
    });
    fireEvent.scroll(scroller);
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([url]) =>
          String(url).includes("cursor=next"),
        ),
      ).toBe(true),
    );

    await act(async () => {
      await setAppLanguage("ar");
    });
    await waitFor(() => expect(root.getAttribute("dir")).toBe("rtl"));
    const rtlCost = within(localeRow).getByLabelText(i18n.t("inventoryInbound.unitCostPlaceholder"));
    const rtlQuantity = within(localeRow).getByLabelText(i18n.t("inventoryInbound.quantity"));
    (rtlCost as HTMLElement).focus();
    fireEvent.keyDown(rtlCost, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(rtlQuantity);
    expect(
      screen.getByRole("columnheader", {
        name: i18n.t("inventoryInbound.batchNumber"),
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: i18n.t("inventoryInbound.nextPage"),
      }),
    ).toBeNull();
  });

  it("keeps the initial catalog visible after the search debounce settles", async () => {
    renderInbound([
      makeVariant(1, "Stable catalog row", "NONE", "NONE"),
    ]);
    await screen.findByText("Stable catalog row");
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 360));
    });
    expect(screen.getByText("Stable catalog row")).toBeTruthy();
  });
  it("restores a filled receipt after leaving and returning to the tab", async () => {
    const products = [makeVariant(1, "Restorable product", "NONE", "NONE")];
    const first = renderInbound(products);
    const row = (await screen.findByText("Restorable product")).closest("tr")!;
    const quantity = within(row).getByLabelText("Quantity") as HTMLInputElement;
    const cost = row.querySelector(".inventory-inbound-cost-cell input") as HTMLInputElement;
    fireEvent.change(quantity, { target: { value: "3" } });
    fireEvent.change(cost, { target: { value: "4.500" } });
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    const keys = inboundStorageKeys(1, 2, 3);
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem(keys.drafts) ?? "{}")["1"][0]).toMatchObject({
        quantity: "3",
        unit_cost: "4.500",
      });
    });
    first.unmount();

    renderInbound(products);
    const restored = (await screen.findByText("Restorable product")).closest("tr")!;
    expect((within(restored).getByLabelText("Quantity") as HTMLInputElement).value).toBe("3");
    expect((restored.querySelector(".inventory-inbound-cost-cell input") as HTMLInputElement).value).toBe("4.500");
    expect(localStorage.getItem(`${keys.drafts}:supplier`)).toBe("55");
  });

  it("only explicit reset clears every part of the current draft, including supplier", async () => {
    renderInbound([makeVariant(1, "Clearable product", "NONE", "NONE")]);
    const row = (await screen.findByText("Clearable product")).closest("tr")!;
    fireEvent.change(within(row).getByLabelText("Quantity"), { target: { value: "5" } });
    fireEvent.change(row.querySelector(".inventory-inbound-cost-cell input")!, { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText(i18n.t("inventoryInbound.reference")), { target: { value: "REF-ABC" } });
    fireEvent.change(screen.getByLabelText(i18n.t("inventoryInbound.notes")), { target: { value: "draft notes" } });
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));

    const keys = inboundStorageKeys(1, 2, 3);
    await waitFor(() => expect(localStorage.getItem(`${keys.drafts}:supplier`)).toBe("55"));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryInbound.clearDraft") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("inventoryInbound.clearConfirm") }));

    await waitFor(() => expect(localStorage.getItem(`${keys.drafts}:supplier`)).toBeNull());
    expect((within(row).getByLabelText("Quantity") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(i18n.t("inventoryInbound.reference")) as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText(i18n.t("inventoryInbound.notes")) as HTMLInputElement).value).toBe("");
    expect(JSON.parse(localStorage.getItem(keys.drafts) ?? "{}")).toEqual({});
  });

  it("restores drafted products beyond the first catalog page and posts their original costs", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.drafts, JSON.stringify({
      "99": [{
        row_id: "draft-off-page",
        quantity: "7",
        uom_id: "1",
        unit_cost: "4.250000",
        batch_number: "",
        production_date: "",
        expiry_date: "",
      }],
    }));
    localStorage.setItem(keys.reference, "INV-OFF-PAGE");

    const firstPage = makeVariant(1, "First page product", "NONE", "NONE");
    const savedProduct = makeVariant(99, "Saved off-page product", "NONE", "NONE");
    const { fetch } = renderInbound([firstPage], null, costPolicy, [savedProduct]);

    const restoredRow = (await screen.findByText("Saved off-page product")).closest("tr")!;
    expect((within(restoredRow).getByLabelText("Quantity") as HTMLInputElement).value).toBe("7");
    expect((restoredRow.querySelector(".inventory-inbound-cost-cell input") as HTMLInputElement).value).toBe("4.250000");
    await waitFor(() => expect(
      fetch.mock.calls.some(([url, opts]) =>
        url === "/catalog/variants/resolve" &&
        (JSON.parse(String(opts?.body)).ids as number[]).includes(99)
      )
    ).toBe(true));
    await waitFor(() => expect(within(restoredRow).getByLabelText("Purchase unit")).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post.mock.calls[0][0].items).toMatchObject([
      { product_variant_id: 99, quantity: "7", unit_cost: "4.250000" },
    ]);
  });

  it("does not report a posted receipt if durable posting has not completed", async () => {
    const keys = inboundStorageKeys(1, 2, 3);
    localStorage.setItem(keys.drafts, JSON.stringify({
      "1": [{
        row_id: "pending-receipt",
        quantity: "2",
        uom_id: "1",
        unit_cost: "5",
        batch_number: "",
        production_date: "",
        expiry_date: "",
      }],
    }));
    localStorage.setItem(keys.reference, "INV-PENDING");
    mocks.post.mockResolvedValueOnce(false);
    renderInbound([makeVariant(1, "Pending product", "NONE", "NONE")]);
    await screen.findByText("Pending product");
    fireEvent.click(screen.getByRole("button", { name: "choose-supplier" }));
    fireEvent.click(screen.getByRole("button", { name: "Post receipt" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(JSON.parse(localStorage.getItem(keys.drafts) ?? "{}")["1"][0].quantity).toBe("2");
    expect(localStorage.getItem(keys.reference)).toBe("INV-PENDING");
  });

  it("keeps frozen inbound lot backend codes localized in AR + EN", () => {
    for (const language of ["ar", "en"] as const) {
      for (const code of [
        "INBOUND_LOT_REQUIRED",
        "INBOUND_LOT_NOT_ALLOWED",
        "INBOUND_LOT_RESERVED",
        "INBOUND_ANONYMOUS_BATCH_COLLISION",
        "INBOUND_WAREHOUSE_AUDIT_LOCKED",
      ]) {
        expect(i18n.exists(`errors.codes.${code}`, { lng: language })).toBe(true);
      }
    }
  });
});