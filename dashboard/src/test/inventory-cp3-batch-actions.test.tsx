import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { parseWarehouseBatchActionSource } from "@/pages/inventory/batches/batchActionContracts";

const root = resolve(process.cwd(), "src/pages/inventory");
const read = (path: string) => readFileSync(resolve(root, path), "utf8");

const sourcePayload = () => ({
  location_id: 11,
  location_name: "Warehouse A1",
  product_variant_id: 41,
  batch_id: 71,
  base_uom_id: 1,
  base_uom_code: "EA",
  quantity_scale: 6,
  quantity_step: "0.000001",
  statuses: [
    {
      stock_status: "AVAILABLE",
      on_hand_quantity: "10.000001",
      reserved_quantity: "3.000001",
      movable_quantity: "7",
      reservation_evidence: {
        coverage: "UNRESOLVED",
        reason: "OWNER_EVIDENCE_UNAVAILABLE",
        owners: [],
        owners_truncated: false,
        unattributed_quantity: "3.000001",
      },
      status_change_actions: [
        {
          destination_status: "QUARANTINED",
          allowed: true,
          eligible_quantity: "7",
          reason_code: "ALLOWED",
        },
        {
          destination_status: "BLOCKED",
          allowed: true,
          eligible_quantity: "7",
          reason_code: "ALLOWED",
        },
        {
          destination_status: "RECALLED",
          allowed: true,
          eligible_quantity: "7",
          reason_code: "ALLOWED",
        },
      ],
    },
  ],
});

describe("CP3 batch core actions", () => {
  it("parses exact-Warehouse server-derived status eligibility without numeric coercion", () => {
    const parsed = parseWarehouseBatchActionSource(sourcePayload(), {
      locationId: 11,
      productVariantId: 41,
      batchId: 71,
    });
    expect(parsed.location_name).toBe("Warehouse A1");
    expect(parsed.quantity_step).toBe("0.000001");
    expect(parsed.statuses[0].movable_quantity).toBe("7");
    expect(parsed.statuses[0].status_change_actions.map((action) => action.destination_status)).toEqual([
      "QUARANTINED",
      "BLOCKED",
      "RECALLED",
    ]);
  });

  it("fails closed on warehouse scope drift and over-eligible server responses", () => {
    expect(() =>
      parseWarehouseBatchActionSource(sourcePayload(), {
        locationId: 12,
        productVariantId: 41,
        batchId: 71,
      }),
    ).toThrow("BATCH_ACTION_SOURCE_RESPONSE_INVALID");

    const payload = sourcePayload();
    payload.statuses[0].status_change_actions[0].eligible_quantity = "8";
    expect(() =>
      parseWarehouseBatchActionSource(payload, {
        locationId: 11,
        productVariantId: 41,
        batchId: 71,
      }),
    ).toThrow("BATCH_ACTION_SOURCE_RESPONSE_INVALID");
  });

  it("keeps disposition company-wide and stock status selected-Warehouse specific", () => {
    const manager = read("batches/BatchDispositionManager.tsx");
    const panel = read("batches/StockStatusActionsPanel.tsx");
    const tab = read("TabBatches.tsx");

    expect(manager).toContain('actionText("dispositionScope")');
    expect(manager).toContain("<StockStatusActionsPanel");
    expect(manager).toContain('access.can("batch.disposition")');
    expect(manager).not.toContain("access.isCompanyOwner ||");
    expect(panel).toContain('access.can("inventory.status_change")');
    expect(panel).toContain("action.allowed");
    expect(panel).toContain("locationId={locationId}");
    expect(tab).toContain("selectedWarehouseId={locationId}");
    expect(tab).toContain("onInventoryChanged");
    expect(tab).not.toContain("access.isCompanyOwner || access.can(\"batch.disposition\")");
  });

  it("does not reconstruct the stock-status transition matrix in React", () => {
    const panel = read("batches/StockStatusActionsPanel.tsx");
    const dialog = read("batches/StockStatusChangeDialog.tsx");
    const contracts = read("batches/batchActionContracts.ts");

    for (const source of [panel, dialog, contracts]) {
      expect(source).not.toContain("_PORTION_STATUS_TRANSITIONS");
      expect(source).not.toContain('AVAILABLE: ["QUARANTINED"');
      expect(source).not.toContain('case "AVAILABLE"');
    }
    expect(panel).toContain("status.status_change_actions.filter((action) => action.allowed)");
  });

  it("uses durable exact-quantity commands and preserves ambiguous retry identity", () => {
    const hook = read("batches/useStockStatusCommand.ts");
    expect(hook).toContain("validateVariantQuantity(");
    expect(hook).toContain("compareQuantity(normalized, eligibleQuantity)");
    expect(hook).toContain('"inventory-status-change-v1"');
    expect(hook).toContain("`${batchId}:${locationId}:${productVariantId}:${sourceStatus}`");
    expect(hook).toContain("isAmbiguousRequestError(error)");
    expect(hook).toContain("request_id: durable.requestId");
    expect(hook).not.toContain("Number(quantity)");
    expect(hook).not.toContain("parseFloat");
  });

  it("recovers revision conflicts by refreshing authority and requiring a fresh target", () => {
    const hook = read("batches/useBatchDispositionCommand.ts");
    const manager = read("batches/BatchDispositionManager.tsx");
    expect(hook).toContain('code === "BATCH_DISPOSITION_REVISION_CONFLICT"');
    expect(hook).toContain("setTargetState(null)");
    expect(hook).toContain("await onRevisionConflict()");
    expect(manager).toContain("command.revisionConflict");
    expect(manager).toContain('actionText("dispositionConflict")');
  });

  it("keeps reservation evidence visible and exact source-to-destination confirmation", () => {
    const manager = read("batches/BatchDispositionManager.tsx");
    const panel = read("batches/StockStatusActionsPanel.tsx");
    const dialog = read("batches/StockStatusChangeDialog.tsx");
    expect(manager).toContain("<BatchQuantityActions");
    expect(panel).toContain('text("reserved"');
    expect(panel).toContain('text("eligible"');
    expect(dialog).toContain('text("sourceStatus")');
    expect(dialog).toContain('text("destinationStatus")');
    expect(dialog).toContain('inputMode="decimal"');
  });

  it("keeps AR/EN, no-lot, RTL/LTR, mobile sizing and keyboard/focus semantics", () => {
    const copy = read("batches/batchActionsI18n.ts");
    const dialog = read("batches/StockStatusChangeDialog.tsx");
    const manager = read("batches/BatchDispositionManager.tsx");
    expect(copy).toContain('noLot: "بدون رقم دفعة"');
    expect(copy).toContain('noLot: "No lot supplied"');
    expect(copy).toContain('stockStatusTitle: "حالة كمية المخزون"');
    expect(copy).toContain('stockStatusTitle: "Warehouse stock status"');
    expect(dialog).toContain("initialFocusRef={quantityRef}");
    expect(dialog).toContain("onSubmit={(event)");
    expect(dialog).toContain("sm:flex-row");
    expect(manager).toContain("sm:grid-cols-2");
  });

  it("keeps bounded mutation refresh explicit for Batches and shell-owned Live/Ledger truth", () => {
    const tab = read("TabBatches.tsx");
    const shell = read("MainInventory.tsx");
    expect(tab).toContain("await batchIndex.refresh()");
    expect(tab).toContain("await onInventoryChanged()");
    expect(shell).toContain("<TabBatches");
    expect(shell).toContain("onInventoryChanged");
  });
});
