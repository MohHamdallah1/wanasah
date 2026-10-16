import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

const sources = {
  live: read("src/pages/inventory/Tab1LiveStock.tsx"),
  liveTable: read("src/pages/inventory/liveStock/LiveStockTable.tsx"),
  liveMobile: read("src/pages/inventory/liveStock/LiveStockMobileCards.tsx"),
  liveContext: read("src/pages/inventory/liveStock/LiveStockWarehouseContext.tsx"),
  transfers: read("src/pages/inventory/TabTransfers.tsx"),
  transferTable: read("src/pages/inventory/transfers/TransferTable.tsx"),
  transferActions: read("src/pages/inventory/transfers/TransferRowActions.tsx"),
  transferCreate: read("src/pages/inventory/transfers/TransferCreateModal.tsx"),
  transferFefo: read("src/pages/inventory/transfers/FefoOverrideEditor.tsx"),
  transferDecision: read("src/pages/inventory/transfers/TransferDecisionModal.tsx"),
  transferParser: read("src/pages/inventory/transfers/parsers.ts"),
  transferI18n: read("src/pages/inventory/transfers/i18n.ts"),
  ledger: read("src/pages/inventory/Tab4Ledger.tsx"),
  ledgerFilters: read("src/pages/inventory/ledger/LedgerFilters.tsx"),
  ledgerTable: read("src/pages/inventory/ledger/LedgerTable.tsx"),
  ledgerMobile: read("src/pages/inventory/ledger/LedgerMobileCards.tsx"),
  ledgerAdjustment: read("src/pages/inventory/ledger/LedgerAdjustmentModal.tsx"),
  ledgerContract: read("src/pages/inventory/ledger/contracts.ts"),
  modal: read("src/components/ui/modal.tsx"),
  focusTrap: read("src/hooks/useDialogFocusTrap.ts"),
};

describe("CP13.5 operations presentation consistency", () => {
  it("keeps Live Stock compact, stock-first and quantity distinctions explicit", () => {
    expect(sources.live).toContain('data-cp13-density="compact"');
    expect(sources.live).toContain('data-cp13-controls="stock-list"');
    expect(sources.liveTable).toContain('data-cp13-stock-table="compact"');
    expect(sources.liveTable).toContain('data-cp13-quantity={metric}');
    expect(sources.liveTable).toContain('"reserved"');
    expect(sources.liveTable).toContain('"available"');
    expect(sources.liveTable).toContain('"unavailable"');
    expect(sources.liveMobile).toContain('data-cp13-phone-list="true"');
    expect(sources.liveContext).toContain('data-cp13-warehouse-context="true"');
  });

  it("keeps Live Stock stale truth explicit with one recoverable retry path and cursor continuation", () => {
    expect(sources.live).toContain('data-cp13-state="stale"');
    expect(sources.live).toContain('t("inventoryLive.errors.staleData")');
    expect(sources.live).toContain("onClick={onRetryPage}");
    expect(sources.live).toContain('data-cp13-continuation="cursor"');
    expect(sources.live).toContain("IntersectionObserver");
    expect(sources.live).toContain("hasMore &&");
  });

  it("presents Transfers with reference, route, purpose, status, quantity summary and clear action hierarchy", () => {
    expect(sources.transfers).toContain('data-cp13-controls="transfer-list"');
    expect(sources.transferTable).toContain('t("inventoryTransfers.source")');
    expect(sources.transferTable).toContain('t("inventoryTransfers.destination")');
    expect(sources.transferTable).toContain('t("inventoryTransfers.purpose")');
    expect(sources.transferTable).toContain('data-cp13-transfer-status={transfer.status}');
    expect(sources.transferTable).toContain("transfer.line_count");
    expect(sources.transferTable).toContain("transfer.total_quantity");
    expect(sources.transferActions).toContain('data-cp13-action-priority={priority}');
  });

  it("keeps transfer purpose required and FEFO automatic while override stays exceptional and reason-bound", () => {
    expect(sources.transferCreate).toContain('data-cp13-transfer-purpose="required"');
    expect(sources.transferParser).toContain('if (!isTransferPurpose(row.transfer_purpose)) throw invalid("transfer_purpose");');
    expect(sources.transferFefo).toContain('data-cp13-fefo-mode={item.fefo_mode}');
    expect(sources.transferFefo).toContain('data-cp13-fefo-override="exceptional"');
    expect(sources.transferFefo.match(/aria-required="true"/g)?.length).toBe(2);
    expect(sources.transferFefo).toContain('t("inventoryTransfers.overrideReason")');
    expect(sources.transferCreate.match(/type="submit"/g)?.length).toBe(1);
  });

  it("makes receive, reject and cancel visually distinct without changing capability gates", () => {
    expect(sources.transferActions).toContain('code: "transfer.receive"');
    expect(sources.transferActions).toContain('code: "transfer.reject"');
    expect(sources.transferActions).toContain('code: "transfer.cancel"');
    expect(sources.transferActions).toContain('can(code)');
    expect(sources.transferActions).toContain('data-cp13-transfer-decision={action}');
    expect(sources.transferDecision).toContain('data-cp13-transfer-decision={action ?? undefined}');
    expect(sources.transferDecision).toContain('aria-required="true"');
    expect(sources.transferDecision).toContain('action === "receive"');
    expect(sources.transferDecision).toContain('action === "reject"');
  });

  it("keeps Ledger a dense chronological investigation surface with explicit movement direction", () => {
    expect(sources.ledger).toContain('data-cp13-density="compact"');
    expect(sources.ledgerFilters).toContain('data-cp13-controls="ledger-list"');
    expect(sources.ledgerTable).toContain('data-cp13-ledger-list="chronological"');
    expect(sources.ledgerTable).toContain('data-cp13-ledger-row="compact"');
    expect(sources.ledgerTable).toContain('data-cp13-movement-direction={outgoing ? "out" : "in"}');
    expect(sources.ledgerMobile).toContain('data-cp13-phone-list="true"');
  });

  it("keeps Ledger correction exceptional, permission-gated and append-only", () => {
    expect(sources.ledger).toContain('access.can("ledger.adjust")');
    expect(sources.ledgerTable).toContain('entry.type === "INBOUND_SUPPLIER" && canAdjust');
    expect(sources.ledgerTable).toContain('data-cp13-ledger-correction="exceptional"');
    expect(sources.ledgerAdjustment).toContain('data-cp13-ledger-correction="append-only"');
    expect(sources.ledgerAdjustment).toContain('text("adjustmentMeaning")');
    expect(sources.ledgerContract).toContain('type: string;');
  });

  it("keeps common loading, empty, recoverable error, RTL/LTR, western digits, focus and phone contracts", () => {
    expect(sources.live).toContain('data-cp13-state="loading"');
    expect(sources.live).toContain('data-cp13-state="empty"');
    expect(sources.transfers).toContain('data-cp13-state={transferList.failure.phase === "first" ? "error" : "stale"}');
    expect(sources.transferTable).toContain('data-cp13-state="empty"');
    expect(sources.ledger).toContain('data-cp13-state="loading"');
    expect(sources.ledger).toContain('data-cp13-state="empty"');
    expect(sources.transfers).toContain("dir={i18n.dir()}");
    expect(sources.ledger).toContain("dir={i18n.dir()}");
    expect(sources.transferI18n).toContain('numberingSystem: "latn"');
    expect(sources.liveTable).toContain('numberingSystem: "latn"');
    expect(sources.liveContext).toContain('numberingSystem: "latn"');
    expect(sources.ledgerContract).toContain('numberingSystem: "latn"');
    expect([sources.live, sources.liveTable, sources.transfers, sources.transferActions, sources.ledgerFilters, sources.ledgerTable].join("\n")).toContain("focus-visible:ring-2");
    expect(sources.modal).toContain("useDialogFocusTrap");
    expect(sources.focusTrap).toContain('event.key === "Escape"');
    expect(sources.focusTrap).toContain('event.key !== "Tab"');
    expect(sources.focusTrap).toContain("restore.focus()");
    expect(sources.transferTable).toContain('data-cp13-phone-list="true"');
  });
});
