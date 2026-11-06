import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StocktakeReviewPanel } from "./StocktakeReviewPanel";
import { parseStocktakeReview } from "./parsers";

const language = vi.hoisted(() => ({ value: "ar" }));
vi.mock("react-i18next", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-i18next")>();
  return {
    ...original,
    useTranslation: () => ({
      i18n: {
        language: language.value,
        resolvedLanguage: language.value,
        dir: () => language.value === "ar" ? "rtl" : "ltr",
      },
      t: (key: string) => key,
    }),
  };
});

const attempt1 = {
  id: 91, attempt_number: 1, counted_by: 17,
  counted_by_name: "Original counter",
  authorized_by: null, authorized_by_name: null,
  recount_of_attempt_id: null, recount_reason: null,
  requires_independent_recount: true,
  submitted_at: "2026-11-04T09:00:00Z",
};
const attempt2 = {
  id: 92, attempt_number: 2, counted_by: 18,
  counted_by_name: "Independent counter",
  authorized_by: 30, authorized_by_name: "Recount supervisor",
  recount_of_attempt_id: 91,
  recount_reason: "Shelf discrepancy confirmed on recount",
  requires_independent_recount: false,
  submitted_at: "2026-11-04T11:15:00+03:00",
};
const line = (id: number, origin: "SNAPSHOT" | "DISCOVERED", expiry: string | null) => ({
  attempt_line_id: id, product_variant_id: id + 200, batch_id: id + 300,
  stock_status: "QUARANTINED", line_origin: origin,
  product_name: "Evidence product " + id,
  base_uom_id: 7, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1",
  batch_number: "LOT-REVIEW-" + id, expiry_date: expiry,
  expected_quantity: origin === "DISCOVERED" ? "0" : "10",
  actual_quantity: "5",
  variance_quantity: origin === "DISCOVERED" ? "5" : "-5",
  notes: null,
});
const rawReview = {
  session_id: 77, reference_number: "STK-000077",
  stocktake_type: "FULL_COUNT", status: "PENDING_REVIEW",
  location_id: 11, independent_recount_satisfied: true,
  latest_attempt: attempt2,
  attempt_history: [attempt1, attempt2],
  // Backend returns latest attempt lines only; no previous attempt line history.
  lines: [line(101, "SNAPSHOT", "2027-03-16"), line(102, "DISCOVERED", null)],
};

beforeEach(() => { language.value = "ar"; });

describe("Stocktake V1 #779 canonical Review evidence parity", () => {
  it.each([
    ["ar", "rtl", "الصلاحية", "بضاعة مكتشفة أثناء الجرد", "سجل محاولات العد"],
    ["en", "ltr", "Expiry", "Discovered during count", "Count attempt history"],
  ] as const)("renders exact backend review fields in %s and preserves approval authority", (locale, dir, expiry, discovered, historyTitle) => {
    language.value = locale;
    const review = parseStocktakeReview(rawReview);
    const approve = vi.fn();
    const { container } = render(<StocktakeReviewPanel
      review={review}
      totals={{ total: 2, matched: 0, shortage: 1, overage: 1, varianceItems: 2 }}
      approvalBlocked={true}
      canCancel={false} onCancel={vi.fn()}
      canRecount={true} onRecount={vi.fn()}
      canApprove={true} onApprove={approve} onVariance={vi.fn()}
    />);
    expect(container.firstElementChild).toHaveAttribute("dir", dir);

    // Both responsive renderers show canonical Batch expiry and discovered origin.
    const mobile = container.querySelector(".md\\:hidden");
    const desktop = container.querySelector("table");
    expect(mobile).not.toBeNull();
    expect(desktop).not.toBeNull();
    for (const surface of [mobile!, desktop!]) {
      expect(within(surface as HTMLElement).getByText("LOT-REVIEW-101")).toBeInTheDocument();
      expect(within(surface as HTMLElement).getByText("2027-03-16")).toBeInTheDocument();
      expect(within(surface as HTMLElement).getAllByText(new RegExp(expiry)).length).toBeGreaterThan(0);
      expect(within(surface as HTMLElement).getByText(discovered)).toBeInTheDocument();
      expect(within(surface as HTMLElement).getByText("LOT-REVIEW-102")).toBeInTheDocument();
      expect(within(surface as HTMLElement).getByText("—")).toBeInTheDocument();
      // Existing review remains the latest attempt; never synthesize historical count lines.
      expect(within(surface as HTMLElement).getAllByText(/Evidence product/)).toHaveLength(2);
    }

    const disclosure = container.querySelector("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(disclosure!.querySelector("summary")!);
    expect(disclosure).toHaveAttribute("open");
    const history = screen.getByRole("list", { name: historyTitle });
    const historicalAttempts = within(history).getAllByRole("listitem");
    expect(historicalAttempts).toHaveLength(2);
    expect(within(historicalAttempts[0]).getByText(/Original counter/)).toBeInTheDocument();
    expect(within(historicalAttempts[1]).getByText(/Independent counter/)).toBeInTheDocument();
    expect(within(historicalAttempts[1]).getByText(/Recount supervisor/)).toBeInTheDocument();
    expect(within(historicalAttempts[1]).getByText(/Shelf discrepancy confirmed on recount/)).toBeInTheDocument();
    expect(history.querySelectorAll("time")).toHaveLength(2);
    expect(history.querySelectorAll("time")[0]).toHaveAttribute("dateTime", attempt1.submitted_at);
    expect(history.querySelectorAll("time")[1]).toHaveAttribute("dateTime", attempt2.submitted_at);
    // Deliberate lack of authorized_by/recount_reason in first attempt stays absent.
    expect(within(historicalAttempts[0]).queryByText(/Recount supervisor/)).not.toBeInTheDocument();

    const approval = screen.getByRole("button", { name: locale === "ar" ? "اعتماد نهائي" : "Final approval" });
    expect(approval).toBeDisabled();
    fireEvent.click(approval);
    expect(approve).not.toHaveBeenCalled();
  });

  it("does not imply previous attempts had count lines, and nullable evidence remains truthful", () => {
    language.value = "en";
    const review = parseStocktakeReview({
      ...rawReview,
      attempt_history: [attempt1], latest_attempt: attempt1,
      lines: [line(103, "SNAPSHOT", null)],
    });
    const { container } = render(<StocktakeReviewPanel
      review={review} totals={{ total: 1, matched: 0, shortage: 1, overage: 0, varianceItems: 1 }}
      approvalBlocked={true} canCancel={false} onCancel={vi.fn()}
      canRecount={false} onRecount={vi.fn()} canApprove={false} onApprove={vi.fn()} onVariance={vi.fn()}
    />);
    expect(screen.getAllByText(/Evidence product/)).toHaveLength(2); // mobile and desktop copies
    const disclosure = container.querySelector("details");
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(disclosure!.querySelector("summary")!);
    expect(disclosure).toHaveAttribute("open");
    expect(screen.queryByText("Independent counter")).not.toBeInTheDocument();
    expect(screen.queryByText(/Shelf discrepancy confirmed/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("time")).toHaveLength(1);
  });

  it.each([
    ["ar", "rtl"],
    ["en", "ltr"],
  ] as const)("keeps numeric amount/sign before Arabic base unit in %s on mobile and desktop", (locale, direction) => {
    language.value = locale;
    const entry = {
      ...line(104, "SNAPSHOT", null),
      base_uom_name: "حبة",
      expected_quantity: "20",
      actual_quantity: "18",
      variance_quantity: "-2",
    };
    const review = parseStocktakeReview({
      ...rawReview, lines: [entry],
    });
    const { container } = render(<StocktakeReviewPanel
      review={review}
      totals={{ total: 1, matched: 0, shortage: 1, overage: 0, varianceItems: 1 }}
      approvalBlocked={true}
      canCancel={false} onCancel={vi.fn()}
      canRecount={true} onRecount={vi.fn()}
      canApprove={false} onApprove={vi.fn()} onVariance={vi.fn()}
    />);
    for (const surface of [
      container.querySelector(".md\\:hidden"),
      container.querySelector("table"),
    ]) {
      expect(surface).not.toBeNull();
      const display = Array.from(surface!.querySelectorAll('[data-stocktake-review-quantity="true"]'));
      expect(display).toHaveLength(3);
      for (const [index, number] of ["20", "18", "-2"].entries()) {
        const amount = display[index];
        expect(amount).toHaveAttribute("dir", direction);
        expect(amount).toHaveAttribute("aria-label", `${number} حبة`);
        expect(amount.querySelector('bdi[dir="ltr"]')).toHaveTextContent(number);
        expect(amount.querySelector('bdi[dir="auto"]')).toHaveTextContent("حبة");
      }
    }
  });

});
