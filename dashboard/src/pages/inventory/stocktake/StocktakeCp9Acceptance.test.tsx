import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { executeStocktakeDurableCommand } from "./durableCommand";

const identity = { companyId: 41, backofficeUserId: 77 };

const source = (path: string) =>
  readFileSync(resolve(process.cwd(), "src/pages/inventory", path), "utf8");

describe("CP9 Stocktake Dashboard V1 closure", () => {
  beforeEach(() => localStorage.clear());

  it("reuses the same request_id and payload after an ambiguous response", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const payload = { count_attempt_id: 9, password: "synthetic", notes: null };

    await expect(executeStocktakeDurableCommand({
      identity,
      operation: "approve",
      target: "5:12",
      payload,
      send: async (body) => {
        bodies.push(body);
        throw Object.assign(new Error("network lost"), { status: 0 });
      },
    })).rejects.toThrow("network lost");

    await executeStocktakeDurableCommand({
      identity,
      operation: "approve",
      target: "5:12",
      payload,
      send: async (body) => {
        bodies.push(body);
        return { status: "POSTED" };
      },
    });

    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[0].request_id).toEqual(expect.any(String));
  });

  it("does not replay a pending command into another session/location scope", async () => {
    const requestIds: string[] = [];
    const payload = { password: "synthetic", reason: "cancel" };
    const ambiguous = async (body: typeof payload & { request_id: string }) => {
      requestIds.push(body.request_id);
      throw Object.assign(new Error("timeout"), { status: 408 });
    };

    await expect(executeStocktakeDurableCommand({
      identity, operation: "cancel", target: "5:12", payload, send: ambiguous,
    })).rejects.toThrow("timeout");
    await expect(executeStocktakeDurableCommand({
      identity, operation: "cancel", target: "6:13", payload, send: ambiguous,
    })).rejects.toThrow("timeout");

    expect(requestIds).toHaveLength(2);
    expect(requestIds[1]).not.toBe(requestIds[0]);
  });

  it("abandons a definitive failure so a deliberate retry gets a fresh identity", async () => {
    const requestIds: string[] = [];
    const payload = { items: [], notes: null };
    await expect(executeStocktakeDurableCommand({
      identity,
      operation: "count",
      target: "5:12",
      payload,
      send: async (body) => {
        requestIds.push(body.request_id);
        throw Object.assign(new Error("validation"), { status: 409 });
      },
    })).rejects.toThrow("validation");

    await executeStocktakeDurableCommand({
      identity,
      operation: "count",
      target: "5:12",
      payload,
      send: async (body) => {
        requestIds.push(body.request_id);
        return { status: "PENDING_REVIEW" };
      },
    });
    expect(requestIds[1]).not.toBe(requestIds[0]);
  });

  it("keeps every action behind its exact independent capability", () => {
    const tab = source("Tab3Stocktake.tsx");
    const sessions = source("stocktake/hooks/useStocktakeSessions.ts");

    expect(tab).toContain('warehouseAccess.can("stocktake.read")');
    expect(tab).toContain("enabled: canReadStocktake");
    expect(sessions).toContain("if (!enabled) return");
    for (const capability of [
      "stocktake.start",
      "stocktake.count",
      "stocktake.review",
      "stocktake.approve",
      "stocktake.recount",
      "stocktake.cancel",
    ]) {
      expect(tab).toContain(capability);
    }
    expect(tab).not.toContain("stocktake.manage");
    expect(tab).not.toContain("isCompanyOwner");
    expect(tab).not.toContain("is_admin");
  });

  it("binds durable mutation identity to exact session/location targets", () => {
    const lifecycle = source("stocktake/hooks/useStocktakeLifecycle.ts");
    const counting = source("stocktake/hooks/useStocktakeCounting.ts");
    const actions = source("stocktake/hooks/useStocktakeActions.ts");
    const cycle = source("stocktake/hooks/useCycleCountStart.ts");
    const vehicle = source("stocktake/hooks/useVehicleReconStart.ts");

    expect(lifecycle).toContain('operation: "start-full"');
    expect(lifecycle).toContain("target: locationId");
    expect(counting).toContain('operation: "count"');
    expect(counting).toContain('target: `${sessionLocationId}:${sessionId}`');
    expect(actions).toContain('operation: "approve"');
    expect(actions).toContain('operation: "recount"');
    expect(actions).toContain('operation: "cancel"');
    expect(cycle).toContain('operation: "start-cycle"');
    expect(vehicle).toContain('operation: "start-vehicle-recon"');
  });

  it("keeps cycle and vehicle eligibility server-owned", () => {
    const cycle = source("stocktake/hooks/useCycleCountStart.ts");
    const vehicle = source("stocktake/hooks/useVehicleReconStart.ts");
    const cycleModal = source("stocktake/StocktakeCycleStartModal.tsx");
    const vehicleModal = source("stocktake/StocktakeVehicleReconModal.tsx");

    expect(cycle).toContain("/warehouse/unified/stocktake/cycle-batches?");
    expect(vehicle).toContain("/warehouse/unified/stocktake/vehicle-recon-candidates?");
    expect(cycleModal).not.toContain("__WANASAH_NOLOT__");
    expect(vehicleModal).not.toContain("stocktake.start");
  });

  it("keeps review truth explicit and count workflow keyboard/phone usable", () => {
    const count = source("stocktake/StocktakeCountingPanel.tsx");
    const review = source("stocktake/StocktakeReviewPanel.tsx");
    const decisions = source("stocktake/StocktakeDecisionModals.tsx");
    const uiCopy = source("stocktake/uiCopy.ts");

    expect(count).toContain("data-stocktake-count-input");
    expect(count).toContain('event.key !== "Enter"');
    expect(count).toContain("md:hidden");
    expect(count).toContain("hidden md:block");
    expect(count).toContain("autoFocus");
    expect(review).toContain("useStocktakeUiCopy");
    expect(review).toContain("text.expected");
    expect(review).toContain("text.counted");
    expect(review).toContain("text.variance");
    expect(uiCopy).toContain('expected: "المتوقع"');
    expect(uiCopy).toContain('expected: "Expected"');
    expect(uiCopy).toContain('counted: "الفعلي"');
    expect(uiCopy).toContain('counted: "Counted"');
    expect(uiCopy).toContain('variance: "الفرق"');
    expect(uiCopy).toContain('variance: "Variance"');
    expect(review).toContain("md:hidden");
    expect(decisions).toContain("autoFocus");
    expect(decisions).toContain('event.key !== "Enter"');
  });

  it("has bilingual RTL/LTR copy on all touched primary Stocktake surfaces", () => {
    for (const path of [
      "stocktake/StocktakeCountingPanel.tsx",
      "stocktake/StocktakeReviewPanel.tsx",
      "stocktake/StocktakeSessionCenter.tsx",
      "stocktake/StocktakeCountModals.tsx",
      "stocktake/StocktakeDecisionModals.tsx",
      "stocktake/StocktakeCycleStartModal.tsx",
      "stocktake/StocktakeVehicleReconModal.tsx",
    ]) {
      const text = source(path);
      expect(text).toContain("dir");
      expect(text).toMatch(/isArabic|useStocktakeCopy|useStocktakeUiCopy/);
    }
  });
});