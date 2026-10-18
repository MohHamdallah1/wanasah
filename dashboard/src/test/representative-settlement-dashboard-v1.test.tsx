import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("Representative settlement Dashboard V1 cleanup", () => {
  it("keeps Stocktake from exposing a second representative-settlement start entry", () => {
    const tab = read("src/pages/inventory/Tab3Stocktake.tsx");
    const sessions = read("src/pages/inventory/stocktake/StocktakeSessionCenter.tsx");

    expect(tab).not.toContain("useVehicleReconStart");
    expect(tab).not.toContain("StocktakeVehicleReconModal");
    expect(tab).not.toContain("onStartVehicleRecon");
    expect(sessions).not.toContain("onStartVehicleRecon");
    expect(sessions).not.toContain("vehicleAction");
  });

  it("keeps the financial step read-only for inventory and stops sending legacy inventory_jard", () => {
    const modal = read("src/components/operations/SettlementModal.tsx");
    const operations = read("src/pages/OperationsDashboard.tsx");

    expect(modal).toContain('data-representative-settlement-inventory="read-only"');
    expect(modal).toContain("report.inventory.map");
    expect(modal).not.toContain("QuantityInput");
    expect(modal).not.toContain("jardData");
    expect(modal).not.toContain("actual_cartons");
    expect(modal).not.toContain("actual_loose_packs");
    expect(operations).not.toContain("inventory_jard");
    expect(operations).not.toContain("SettlementCountInput");
    expect(operations).toContain("JSON.stringify({ actual_cash: actualCash, notes: notes })");
  });

  it("does not guess the pending backend inventory-stage contract", () => {
    const operations = read("src/pages/OperationsDashboard.tsx");
    const commandCenter = read("src/components/operations/CommandCenter.tsx");
    const hero = read("src/components/dashboard/HeroSettlement.tsx");

    expect(operations).not.toContain("/warehouse/unified/stocktake/start");
    expect(commandCenter).toContain("FINANCIAL_SETTLEMENT_READY_STATUS");
    expect(commandCenter).toContain("disabled={!canApproveSettlement}");
    expect(hero).not.toContain("authFetch");
  });
});
