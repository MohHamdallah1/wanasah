import { describe, expect, it } from "vitest";

import type { WarehouseProduct } from "@/pages/inventory/liveStock/contracts";
import {
  clearInventoryWarmScope,
  inventoryWarmScopeKey,
  patchLiveStockWarmSnapshot,
  readInventoryShellWarmSnapshot,
  readLiveStockWarmSnapshot,
  writeInventoryShellWarmSnapshot,
} from "@/pages/inventory/inventorySessionCache";

const stockItem = {
  id: 7,
  name: "صنف",
} as unknown as WarehouseProduct;

describe("inventory in-memory warm cache", () => {
  it("partitions snapshots by tenant/actor and warehouse", () => {
    const scopeA = inventoryWarmScopeKey("1", "10");
    const scopeB = inventoryWarmScopeKey("2", "10");
    expect(scopeA).not.toBeNull();
    expect(scopeB).not.toBeNull();

    patchLiveStockWarmSnapshot(scopeA, 100, {
      hasPage: true,
      items: [stockItem],
      nextCursor: "next-a",
    });
    patchLiveStockWarmSnapshot(scopeB, 100, {
      hasPage: true,
      items: [],
      nextCursor: null,
    });

    expect(readLiveStockWarmSnapshot(scopeA, 100)?.items).toHaveLength(1);
    expect(readLiveStockWarmSnapshot(scopeB, 100)?.items).toHaveLength(0);
    expect(readLiveStockWarmSnapshot(scopeA, 101)).toBeNull();

    clearInventoryWarmScope(scopeA);
    clearInventoryWarmScope(scopeB);
  });

  it("keeps page, summary, and lock readiness independent", () => {
    const scope = inventoryWarmScopeKey("3", "11");
    expect(scope).not.toBeNull();

    patchLiveStockWarmSnapshot(scope, 200, {
      hasSummary: true,
      stockTotal: 25,
      alertCount: 3,
    });

    const summaryOnly = readLiveStockWarmSnapshot(scope, 200);
    expect(summaryOnly?.hasSummary).toBe(true);
    expect(summaryOnly?.hasPage).toBe(false);
    expect(summaryOnly?.hasStatus).toBe(false);

    patchLiveStockWarmSnapshot(scope, 200, {
      hasStatus: true,
      auditLocked: false,
    });
    expect(readLiveStockWarmSnapshot(scope, 200)).toMatchObject({
      hasSummary: true,
      hasPage: false,
      hasStatus: true,
      auditLocked: false,
    });

    clearInventoryWarmScope(scope);
  });

  it("returns defensive copies instead of mutable cache references", () => {
    const scope = inventoryWarmScopeKey("4", "12");
    expect(scope).not.toBeNull();

    writeInventoryShellWarmSnapshot(scope, {
      locations: [{ id: 1, name: "A", code: "A" }],
      setup: {
        warehouse_ready: true,
        active_warehouse_count: 1,
        accessible_warehouse_count: 1,
        can_create: false,
      },
      locationsTruncated: false,
      selectedLocationId: 1,
    });

    const first = readInventoryShellWarmSnapshot(scope);
    expect(first).not.toBeNull();
    if (first) first.locations[0].name = "mutated";

    expect(readInventoryShellWarmSnapshot(scope)?.locations[0].name).toBe("A");

    clearInventoryWarmScope(scope);
  });
});
