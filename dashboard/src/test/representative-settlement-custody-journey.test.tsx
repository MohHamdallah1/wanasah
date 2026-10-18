import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { RepresentativeCustodyModal } from "@/features/operations/representativeSettlement/RepresentativeCustodyModal";
import { representativeSettlementCopy } from "@/features/operations/representativeSettlement/copy";

const lineKey = "abcdefghijklmnopqrstuvwx";
const custody = {
  work_session_id: 80, vehicle_location_id: 70, inventory_reconciled: false, custody_received: false,
  review_required: false, reconciliation_reference: null,
  lines: [{ line_key: lineKey, product_name: "Sample Product", sku: "SKU-1", batch_number: "LOT-7", expiry_date: "2027-03-01", stock_status: "DAMAGED", uom: "PCS", expected_quantity: "10" }],
};
const reconciledCustody = { ...custody, inventory_reconciled: true, lines: [{ ...custody.lines[0], expected_quantity: "8" }] };
const firstReview = {
  status: "REVIEW_REQUIRED", reconciliation_reference: "VREC-HIDDEN", independent_recount_satisfied: false,
  requires_independent_recount: true, attempt_number: 1,
  lines: [{ product_name: "Sample Product", batch_number: "LOT-7", stock_status: "DAMAGED", uom: "PCS", expected_quantity: "10", actual_quantity: "8", variance_quantity: "-2", expiry_date: "2027-03-01" }],
};
const secondReview = { ...firstReview, independent_recount_satisfied: true, attempt_number: 2 };
const countSheet = {
  status: "RECOUNT_REQUIRED", reconciliation_reference: "VREC-HIDDEN",
  lines: [{ line_key: lineKey, product_name: "Sample Product", stock_status: "DAMAGED", batch_number: "LOT-7", expiry_date: "2027-03-01", uom: "PCS" }],
};

function apiMock() {
  let custodyReads = 0;
  let receivePosts = 0;
  let varianceReads = 0;
  let recountAuthorized = false;
  return vi.fn(async (path: string, options: RequestInit = {}) => {
    const method = options.method || "GET";
    if (path.startsWith("/warehouse/locations?")) return { items: [{ id: 91, name: "Main Warehouse", code: "WH-1" }], next_cursor: null, has_more: false, total: 1 };
    if (path === "/inventory/access/locations/capabilities" && method === "POST") return { locations: { "91": ["transfer.destination"] } };
    if (path === "/admin/sessions/80/inventory-custody" && method === "GET") { custodyReads += 1; return custodyReads === 1 ? custody : reconciledCustody; }
    if (path === "/admin/sessions/80/inventory-custody/receive" && method === "POST") {
      receivePosts += 1;
      return receivePosts === 1
        ? { status: "REVIEW_REQUIRED", review_required: true, reconciliation_reference: "VREC-HIDDEN", requires_independent_recount: true, movement_count: 0 }
        : { status: "CUSTODY_RECEIVED", review_required: false, inventory_reconciled: true, movement_count: 1, financial_ready: true };
    }
    if (path === "/admin/sessions/80/inventory-custody/variance" && method === "GET") { varianceReads += 1; return varianceReads === 1 ? firstReview : secondReview; }
    if (path === "/admin/sessions/80/inventory-custody/variance/count-sheet" && method === "GET") {
      if (!recountAuthorized) throw Object.assign(new Error("not ready"), { status: 409, code: "RECOUNT_NOT_AUTHORIZED" });
      return countSheet;
    }
    if (path === "/admin/sessions/80/inventory-custody/variance/recount" && method === "POST") { recountAuthorized = true; return { status: "RECOUNT_REQUIRED", recount_authorized: true }; }
    if (path === "/admin/sessions/80/inventory-custody/variance/count" && method === "POST") return { status: "REVIEW_REQUIRED", attempt_number: 2, requires_independent_recount: true };
    if (path === "/admin/sessions/80/inventory-custody/variance/approve" && method === "POST") return { status: "RECONCILED_AWAITING_RECEIPT", movement_count: 1, receiver_must_confirm_handoff: true, financial_ready: false };
    throw new Error("Unexpected request " + method + " " + path);
  });
}

describe("representative settlement custody journey", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("company_id", "7");
    localStorage.setItem("backoffice_user_id", "9");
  });

  it("resumes an already authorized blind recount without reopening the review step", async () => {
    await i18n.changeLanguage("en");
    const copy = representativeSettlementCopy("en");
    const authFetch = vi.fn(async (path: string, options: RequestInit = {}) => {
      const method = options.method || "GET";
      if (path.startsWith("/warehouse/locations?")) return { items: [{ id: 91, name: "Main Warehouse", code: "WH-1" }], next_cursor: null, has_more: false, total: 1 };
      if (path === "/inventory/access/locations/capabilities" && method === "POST") return { locations: { "91": ["transfer.destination"] } };
      if (path === "/admin/sessions/80/inventory-custody" && method === "GET") return { ...custody, review_required: true };
      if (path === "/admin/sessions/80/inventory-custody/variance/count-sheet" && method === "GET") return countSheet;
      throw new Error("Unexpected request " + method + " " + path);
    });

    render(<RepresentativeCustodyModal isOpen onClose={vi.fn()} driverName="Representative A" sessionId={80} authFetch={authFetch as never} onFinancialReady={vi.fn()} />);
    expect(await screen.findByText(copy.recountTitle)).toBeInTheDocument();
    expect(screen.queryByText(copy.reviewTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.expected)).not.toBeInTheDocument();
  });

  for (const locale of ["ar", "en"] as const) {
    it("keeps custody, variance, recount, approval and handoff in one " + locale + " DOM journey", async () => {
      await i18n.changeLanguage(locale);
      const copy = representativeSettlementCopy(locale);
      const authFetch = apiMock();
      const onFinancialReady = vi.fn();
      render(<RepresentativeCustodyModal isOpen onClose={vi.fn()} driverName="Representative A" sessionId={80} authFetch={authFetch as never} onFinancialReady={onFinancialReady} />);

      expect(await screen.findByText(copy.countTitle)).toBeInTheDocument();
      expect(screen.getByText("LOT-7", { exact: false })).toBeInTheDocument();
      expect(screen.getByText(copy.statusLabels.DAMAGED, { exact: false })).toBeInTheDocument();
      expect(document.body.textContent).not.toContain(lineKey);
      expect(document.body.textContent).not.toContain("VREC-HIDDEN");

      fireEvent.change(screen.getByLabelText(copy.warehouse), { target: { value: "91" } });
      fireEvent.change(screen.getByLabelText(copy.actual + ": Sample Product"), { target: { value: "8" } });
      fireEvent.click(screen.getByRole("checkbox"));
      fireEvent.click(screen.getByRole("button", { name: copy.receive }));

      expect(await screen.findByText(copy.reviewTitle)).toBeInTheDocument();
      expect(screen.getByText(copy.independentRequired)).toBeInTheDocument();
      expect(screen.getByText("-2")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: copy.requestRecount }));
      fireEvent.change(screen.getByLabelText(copy.recountReason), { target: { value: "Physical recount" } });
      fireEvent.change(screen.getByLabelText(copy.authorizerUsername), { target: { value: "supervisor" } });
      fireEvent.change(screen.getByLabelText(copy.authorizerPassword), { target: { value: "secret" } });
      fireEvent.click(screen.getByRole("button", { name: copy.authorizeRecount }));

      expect(await screen.findByText(copy.recountTitle)).toBeInTheDocument();
      expect(screen.queryByText(copy.expected)).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText(copy.actual + ": Sample Product"), { target: { value: "8" } });
      fireEvent.click(screen.getByRole("button", { name: copy.submitRecount }));

      expect(await screen.findByText(copy.independentSatisfied)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: copy.approve }));
      fireEvent.change(screen.getByLabelText(copy.approvalPassword), { target: { value: "owner-password" } });
      fireEvent.click(screen.getByRole("button", { name: copy.approveFinal }));

      expect(await screen.findByText(copy.handoffTitle)).toBeInTheDocument();
      expect(screen.queryByLabelText(copy.actual + ": Sample Product")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("checkbox"));
      fireEvent.click(screen.getByRole("button", { name: copy.confirmReceipt }));

      await waitFor(() => expect(onFinancialReady).toHaveBeenCalledWith(80));
      expect(document.body.textContent).not.toContain("Vehicle Recon");
      expect(document.body.textContent).not.toContain("VEHICLE_RECON");
    });
  }
});
