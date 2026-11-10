import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { beginDashboardSession, captureDashboardSession, notifyDashboardSessionChange } from "@/lib/authStorage";
import type { InventoryCapabilities } from "@/hooks/useInventoryAccess";
import {
  clearLegacyDispatchPreferences, createDispatchAsyncEpoch,
  defaultDispatchPreferences, dispatchActorScope, dispatchPreferencesKey,
  readDispatchPreferences, reconcileDispatchPreferences, writeDispatchPreferences,
} from "@/features/dispatch/sessionScope";

const company = (c: number, p: number, b: number): InventoryCapabilities => ({
  company_id: c, principal_id: p, backoffice_user_id: b, is_company_owner: false,
  location_id: null, permissions: ["dispatch.read", "dispatch.execute"],
  any_permissions: ["dispatch.read", "dispatch.execute"], location_permissions: [],
});
function login(c: number, p: number, b: number) {
  beginDashboardSession();
  localStorage.setItem("admin_token", "synthetic");
  localStorage.setItem("company_id", String(c));
  localStorage.setItem("principal_id", String(p));
  localStorage.setItem("backoffice_user_id", String(b));
  localStorage.setItem("refresh_token", "test-token");
  notifyDashboardSessionChange();
  return captureDashboardSession();
}
const data = {
  zones: [{ id: "1" }, { id: "2" }],
  drivers: [{ id: "3" }],
  vehicles: [{ id: "4", can_execute: true }, { id: "5", can_execute: false }],
  warehouses: [{ id: "6", can_execute: true }, { id: "7", can_execute: false }],
};

describe("Dispatch D10 actor session preferences and async fence", () => {
  beforeEach(() => { localStorage.clear(); vi.stubGlobal("crypto", webcrypto); });
  afterEach(() => vi.unstubAllGlobals());

  it("accepts only a current exact canonical company/principal/Backoffice identity", () => {
    const session = login(1, 2, 3);
    expect(dispatchActorScope(session, company(1, 2, 3))).toBe("1:2:3");
    expect(dispatchActorScope(session, company(1, 2, 4))).toBeNull();
    expect(dispatchActorScope(session, company(1, 4, 3))).toBeNull();
    expect(dispatchActorScope(session, company(4, 2, 3))).toBeNull();
    login(1, 2, 3);
    expect(dispatchActorScope(session, company(1, 2, 3))).toBeNull();
  });

  it("preserves same-actor safe launch selection on refresh, but not a second principal or company", () => {
    const actor = "1:2:3";
    const prefs = { activeTab: "launch" as const, zoneForShops: "2", launchZone: "1", driver: "3", vehicle: "4", sourceWarehouse: "6" };
    expect(writeDispatchPreferences(actor, prefs)).toBe(true);
    expect(reconcileDispatchPreferences(readDispatchPreferences(actor), data, true)).toEqual(prefs);
    expect(readDispatchPreferences("1:9:3")).toEqual(defaultDispatchPreferences());
    expect(readDispatchPreferences("9:2:3")).toEqual(defaultDispatchPreferences());
    expect(readDispatchPreferences("1:2:9")).toEqual(defaultDispatchPreferences());
    expect(localStorage.getItem(dispatchPreferencesKey(actor))).not.toBeNull();
  });

  it("never resurrects a vehicle on another, missing, or unauthorized source warehouse", () => {
    const before = { activeTab: "launch" as const, zoneForShops: "2", launchZone: "1", driver: "3", vehicle: "4", sourceWarehouse: "7" };
    expect(reconcileDispatchPreferences(before, data, true)).toMatchObject({ sourceWarehouse: "", vehicle: "" });
    const other = { ...before, sourceWarehouse: "6", vehicle: "5" };
    expect(reconcileDispatchPreferences(other, data, true).vehicle).toBe("");
    expect(reconcileDispatchPreferences({ ...other, vehicle: "4" }, data, false)).toMatchObject({
      sourceWarehouse: "", vehicle: "", launchZone: "", driver: "",
    });
  });

  it("invalid numeric IDs and malformed/foreign envelopes fail closed", () => {
    const scope = "1:2:3";
    localStorage.setItem(dispatchPreferencesKey(scope), JSON.stringify({
      version: 1, scope: "2:2:3", activeTab: "launch", vehicle: "4", sourceWarehouse: "6",
    }));
    expect(readDispatchPreferences(scope)).toEqual(defaultDispatchPreferences());
    localStorage.setItem(dispatchPreferencesKey(scope), JSON.stringify({
      version: 1, scope, activeTab: "wrong", zoneForShops: "-12",
      launchZone: "not-id", driver: "Infinity", vehicle: "04", sourceWarehouse: "4",
    }));
    expect(readDispatchPreferences(scope)).toMatchObject({
      activeTab: "routes", zoneForShops: "", launchZone: "", driver: "", vehicle: "", sourceWarehouse: "4",
    });
    localStorage.setItem(dispatchPreferencesKey(scope), "{invalid");
    expect(readDispatchPreferences(scope)).toEqual(defaultDispatchPreferences());
  });

  it("erases only global leak-prone legacy keys, never immutable operation records", () => {
    localStorage.setItem("activeTab", "launch");
    localStorage.setItem("wanasah_route_vehicle", "4");
    localStorage.setItem("shop_import_draft", JSON.stringify({ companyId: "1", data: [{ owner: "Private" }] }));
    localStorage.setItem("wanasah:durable:shop-create:1:2:3", "immutable original UUID");
    clearLegacyDispatchPreferences();
    expect(localStorage.getItem("activeTab")).toBeNull();
    expect(localStorage.getItem("wanasah_route_vehicle")).toBeNull();
    expect(localStorage.getItem("shop_import_draft")).toBeNull();
    expect(localStorage.getItem("wanasah:durable:shop-create:1:2:3")).toBe("immutable original UUID");
  });

  it("rejects late async after A→B→A same numeric context, revoke, or login", () => {
    const session = login(1, 2, 3);
    const fence = createDispatchAsyncEpoch(session);
    fence.update("warehouse:6|vehicle:4");
    const stale = fence.capture();
    fence.update("warehouse:7|vehicle:4");
    fence.update("warehouse:6|vehicle:4");
    expect(stale()).toBe(false);
    const revoked = fence.capture();
    fence.revoke();
    expect(revoked()).toBe(false);
    const loginPending = fence.capture();
    login(1, 2, 3);
    expect(loginPending()).toBe(false);
  });
});
