import { describe, expect, it, vi } from "vitest";
import type { InventoryCapabilities } from "@/hooks/useInventoryAccess";
import { createDispatchReadFence, dispatchPrivileges } from "@/features/dispatch/dispatchAccess";
import { loadDispatchRead } from "@/features/dispatch/loadDispatchRead";

const grants = (permissions: string[], any_permissions = permissions, owner = false): InventoryCapabilities => ({
  company_id: 12, principal_id: 8, backoffice_user_id: 9,
  is_company_owner: owner, location_id: null, permissions, any_permissions,
  location_permissions: [],
});

describe("Dispatch D09 effective privileges", () => {
  it("fails closed while identity is unknown, even if a prior account was an owner", () => {
    expect(Object.values(dispatchPrivileges(undefined)).every(value => value === false)).toBe(true);
    expect(dispatchPrivileges(grants([], [], true)).zones).toBe(false);
  });

  it("shows Zones and scoped Routes to a non-owner with an effective dispatch read grant", () => {
    const result = dispatchPrivileges(grants([], ["dispatch.read"]));
    expect(result.routes).toBe(true);
    expect(result.zones).toBe(true);
    expect(result.zoneManage).toBe(false);
    expect(result.launch).toBe(false);
  });

  it("keeps company write and independent shortage read/create/cancel separate", () => {
    const reader = dispatchPrivileges(grants(["dispatch.read", "shortage.read"]));
    expect(reader.zones).toBe(true);
    expect(reader.zoneManage).toBe(false);
    expect(reader.shortages).toBe(true);
    expect(reader.shortageCreate).toBe(false);
    expect(reader.shortageCancel).toBe(false);
    expect(reader.shortageEdit).toBe(false);
    const editor = dispatchPrivileges(grants(["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"]));
    expect(editor.zoneManage).toBe(true);
    expect(editor.shortageCreate).toBe(true);
    expect(editor.shortageCancel).toBe(true);
    expect(editor.shortageEdit).toBe(true);
  });

  it("shortage-only grants do not imply dispatch/financial reads", () => {
    const result = dispatchPrivileges(grants(["shortage.read", "shortage.create"]));
    expect(result.routes).toBe(false);
    expect(result.zones).toBe(false);
    expect(result.shortages).toBe(true);
    expect(result.shortageEdit).toBe(false);
  });
});

describe("Dispatch D09 late-response fence", () => {
  it("rejects a late successful response when a newer refresh replaced it", () => {
    const fence = createDispatchReadFence();
    const first = fence.start(() => true);
    const second = fence.start(() => true);
    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
  });

  it("rejects responses after 403 revocation even when a transport ignores abort", () => {
    const fence = createDispatchReadFence();
    const request = fence.start(() => true);
    fence.revoke();
    expect(request.isCurrent()).toBe(false);
    expect(request.signal.aborted).toBe(true);
  });

  it("rejects a response if principal/company/session changes before it resolves", () => {
    const fence = createDispatchReadFence();
    let current = true;
    const request = fence.start(() => current);
    current = false;
    expect(request.isCurrent()).toBe(false);
  });
});

describe("Dispatch D09 scoped HTTP refresh", () => {
  it("requests only existing effective grants, never a denied shortage endpoint", async () => {
    const fetch = vi.fn(async (path: string) => path);
    const onData = vi.fn();
    await loadDispatchRead({
      fetch, grants: dispatchPrivileges(grants([], ["dispatch.read"])),
      signal: new AbortController().signal, isCurrent: () => true,
      onData, onError: vi.fn(),
    });
    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      "/dispatch/init", "/dispatch/shops", "/dispatch/active_routes",
    ]);
    expect(onData).toHaveBeenCalledWith({
      init: "/dispatch/init", shops: "/dispatch/shops",
      routes: "/dispatch/active_routes", shortages: null,
    });
  });

  it("allows an independent shortage reader without implicitly fetching Shops or Zones", async () => {
    const fetch = vi.fn(async (path: string) => path);
    await loadDispatchRead({
      fetch, grants: dispatchPrivileges(grants(["shortage.read"])),
      signal: new AbortController().signal, isCurrent: () => true,
      onData: vi.fn(), onError: vi.fn(),
    });
    expect(fetch.mock.calls.map(([path]) => path)).toEqual(["/dispatch/shortages"]);
  });

  it("does not admit old rows if a 403 revokes access while an HTTP read completes late", async () => {
    let finish!: (rows: unknown) => void;
    const pending = new Promise<unknown>(resolve => { finish = resolve; });
    const onData = vi.fn(), onError = vi.fn();
    const fence = createDispatchReadFence();
    const request = fence.start(() => true);
    const loading = loadDispatchRead({
      fetch: () => pending, grants: dispatchPrivileges(grants([], ["dispatch.read"])),
      signal: request.signal, isCurrent: request.isCurrent,
      onData, onError,
    });
    fence.revoke();
    finish([{ name: "PRIVATE SHOP", initialDebt: 200 }]);
    await loading;
    expect(onData).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("fails the entire refresh when the backend denies one HTTP request", async () => {
    const onData = vi.fn(), onError = vi.fn();
    const denied = Object.assign(new Error("Forbidden"), { status: 403 });
    await loadDispatchRead({
      fetch: path => path === "/dispatch/shops" ? Promise.reject(denied) : Promise.resolve([]),
      grants: dispatchPrivileges(grants([], ["dispatch.read"])),
      signal: new AbortController().signal, isCurrent: () => true,
      onData, onError,
    });
    expect(onData).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(denied);
  });
});


describe("D15 #925 progressive signed Dispatch reads — no slow Shops barrier", () => {
  const privileges = dispatchPrivileges(grants(["shortage.read"], ["dispatch.read"]));
  it("Routes paints after its own genuine signed result without issuing Shops", async () => {
    let releaseInit!: (value: unknown) => void;
    const slowInit = new Promise<unknown>(resolve => { releaseInit = resolve; });
    const seen: string[] = [], parts: string[] = [];
    const complete = vi.fn(), onError = vi.fn();
    const loading = loadDispatchRead({
      tab: "routes", grants: privileges,
      fetch: async path => {
        seen.push(path);
        if (path === "/dispatch/init") return slowInit;
        return path === "/dispatch/active_routes" ? [{ id: "47" }] : [];
      },
      signal: new AbortController().signal, isCurrent: () => true,
      onData: vi.fn(), onPart: kind => parts.push(kind), onReady: complete, onError,
    });
    await vi.waitFor(() => expect(complete).toHaveBeenCalledOnce());
    expect(parts).toContain("routes");
    expect(parts).not.toContain("init");
    expect(seen).toEqual(["/dispatch/init", "/dispatch/active_routes", "/dispatch/shortages"]);
    expect(seen).not.toContain("/dispatch/shops");
    releaseInit({ zones: [], drivers: [], vehicles: [], warehouses: [] });
    await loading;
    expect(onError).not.toHaveBeenCalled();
  });

  it("Zones paints signed init first while genuine Shops GET remains unresolved", async () => {
    let releaseShops!: (value: unknown) => void;
    const slowShops = new Promise<unknown>(resolve => { releaseShops = resolve; });
    const stages: string[] = [], complete = vi.fn();
    const loading = loadDispatchRead({
      tab: "zones", grants: privileges,
      fetch: path => path === "/dispatch/shops"
        ? slowShops : Promise.resolve(path === "/dispatch/init" ? { zones: [{ id: "7" }] } : []),
      signal: new AbortController().signal, isCurrent: () => true,
      onData: vi.fn(), onPart: kind => stages.push(kind), onReady: complete, onError: vi.fn(),
    });
    await vi.waitFor(() => expect(stages).toContain("init"));
    expect(stages).not.toContain("shops");
    expect(complete).not.toHaveBeenCalled();
    releaseShops([{ id: "2", zoneId: "7" }]);
    await loading;
    await vi.waitFor(() => expect(complete).toHaveBeenCalledOnce());
    expect(stages).toContain("shops");
  });

  it("Launch shows init separately while fetching required live zone Shops for POST validation", async () => {
    const seen: string[] = [];
    await loadDispatchRead({
      tab: "launch", grants: privileges,
      fetch: async path => { seen.push(path); return []; },
      signal: new AbortController().signal, isCurrent: () => true,
      onData: vi.fn(), onPart: vi.fn(), onReady: vi.fn(), onError: vi.fn(),
    });
    expect(seen).toContain("/dispatch/init");
    expect(seen).toContain("/dispatch/shops");
    expect(seen).not.toContain("/dispatch/active_routes");
  });

  it("a delayed 403 sibling revokes a previously admitted Routes tab; stale results never republish", async () => {
    let failInit!: (error: unknown) => void;
    const slowInit = new Promise<unknown>((_, reject) => { failInit = reject; });
    const fence = createDispatchReadFence();
    const admission = fence.start(() => true);
    const stages: string[] = [], onReady = vi.fn();
    const onError = vi.fn(() => fence.revoke());
    const loading = loadDispatchRead({
      tab: "routes", grants: privileges,
      fetch: path => path === "/dispatch/init" ? slowInit
        : Promise.resolve(path === "/dispatch/active_routes" ? [{ id: "47" }] : []),
      signal: admission.signal, isCurrent: admission.isCurrent,
      onData: vi.fn(), onPart: kind => stages.push(kind), onReady, onError,
    });
    await vi.waitFor(() => expect(onReady).toHaveBeenCalledOnce());
    failInit(Object.assign(new Error("revoked"), { status: 403 }));
    await loading;
    expect(onError).toHaveBeenCalledOnce();
    expect(admission.isCurrent()).toBe(false);
    expect(stages).not.toContain("init");
  });

  it("revoking a pending actor prevents both publication and readiness", async () => {
    let release!: (rows: unknown) => void;
    const deferred = new Promise<unknown>(resolve => { release = resolve; });
    const fence = createDispatchReadFence();
    const admission = fence.start(() => true);
    const onPart = vi.fn(), onReady = vi.fn();
    const loading = loadDispatchRead({
      tab: "routes", grants: dispatchPrivileges(grants([], ["dispatch.read"])),
      fetch: () => deferred,
      signal: admission.signal, isCurrent: admission.isCurrent,
      onData: vi.fn(), onPart, onReady, onError: vi.fn(),
    });
    fence.revoke();
    release([{ id: "PRIVATE-COMPANY-A" }]);
    await loading;
    expect(onPart).not.toHaveBeenCalled();
    expect(onReady).not.toHaveBeenCalled();
  });
});
