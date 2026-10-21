import { createRef, useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { CreateProductPurchaseReferenceSection } from "@/pages/products/create/CreateProductPurchaseReferenceSection";
import { CreateProductCommerceSection } from "@/pages/products/create/CreateProductCommerceSection";
import { isPurchaseReferenceCreateInput, parsePurchaseReferenceCreateOptions } from "@/pages/products/create/purchaseReferenceCreateContract";
import { isProductCreateCommandPayload, productCreateRequestBody, productDraftFromCreateCommand,
  type ProductCreateCommandPayload } from "@/pages/products/create/productCreateCommand";
import { emptyDraft } from "@/pages/products/create/useCreateProductState";
import { useCreateProductMutation } from "@/pages/products/create/useCreateProductMutation";
import type { ProductDraft } from "@/pages/products/create/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));
const options = { can_manage: true, currency_code: "JOD",
  uoms: [{ id: 1, code: "EACH" }, { id: 2, code: "CARTON" }] };
const reference = { amount: "24.000000", purchase_uom_id: 2, currency_code: "JOD" };
const command: ProductCreateCommandPayload = {
  name: "New SKU", family_mode: "none", family_id: null, family_name: null, family_label: "",
  package_uom_code: "CARTON", units_per_package: 12, package_price: "60", unit_price: null,
  unit_barcode: null, package_barcode: null, lot_control_mode: "NONE", expiry_control_mode: "NONE",
};
const draft: ProductDraft = { ...emptyDraft, name: "New SKU", family_mode: "none",
  units_per_package: "12", package_price: "60", lot_control_mode: "NONE", expiry_control_mode: "NONE" };

beforeEach(async () => {
  localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  await i18n.changeLanguage("en");
});
afterEach(() => cleanup());

function Fields() {
  const [value, setValue] = useState(draft);
  return <>
    <CreateProductCommerceSection draft={value} createFieldError={null} packageUoms={options.uoms.slice(1)}
      packageUomsLoading={false} packageUomsError={false} draftDerived={null}
      createUnitsRef={createRef()} createPackagePriceRef={createRef()} createUnitPriceRef={createRef()}
      onHasPackageChange={vi.fn()} onRetryPackageUoms={vi.fn()} onPackageUomChange={vi.fn()}
      onUnitsPerPackageChange={vi.fn()} onPackagePriceChange={vi.fn()} onUnitPriceChange={vi.fn()} />
    <CreateProductPurchaseReferenceSection draft={value} options={options} saving={false} onRetry={vi.fn()}
      onChange={(next) => setValue((current) => ({ ...current, purchase_cost_reference: next }))} />
  </>;
}

function Mutation({ authFetch, value = { ...draft, purchase_cost_reference: reference } }: {
  authFetch: (path: string, opts?: RequestInit) => Promise<unknown>; value?: ProductDraft;
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={queryClient}><MutationBody authFetch={authFetch} value={value} client={queryClient} /></QueryClientProvider>;
}

function MutationBody({ authFetch, value, client }: {
  authFetch: (path: string, opts?: RequestInit) => Promise<unknown>; value: ProductDraft; client: QueryClient;
}) {
  const noop = vi.fn();
  const { submitCreate, createMutation } = useCreateProductMutation({
    draft: value, familyOptions: [], packageUoms: options.uoms.slice(1), authFetch,
    draftStorageKey: "product-create-draft", companyId: 7, driverId: 31,
    setDraft: noop, setCreateFieldError: noop, setCreateTrackingExpanded: noop,
    setCreateAdvancedExpanded: noop, setCreateOpen: noop, setCursor: noop, setHistory: noop,
    queryClient: client, t: i18n.t.bind(i18n),
    createNameRef: createRef(), createFamilyRef: createRef(), createUnitsRef: createRef(),
    createPackagePriceRef: createRef(), createUnitPriceRef: createRef(),
  });
  return <button type="button" disabled={createMutation.isPending} onClick={submitCreate}>
    {createMutation.isPending ? "waiting" : "submit"}
  </button>;
}

const response = { message: "Product created.", product_variant_id: 91, package_price: "60.000000",
  unit_price: "5.000000", lot_control_mode: "NONE", expiry_control_mode: "NONE" };

describe("Product quick-create optional purchase reference", () => {
  it("keeps old durable commands and no-reference request bodies unchanged", () => {
    expect(isProductCreateCommandPayload(command)).toBe(true);
    expect(productCreateRequestBody(command)).not.toHaveProperty("purchase_cost_reference");
    expect(productDraftFromCreateCommand(command)).not.toHaveProperty("purchase_cost_reference");
    const next = { ...command, purchase_cost_reference: reference };
    expect(isProductCreateCommandPayload(next)).toBe(true);
    expect(productCreateRequestBody(next).purchase_cost_reference).toEqual(reference);
    expect(productDraftFromCreateCommand(next).purchase_cost_reference).toEqual(reference);
    expect(productCreateRequestBody(next).package_price).toBe("60");
  });

  it("keeps purchase amount exact, including values beyond floating point money precision", () => {
    const precise = { ...reference, amount: "99999999999999.999999" };
    expect(isPurchaseReferenceCreateInput(precise)).toBe(true);
    expect(productCreateRequestBody({ ...command, purchase_cost_reference: precise }).purchase_cost_reference?.amount)
      .toBe("99999999999999.999999");
    for (const amount of [24, "-1", "NaN", "1.0000001", "100000000000000"]) {
      expect(isPurchaseReferenceCreateInput({ ...reference, amount })).toBe(false);
    }
    expect(isProductCreateCommandPayload({ ...command, purchase_cost_reference: null })).toBe(false);
    expect(() => parsePurchaseReferenceCreateOptions({ ...options, currency_code: null })).toThrow();
  });

  it("labels purchase cost separately and never changes unit or package sale prices", () => {
    render(<Fields />);
    expect(screen.queryByLabelText("Purchase reference amount")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Add a purchase-cost reference (optional)"));
    fireEvent.change(screen.getByLabelText("Purchase reference amount"), { target: { value: "24.123456" } });
    fireEvent.change(screen.getByLabelText("Purchase unit"), { target: { value: "2" } });
    expect(screen.getByLabelText("Purchase reference amount")).toHaveValue("24.123456");
    expect(screen.getByText("Company currency: JOD")).toBeInTheDocument();
    expect(screen.getByDisplayValue("60")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Add a purchase-cost reference (optional)"));
    expect(screen.queryByLabelText("Purchase reference amount")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("60")).toBeInTheDocument();
  });

  it("hides the optional entry without cost MANAGE and preserves a draft when options fail", () => {
    const { rerender } = render(<CreateProductPurchaseReferenceSection draft={draft}
      options={{ can_manage: false, currency_code: null, uoms: [] }} saving={false}
      onRetry={vi.fn()} onChange={vi.fn()} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    const retry = vi.fn();
    rerender(<CreateProductPurchaseReferenceSection draft={{ ...draft, purchase_cost_reference: reference }}
      failed saving={false} onRetry={retry} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Purchase reference amount")).toHaveValue("24.000000");
    fireEvent.click(screen.getByText("Retry purchase reference options"));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("uses locale-driven Arabic copy and direction", async () => {
    await act(() => i18n.changeLanguage("ar"));
    render(<CreateProductPurchaseReferenceSection draft={draft} options={options} saving={false}
      onRetry={vi.fn()} onChange={vi.fn()} />);
    expect(screen.getByLabelText("إضافة تكلفة شراء مرجعية (اختياري)").closest("section")).toHaveAttribute("dir", "rtl");
  });

  it("posts Product and reference together once with no follow-up HTTP mutation", async () => {
    const fetch = vi.fn().mockResolvedValue(response);
    render(<Mutation authFetch={fetch} />);
    fireEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(fetch.mock.calls[0][0]).toBe("/simple-products");
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.purchase_cost_reference).toEqual(reference);
    expect(body.package_price).toBe("60");
    await waitFor(() => expect(screen.getByRole("button", { name: "submit" })).not.toBeDisabled());
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("preserves request identity and full reference payload across timeout and retry", async () => {
    const fetch = vi.fn().mockRejectedValueOnce(Object.assign(new Error(), { code: "REQUEST_TIMEOUT", status: 408 }))
      .mockResolvedValueOnce(response);
    render(<Mutation authFetch={fetch} />);
    fireEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "submit" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const bodies = fetch.mock.calls.map((call) => JSON.parse(call[1].body));
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[0].purchase_cost_reference).toEqual(reference);
  });

  it("sends the legacy command without a reference when optional entry is omitted", async () => {
    const fetch = vi.fn().mockResolvedValue(response);
    render(<Mutation authFetch={fetch} value={draft} />);
    fireEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(fetch.mock.calls[0][1].body)).not.toHaveProperty("purchase_cost_reference");
  });
});
