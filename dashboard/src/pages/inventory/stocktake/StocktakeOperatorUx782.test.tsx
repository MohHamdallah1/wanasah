import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeCycleStartModal } from "./StocktakeCycleStartModal";
import { StocktakeCountingPanel } from "./StocktakeCountingPanel";
import type { CycleCountStartController } from "./hooks/useCycleCountStart";
import type { StocktakeRow } from "../inventoryUtils";

const locale = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      i18n: {
        language: locale.value, resolvedLanguage: locale.value,
        dir: () => locale.value === "ar" ? "rtl" : "ltr",
      },
      t: (key: string) => key,
    }),
  };
});
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, title, children, footer }: {
    isOpen: boolean; title: string; children: React.ReactNode; footer: React.ReactNode;
  }) => isOpen ? <div role="dialog" aria-label={title}>{children}{footer}</div> : null,
}));

const product = {
  id: 118, name: "Chickpeas 750 g", sku: "CH-750",
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1",
};
const batch = {
  id: 51, product_variant_id: 118, batch_number: "TRUE-LOT-51",
  production_date: "2026-01-01", expiry_date: "2027-04-12", is_active: true,
};
function controller(selected: typeof product | null = null): CycleCountStartController {
  return {
    locationId: 11, productSource: "warehouse", selectProductSource: vi.fn(),
    productSearchInput: "", setProductSearchInput: vi.fn(),
    products: [product], productsNextCursor: null,
    productsLoading: false, productsLoadingMore: false,
    selectedProduct: selected, chooseProduct: vi.fn(), clearProduct: vi.fn(),
    loadMoreProducts: vi.fn(),
    batchSearchInput: "", setBatchSearchInput: vi.fn(),
    batches: [batch], batchesNextCursor: null,
    batchesLoading: false, batchesLoadingMore: false,
    selectedBatch: null, setSelectedBatch: vi.fn(), loadMoreBatches: vi.fn(),
    notes: "", setNotes: vi.fn(), starting: false,
    startCycleCount: vi.fn(async () => true), resetForm: vi.fn(),
  };
}
const row = (id: number, status: StocktakeRow["stock_status"]): StocktakeRow => ({
  row_key: "118:" + id + ":" + status, product_variant_id: 118, batch_id: id,
  stock_status: status, product_name: "Chickpeas 750 g",
  batch_number: "TRUE-LOT-" + id, expiry_date: "2027-04-12",
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1",
  actual_quantity: "0", counted: false,
});

beforeEach(() => { locale.value = "ar"; });

describe("Stocktake V1 #782 operator product count UX", () => {
  it.each([
    ["ar", "جرد صنف", "أصناف موجودة بالمستودع", "بحث في جميع أصناف الشركة", "بدء العد"],
    ["en", "Product count", "Products on hand here", "Search entire company catalog", "Start count"],
  ] as const)("offers explicit on-hand default and company-wide mode in %s without starting automatically", (language, title, warehouse, catalog, start) => {
    locale.value = language;
    const c = controller();
    const onStart = vi.fn();
    render(<StocktakeCycleStartModal open controller={c} onClose={vi.fn()} onStart={onStart} />);
    const dialog = screen.getByRole("dialog", { name: title });
    expect(within(dialog).getByRole("button", { name: warehouse })).toHaveAttribute("aria-pressed", "true");
    expect(within(dialog).getByRole("button", { name: catalog })).toHaveAttribute("aria-pressed", "false");
    expect(within(dialog).getByText("Chickpeas 750 g")).toBeInTheDocument();
    expect(within(dialog).getByText(/#11/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: start })).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: catalog }));
    expect(c.selectProductSource).toHaveBeenCalledWith("catalog");
    expect(onStart).not.toHaveBeenCalled();
  });

  it.each([
    ["ar", "خيار متقدم: جرد تشغيلة واحدة", "بدء العد"],
    ["en", "Advanced: count one batch only", "Start count"],
  ] as const)("defaults selected product to all batches with optional genuine single-batch disclosure %s", (language, advanced, start) => {
    locale.value = language;
    const c = controller(product);
    const onStart = vi.fn();
    const { container } = render(<StocktakeCycleStartModal open controller={c} onClose={vi.fn()} onStart={onStart} />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText(new RegExp(advanced))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: start })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: start }));
    expect(onStart).toHaveBeenCalledOnce();
    fireEvent.click(details!.querySelector("summary")!);
    expect(details).toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: /TRUE-LOT-51/ }));
    expect(c.setSelectedBatch).toHaveBeenCalledWith(batch);
    expect(c.selectedBatch).toBeNull(); // React state authority remains in controller, default is all.
  });

  it.each([
    ["ar", "لا توجد كميات مسجلة", "إنهاء العد وتثبيت المحاولة"],
    ["en", "no recorded stock", "Finish count and submit attempt"],
  ] as const)("explains zero snapshot and provides registered Lot recovery without phantom submission %s", (language, hint, finish) => {
    locale.value = language;
    const discovered = vi.fn(), submit = vi.fn(), cancel = vi.fn();
    render(<StocktakeCountingPanel warehouseId={11} scopeProductName="No-stock product"
      rows={[]} progress={{ total: 0, counted: 0, remaining: 0 }}
      onUpdateRow={vi.fn()} onConfirmZero={vi.fn()} onAddDiscovered={discovered}
      onRemoveDiscovered={vi.fn()} canCancel onCancel={cancel} onSubmit={submit} />);
    const alert = screen.getByRole("status");
    expect(within(alert).getByText(new RegExp(hint, "i"))).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole("button"));
    expect(discovered).toHaveBeenCalledOnce();
    const finishButton = screen.getByRole("button", { name: finish });
    expect(finishButton).toBeDisabled();
    fireEvent.click(finishButton);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: language === "ar" ? "إلغاء الجرد" : "Cancel stocktake" }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(document.body).toHaveTextContent("No-stock product");
  });

  it.each([
    ["ar", "العد جارٍ"], ["en", "Count in progress"],
  ] as const)("keeps separate batch/status counts and protects expected quantities in %s", (language, label) => {
    locale.value = language;
    const first = row(51, "AVAILABLE"), second = row(52, "QUARANTINED");
    const { container } = render(<StocktakeCountingPanel warehouseId={11} scopeProductName="Chickpeas 750 g"
      rows={[first, second]} progress={{ total: 2, counted: 0, remaining: 2 }}
      onUpdateRow={vi.fn()} onConfirmZero={vi.fn()} onAddDiscovered={vi.fn()}
      onRemoveDiscovered={vi.fn()} canCancel onCancel={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText("20")).not.toBeInTheDocument(); // No expected quantity shown.
    const mobileInputs = container.querySelectorAll(".md\\:hidden input[data-stocktake-count-input='true']");
    expect(mobileInputs).toHaveLength(2);
    expect(mobileInputs[0].getAttribute("aria-label")).toContain("TRUE-LOT-51");
    expect(mobileInputs[1].getAttribute("aria-label")).toContain("TRUE-LOT-52");
    expect(screen.getByRole("button", { name: language === "ar" ? "إنهاء العد وتثبيت المحاولة" : "Finish count and submit attempt" })).toBeDisabled();
  });
});
