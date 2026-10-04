import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { resources } from "@/i18n/resources";
import { ArchiveBlockerList } from "@/features/catalog/archive/ArchiveBlockerList";
import { archiveOwnerGap, archiveOwnerNavigation } from "@/features/catalog/archive/navigation";
import { parseArchiveOwnerTarget, type ArchiveOwnerTarget } from "@/features/catalog/archive/ownerTargets";
import { parseArchivePreflight, type ArchiveBlocker } from "@/features/catalog/contracts";
import { createInventoryOwnerFocusState, parseInventoryNavigationState } from "@/features/inventory/navigation";
import { createDispatchOwnerFocusState, parseDispatchNavigationState } from "@/features/dispatch/navigation";
import { createSettlementOwnerState, parseOperationsNavigationState } from "@/features/operations/navigation";

const mocks = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("react-router-dom", () => ({ useNavigate: () => mocks.navigate }));
afterEach(() => { cleanup(); mocks.navigate.mockClear(); });

const targets: Array<[string, ArchiveOwnerTarget]> = [
  ["INVENTORY_BALANCE", { kind: "batch", operation_id: 11, batch_id: 50, location_id: 1 }],
  ["OPEN_TRANSFER", { kind: "transfer", operation_id: 20, location_id: 3, reference: "TX-20" }],
  ["OPEN_TRANSFER", { kind: "handshake", operation_id: 21, route_id: 70 }],
  ["OPEN_STOCKTAKE", { kind: "stocktake", operation_id: 30, location_id: 1 }],
  ["ACTIVE_INVENTORY_LOCK", { kind: "stocktake", operation_id: 30, location_id: 1 }],
  ["PRODUCT_LOCATION", { kind: "product-location", operation_id: 60, location_id: 1 }],
  ["ACTIVE_ROUTE_LOAD", { kind: "route-load", operation_id: 70, route_id: 70 }],
  ["OPEN_SHORTAGE", { kind: "shortage", operation_id: 90 }],
  ["OPEN_CUSTODY", { kind: "settlement", operation_id: 80 }],
];
const blocker = (code: string, target: ArchiveOwnerTarget | null = null): ArchiveBlocker => ({ code, count: 2, sample_id: 11, owner_target: target });

describe("archive owner navigation", () => {
  it.each(targets)("maps %s to exact owner identity, never Live Stock", (code, target) => {
    expect(parseArchiveOwnerTarget(target)).toEqual(target);
    const action = archiveOwnerNavigation(blocker(code, target), 101);
    expect(action).toBeTruthy();
    expect(action?.path).toBe(target.kind === "settlement" ? "/" : target.kind === "handshake" || target.kind === "route-load" || target.kind === "shortage" ? "/dispatch" : "/inventory");
    if (action?.path === "/inventory") {
      const intent = parseInventoryNavigationState(action.state);
      expect(intent?.kind).toBe("owner-focus");
      expect(intent?.tab).not.toBe("live");
      expect(intent).toMatchObject({ variantId: 101, operationId: target.kind === "batch" ? target.batch_id : "operation_id" in target ? target.operation_id : 0 });
    } else if (action?.path === "/") {
      expect(parseOperationsNavigationState(action.state)).toEqual({ version: 1, kind: "settlement-owner", sessionId: 80 });
    } else {
      expect(parseDispatchNavigationState(action?.state)).not.toBeNull();
    }
  });

  it.each(["STOCK_POLICY", "ACTIVE_OFFER", "OPEN_CUSTODY", "NEW_UNKNOWN_BLOCKER"])("does not invent an action for %s", (code) => {
    expect(archiveOwnerNavigation(blocker(code), 101)).toBeNull();
    expect(archiveOwnerGap(blocker(code))).toBeTruthy();
  });

  it("rejects mismatched owner types and explains authoritative assignment-history gaps", () => {
    expect(archiveOwnerNavigation(blocker("OPEN_STOCKTAKE", { kind: "shortage", operation_id: 90 }), 101)).toBeNull();
    const historical = blocker("PRODUCT_LOCATION", { kind: "capability-gap", reason: "PRODUCT_LOCATION_REFERENCES" });
    expect(archiveOwnerNavigation(historical, 101)).toBeNull();
    expect(archiveOwnerGap(historical)).toBe("history");
  });

  it.each(["INVENTORY_SOURCE", "TRANSIT_STATE", "STOCKTAKE_STATE"] as const)("renders %s as a capability gap without an action", (reason) => {
    const target: ArchiveOwnerTarget = { kind: "capability-gap", reason };
    expect(parseArchiveOwnerTarget(target)).toEqual(target);
    const item = blocker("OPEN_TRANSFER", target);
    expect(archiveOwnerNavigation(item, 101)).toBeNull();
    expect(archiveOwnerGap(item)).not.toBe("unavailable");
  });

  it.each([null, {}, { kind: "batch", operation_id: 11, batch_id: -1, location_id: 1 }, { kind: "stocktake", operation_id: 30, location_id: 0 }, { kind: "legacy-offer", operation_id: 90 }])("fails closed for malformed hints", (raw) => {
    expect(parseArchiveOwnerTarget(raw)).toBeNull();
  });

  it("keeps old preflight compatible and parses the optional read projection", () => {
    const response = { variant_id: 101, lifecycle_status: "RETIRING", version: 2, can_archive: false, blockers: [{ code: "OPEN_TRANSFER", count: 1, sample_id: 20 }] };
    expect(parseArchivePreflight(response).blockers[0].owner_target).toBeNull();
    response.blockers = [{ ...response.blockers[0], ...{ owner_target: targets[1][1] } }];
    expect(parseArchivePreflight(response).blockers[0].owner_target).toEqual(targets[1][1]);
  });

  it("validates owner navigation version, matching tab and positive IDs", () => {
    expect(parseOperationsNavigationState(createSettlementOwnerState(80))).toEqual({ version: 1, kind: "settlement-owner", sessionId: 80 });
    expect(parseOperationsNavigationState(createSettlementOwnerState(0))).toBeNull();
    expect(parseOperationsNavigationState({ operationsNavigation: { version: 2, kind: "settlement-owner", sessionId: 80 } })).toBeNull();
    const state = createInventoryOwnerFocusState({ flow: "stocktake", variantId: 101, operationId: 30, locationId: 1, reference: "" });
    expect(parseInventoryNavigationState(state)).toEqual(state.inventoryNavigation);
    expect(parseInventoryNavigationState({ inventoryNavigation: { ...state.inventoryNavigation, tab: "live" } })).toBeNull();
    expect(parseInventoryNavigationState({ inventoryNavigation: { ...state.inventoryNavigation, operationId: 0 } })).toBeNull();
    for (const intent of [{ version: 1, kind: "route-load", routeId: 70 }, { version: 1, kind: "shortage-owner", shortageId: 90 }] as const) {
      expect(parseDispatchNavigationState(createDispatchOwnerFocusState(intent))).toEqual(intent);
      expect(parseDispatchNavigationState({ dispatchNavigation: { ...intent, version: 2 } })).toBeNull();
    }
  });

  it.each(["ar", "en"])("renders localized, keyboard reachable actions and explicit gaps in %s", async (language) => {
    const i18n = createInstance();
    await i18n.init({ resources, lng: language, fallbackLng: "en", interpolation: { escapeValue: false } });
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(<I18nextProvider i18n={i18n}><ArchiveBlockerList variantId={101} blockers={[blocker("OPEN_TRANSFER", targets[1][1]), blocker("STOCK_POLICY")]} /></I18nextProvider>);
    expect(screen.getByRole("list")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    const button = screen.getByRole("button", { name: i18n.t("archiveOwners.actions.transfer") });
    button.focus(); expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(mocks.navigate).toHaveBeenCalledWith("/inventory", { state: expect.objectContaining({ inventoryNavigation: expect.objectContaining({ flow: "transfer", operationId: 20, locationId: 3 }) }) });
    expect(screen.getByText(i18n.t("archiveOwners.gaps.policy"))).toBeVisible();
    expect(screen.getAllByText("2")).toHaveLength(2);
    expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
});
