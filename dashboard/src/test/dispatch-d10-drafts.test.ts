import { beforeEach, describe, expect, it } from "vitest";
import {
  clearRouteLoadDraft, clearShortageDraft, restoreRouteLoadDraft, restoreShortageDraft,
  routeDraftKey, saveRouteLoadDraft, saveShortageDraft, shortageDraftKey,
} from "@/features/dispatch/dispatchDrafts";
import type { Shop, Zone } from "@/types/dispatch";

const actor = "1:2:3";
const base = { "8": "12", "9": "5" };
const targets = { "8": "14", "9": "4" };
const zones = [{ id: "7" }] as Zone[];
const shops = [{ id: "6", zoneId: "7", archived: false }] as Shop[];
const drivers = [{ id: "5" }];

describe("Dispatch D10 location and actor drafts", () => {
  beforeEach(() => localStorage.clear());
  it("recovers same-actor unchanged vehicle stock but rejects Warehouse A→B, vehicle B and other actor", () => {
    saveRouteLoadDraft(actor, "21", "31", "7", "5", base, targets);
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", base, ["8", "9"])).toEqual(targets);
    expect(restoreRouteLoadDraft("1:99:3", "21", "31", "7", "5", base, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft("2:2:3", "21", "31", "7", "5", base, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft(actor, "22", "31", "7", "5", base, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft(actor, "21", "32", "7", "5", base, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft(actor, "21", "31", "8", "5", base, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "6", base, ["8", "9"])).toBeNull();
  });
  it("fails closed on changed physical balance and unknown/removed products", () => {
    saveRouteLoadDraft(actor, "21", "31", "7", "5", base, targets);
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", { ...base, "8": "13" }, ["8", "9"])).toBeNull();
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", base, ["8"])).toBeNull();
    localStorage.setItem(routeDraftKey(actor, "21", "31", "7", "5"), JSON.stringify({
      version: 1, scope: actor, warehouse: "21", vehicle: "31", zone: "7", driver: "5",
      base, targets: { "999": "1" },
    }));
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", base, ["8", "9"])).toBeNull();
  });
  it("invalid quantities and foreign/tampered record never restore", () => {
    saveRouteLoadDraft(actor, "21", "31", "7", "5", base, { "8": "-1" });
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", base, ["8", "9"])).toBeNull();
    localStorage.setItem(routeDraftKey(actor, "21", "31", "7", "5"), '{"scope":"2:2:3","version":1}');
    expect(restoreRouteLoadDraft(actor, "21", "31", "7", "5", base, ["8", "9"])).toBeNull();
    clearRouteLoadDraft(actor, "21", "31", "7", "5");
    expect(localStorage.getItem(routeDraftKey(actor, "21", "31", "7", "5"))).toBeNull();
  });
  it("preserves an authorized shortage draft on refresh and blocks changed shop-zone or actor", () => {
    const rows = [{ productId: "11", productName: "Lolo", quantity: 4 }];
    saveShortageDraft(actor, { zoneId: "7", shopId: "6", driverId: "5", rows });
    expect(restoreShortageDraft(actor, zones, shops, drivers)?.rows).toEqual(rows);
    expect(restoreShortageDraft("1:99:3", zones, shops, drivers)).toBeNull();
    expect(restoreShortageDraft("2:2:3", zones, shops, drivers)).toBeNull();
    expect(restoreShortageDraft(actor, zones, [{ ...shops[0], zoneId: "9" }], drivers)).toBeNull();
    expect(restoreShortageDraft(actor, zones, [{ ...shops[0], archived: true }], drivers)).toBeNull();
    expect(restoreShortageDraft(actor, zones, shops, [])).toBeNull();
  });
  it("rejects poisoned excessive, invalid and foreign shortage rows, clears only matching actor", () => {
    saveShortageDraft(actor, { zoneId: "7", shopId: "6", driverId: "", rows: [{ productId: "0", productName: "bad", quantity: 1 }] });
    expect(restoreShortageDraft(actor, zones, shops, drivers)).toBeNull();
    localStorage.setItem(shortageDraftKey(actor), JSON.stringify({
      version: 1, scope: actor, zoneId: "7", shopId: "6", driverId: "",
      rows: [{ productId: "8", productName: "Lolo", quantity: -4 }],
    }));
    expect(restoreShortageDraft(actor, zones, shops, drivers)).toBeNull();
    saveShortageDraft("2:2:3", { zoneId: "7", shopId: "6", driverId: "", rows: [{ productId: "11", productName: "A", quantity: 2 }] });
    clearShortageDraft(actor);
    expect(localStorage.getItem(shortageDraftKey("2:2:3"))).not.toBeNull();
  });
});
