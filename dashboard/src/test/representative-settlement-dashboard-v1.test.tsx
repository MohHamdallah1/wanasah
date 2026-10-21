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
    const commandCenter = read("src/components/operations/CommandCenter.tsx");
    expect(commandCenter.match(/data-representative-settlement-entry/g)).toHaveLength(1);
  });

  it("keeps the financial step read-only for inventory and stops sending legacy inventory_jard", () => {
    const modal = read("src/components/operations/SettlementModal.tsx");
    const operations = read("src/pages/OperationsDashboard.tsx");
    const financial = read("src/features/operations/representativeSettlement/financialSettlementAdapter.ts");
    const durable = read("src/features/operations/representativeSettlement/durableCommand.ts");

    expect(modal).toContain('data-representative-settlement-inventory="read-only"');
    expect(modal).toContain("report.inventory.map");
    expect(modal).not.toContain("QuantityInput");
    expect(modal).not.toContain("jardData");
    expect(modal).not.toContain("actual_cartons");
    expect(modal).not.toContain("actual_loose_packs");
    expect(operations).not.toContain("inventory_jard");
    expect(operations).not.toContain("SettlementCountInput");
    expect(financial).not.toContain("inventory_jard");
    expect(financial).toContain("actual_cash: command.actualCash");
    expect(financial).toContain("executeRepresentativeSettlementCommand");
    expect(financial).toContain('operation: "financial-close"');
    expect(durable).toContain("request_id: command.requestId");
  });

  it("uses the Operations-owned custody contract without exposing Stocktake mechanics", () => {
    const operations = read("src/pages/OperationsDashboard.tsx");
    const commandCenter = read("src/components/operations/CommandCenter.tsx");
    const api = read("src/features/operations/representativeSettlement/api.ts");
    const hero = read("src/components/dashboard/HeroSettlement.tsx");

    expect(operations).not.toContain("/warehouse/unified/stocktake/start");
    expect(commandCenter).toContain('data-representative-settlement-entry="yellow-card"');
    expect(api).toContain("/warehouse/unified/transfer/locations?");
    expect(api).not.toContain("/warehouse/locations?");
    expect(api).not.toContain("/inventory/access/locations/capabilities");
    for (const suffix of [
      "/inventory-custody",
      "/inventory-custody/receive",
      "/inventory-custody/variance",
      "/inventory-custody/variance/recount",
      "/inventory-custody/variance/count-sheet",
      "/inventory-custody/variance/count",
      "/inventory-custody/variance/approve",
    ]) expect(api).toContain(suffix);
    expect(hero).not.toContain("authFetch");
  });
});
