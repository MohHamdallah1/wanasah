import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeCountingPanel } from "./StocktakeCountingPanel";
import { StocktakeReviewPanel } from "./StocktakeReviewPanel";
import { StocktakeIndependentWait } from "./StocktakeIndependentWait";
import type { StocktakeRow } from "../inventoryUtils";
import type { StocktakeReview, StocktakeType } from "./types";

const locale = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return {
    ...actual,
    useTranslation: () => ({
      i18n: {
        language: locale.value,
        resolvedLanguage: locale.value,
        dir: () => locale.value === "ar" ? "rtl" : "ltr",
      },
      t: (key: string) => key,
    }),
  };
});

const countRow = (id: number, status: StocktakeRow["stock_status"], counted = false): StocktakeRow => ({
  row_key: `118:${id}:${status}`,
  product_variant_id: 118, batch_id: id, stock_status: status,
  product_name: "Chickpeas 750 g", batch_number: `REAL-LOT-${id}`,
  expiry_date: "2027-04-12",
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1",
  actual_quantity: counted ? "2" : "", counted,
});

function counting(options: { product?: string; rows?: StocktakeRow[]; progress?: { total: number; counted: number; remaining: number } } = {}) {
  const callbacks = {
    update: vi.fn(), zero: vi.fn(), discovered: vi.fn(), remove: vi.fn(),
    cancel: vi.fn(), submit: vi.fn(),
  };
  const rows = options.rows ?? [countRow(51, "AVAILABLE"), countRow(52, "BLOCKED")];
  const view = render(
    <StocktakeCountingPanel warehouseName="Main Warehouse" scopeProductName={options.product}
      rows={rows} progress={options.progress ?? { total: rows.length, counted: 0, remaining: rows.length }}
      onUpdateRow={callbacks.update} onConfirmZero={callbacks.zero}
      onAddDiscovered={callbacks.discovered} onRemoveDiscovered={callbacks.remove}
      canCancel onCancel={callbacks.cancel} onSubmit={callbacks.submit} />,
  );
  return { ...view, callbacks };
}

function reviewFixture(type: StocktakeType): StocktakeReview {
  return {
    session_id: 70, reference_number: "ST-2026-70", stocktake_type: type,
    status: "PENDING_REVIEW", location_id: 11, independent_recount_satisfied: false,
    latest_attempt: {
      id: 77, attempt_number: 1, counted_by: 9, counted_by_name: "Counter A",
      authorized_by: null, authorized_by_name: null, recount_reason: null,
      requires_independent_recount: false, submitted_at: "2026-11-05T08:10:00Z",
    },
    attempt_history: [{
      id: 77, attempt_number: 1, counted_by: 9, counted_by_name: "Counter A",
      authorized_by: null, authorized_by_name: null, recount_reason: null,
      requires_independent_recount: false, submitted_at: "2026-11-05T08:10:00Z",
    }],
    lines: [
      {
        attempt_line_id: 1, product_variant_id: 118, batch_id: 51,
        stock_status: "AVAILABLE", line_origin: "SNAPSHOT", product_name: "Chickpeas 750 g",
        base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
        quantity_scale: 0, quantity_step: "1", batch_number: "REAL-LOT-51",
        expiry_date: "2027-04-12", expected_quantity: "4",
        actual_quantity: "2", variance_quantity: "-2",
      },
      {
        attempt_line_id: 2, product_variant_id: 118, batch_id: 52,
        stock_status: "BLOCKED", line_origin: "DISCOVERED", product_name: "Chickpeas 750 g",
        base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
        quantity_scale: 0, quantity_step: "1", batch_number: "REAL-LOT-52",
        expiry_date: "2027-04-12", expected_quantity: "0",
        actual_quantity: "1", variance_quantity: "1",
      },
    ],
  };
}

function review(type: StocktakeType, blocked = false) {
  const callbacks = { variance: vi.fn(), cancel: vi.fn(), recount: vi.fn(), approve: vi.fn() };
  const view = render(
    <StocktakeReviewPanel warehouseName="Main Warehouse"
      scopeProductName={type === "CYCLE_COUNT" ? "Chickpeas 750 g" : null}
      review={reviewFixture(type)}
      totals={{ total: 2, matched: 0, shortage: 1, overage: 1, varianceItems: 2 }}
      approvalBlocked={blocked} onVariance={callbacks.variance}
      canCancel onCancel={callbacks.cancel} canRecount onRecount={callbacks.recount}
      canApprove onApprove={callbacks.approve} />,
  );
  return { ...view, callbacks };
}

beforeEach(() => { locale.value = "ar"; });

describe("Stocktake single count/review workspace V1", () => {
  it.each([
    ["ar", undefined, "جرد شامل", "العد", "جدول العد الفعلي"],
    ["ar", "Chickpeas 750 g", "جرد صنف", "العد", "جدول العد الفعلي"],
    ["en", undefined, "Full count", "Count", "Physical count table"],
    ["en", "Chickpeas 750 g", "Product count", "Count", "Physical count table"],
  ] as const)("uses ONE shared counting surface for %s with product scope %s", (language, product, type, step, table) => {
    locale.value = language;
    const { container, callbacks } = counting({ product });
    expect(screen.getByText(type)).toBeInTheDocument();
    expect(screen.getByText("Main Warehouse")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: table })).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    const stages = screen.getByRole("list", { name: language === "ar" ? "مراحل الجرد" : "Stocktake stages" });
    expect(stages.querySelectorAll('li[aria-current="step"]')).toHaveLength(1);
    expect(stages.querySelector('li[aria-current="step"]')).toHaveTextContent(step);
    const mobile = container.querySelectorAll(".md\\:hidden article");
    expect(mobile).toHaveLength(2);
    expect(mobile[0]).toHaveTextContent("REAL-LOT-51");
    expect(mobile[1]).toHaveTextContent("REAL-LOT-52");
    expect(screen.getAllByText(language === "ar" ? "محظور" : "Blocked").length).toBeGreaterThan(0);
    // Before submitting, the UI has no expected stock or variance columns.
    expect(screen.queryByText(language === "ar" ? "المتوقع" : "Expected")).not.toBeInTheDocument();
    expect(screen.queryByText(language === "ar" ? "الفرق" : "Variance")).not.toBeInTheDocument();
    const firstInput = mobile[0].querySelector<HTMLInputElement>("input[data-stocktake-count-input]");
    expect(firstInput?.getAttribute("aria-label")).toContain("REAL-LOT-51");
    fireEvent.change(firstInput!, { target: { value: "3" } });
    expect(callbacks.update).toHaveBeenCalledWith("118:51:AVAILABLE", "3");
    expect(callbacks.submit).not.toHaveBeenCalled();
  });

  it.each(["ar", "en"] as const)("keeps zero-stock recovery, disabled empty submit and cancel in %s", (language) => {
    locale.value = language;
    const { callbacks } = counting({ product: "Missing item", rows: [], progress: { total: 0, counted: 0, remaining: 0 } });
    const hint = screen.getByRole("status");
    expect(hint).toHaveTextContent(language === "ar" ? "لا توجد كميات مسجلة" : "no recorded stock");
    fireEvent.click(within(hint).getByRole("button"));
    expect(callbacks.discovered).toHaveBeenCalledOnce();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    const finish = screen.getByRole("button", { name: language === "ar" ? "إنهاء العد وتثبيت المحاولة" : "Finish count and submit attempt" });
    expect(finish).toBeDisabled();
    fireEvent.click(finish);
    expect(callbacks.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: language === "ar" ? "إلغاء الجرد" : "Cancel stocktake" }));
    expect(callbacks.cancel).toHaveBeenCalledOnce();
  });

  it.each([
    ["ar", "FULL_COUNT", "جرد شامل", "المراجعة", "جدول مراجعة الجرد"],
    ["ar", "CYCLE_COUNT", "جرد صنف", "المراجعة", "جدول مراجعة الجرد"],
    ["en", "FULL_COUNT", "Full count", "Review", "Count review table"],
    ["en", "CYCLE_COUNT", "Product count", "Review", "Count review table"],
  ] as const)("shows post-submission quantities and correct phase in %s %s", (language, type, label, step, table) => {
    locale.value = language;
    const { container, callbacks } = review(type);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("ST-2026-70")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: table })).toBeInTheDocument();
    const stages = screen.getByRole("list", { name: language === "ar" ? "مراحل الجرد" : "Stocktake stages" });
    expect(stages.querySelector('li[aria-current="step"]')).toHaveTextContent(step);
    expect(container.querySelectorAll(".md\\:hidden article")).toHaveLength(2);
    expect(container).toHaveTextContent("REAL-LOT-51");
    expect(container).toHaveTextContent("REAL-LOT-52");
    expect(container).toHaveTextContent(language === "ar" ? "بضاعة مكتشفة أثناء الجرد" : "Discovered during count");
    expect(screen.getByRole("button", { name: language === "ar" ? "اعتماد نهائي" : "Final approval" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: language === "ar" ? "إعادة عد" : "Recount" }));
    expect(callbacks.recount).toHaveBeenCalledOnce();
    expect(callbacks.approve).not.toHaveBeenCalled();
  });

  it.each(["ar", "en"] as const)("blocks approval until independent recount, without changing button authority in %s", (language) => {
    locale.value = language;
    const { callbacks } = review("FULL_COUNT", true);
    const approve = screen.getByRole("button", { name: language === "ar" ? "اعتماد نهائي" : "Final approval" });
    expect(approve).toBeDisabled();
    fireEvent.click(approve);
    expect(callbacks.approve).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(language === "ar" ? "إعادة عد مستقلة" : "independent recount");
  });

  it.each(["ar", "en"] as const)("keeps independent wait compact, plain-language and cancel authorization in %s", language => {
    locale.value = language;
    const cancel = vi.fn();
    const view = render(<StocktakeIndependentWait canCancel={false} onCancel={cancel} />);
    expect(screen.getByRole("list", { name: language === "ar" ? "مراحل الجرد" : "Stocktake stages" })).toBeInTheDocument();
    expect(view.container.textContent).not.toMatch(/Snapshot|عد أعمى|blind count/i);
    const button = screen.getByRole("button", { name: language === "ar" ? "إلغاء جلسة الجرد" : "Cancel stocktake session" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(cancel).not.toHaveBeenCalled();
  });
});
