import { webcrypto } from "node:crypto";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { captureDashboardSession, beginDashboardSession } from "@/lib/authStorage";
import { readDurableCommand } from "@/lib/durableOperations";
import {
  routeLaunchIntent, routeLaunchReadback, routeLaunchScopeKey, routeLaunchText,
  type RouteLaunchActor, type RouteLaunchIntent,
} from "@/features/dispatch/routeLaunch/contract";
import {
  createRouteLaunchRecovery, useRouteLaunchRecovery,
} from "@/features/dispatch/routeLaunch/useRouteLaunchRecovery";

const actor: RouteLaunchActor = {
  actorScope: "1:11:110", warehouseId: 20, vehicleId: 31,
};
const draft = (amount = "5") => routeLaunchIntent({
  zone_id: "7", driver_id: "9", vehicle_id: "31", source_location_id: 20,
  inventory_base: { "44": amount },
  expected_inventory_base: { "44": "10" },
});
const DENIED = (status: number) => Object.assign(new Error("private error"), { status });
type Recorded = RouteLaunchIntent & { request_id: string };
const committed = (requestId: string, routeId = 300) => ({
  state: "COMMITTED" as const, request_id: requestId, route_id: routeId,
  message: "تم إطلاق خط السير بنجاح",
  commercial_context: {
    commercial_context_id: 22, price_publication_revision: 2,
    tax_ruleset_version: 3, rounding_policy_version: 1,
  },
});

const held = new Set<string>();
const locks = {
  request: async <T,>(key: string, _opt: unknown, fn: (lock: object | null) => Promise<T>): Promise<T> => {
    if (held.has(key)) return fn(null);
    held.add(key);
    try { return await fn({ name: key }); }
    finally { held.delete(key); }
  },
};
const record = async () => readDurableCommand<RouteLaunchIntent>(routeLaunchScopeKey(actor));
const controller = (fetch: (path: string, opts?: RequestInit) => Promise<unknown>,
  access = { current: true, authorized: true }) => createRouteLaunchRecovery({
    actor, fetch, current: () => access.current, authorized: () => access.authorized,
  });

function server() {
  const records = new Map<string, { body: Recorded; response: ReturnType<typeof committed> }>();
  const posts: Recorded[] = [];
  let loss: "after" | "before" | null = null;
  let deny: number | null = null;
  let wrongReceipt = false;
  let getCalls = 0;
  const fetch = vi.fn(async (path: string, options?: RequestInit): Promise<unknown> => {
    if (deny !== null) throw DENIED(deny);
    if (path.startsWith("/dispatch/route/create-operations/")) {
      getCalls++;
      const id = path.split("/").at(-1)!;
      const found = records.get(id);
      if (!found) return { request_id: id, state: "UNKNOWN" };
      return { request_id: id, state: "COMMITTED", response:
        wrongReceipt ? committed("22222222-2222-4222-8222-222222222222") : found.response };
    }
    expect(path).toBe("/dispatch/route");
    expect(options?.method).toBe("POST");
    const body = JSON.parse(String(options?.body)) as Recorded;
    posts.push(body);
    if (loss === "before") { loss = null; throw new TypeError("offline before the server"); }
    const previous = records.get(body.request_id);
    if (previous) expect(body).toEqual(previous.body);
    else records.set(body.request_id, { body, response: committed(body.request_id) });
    if (loss === "after") { loss = null; throw new TypeError("original 201 lost"); }
    return records.get(body.request_id)!.response;
  });
  return {
    fetch, posts, records, getGets: () => getCalls,
    lose: (stage: "after" | "before") => { loss = stage; },
    deny: (code: number | null) => { deny = code; },
    corrupt: () => { wrongReceipt = true; },
  };
}

beforeEach(() => {
  localStorage.clear();
  held.clear();
  vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(navigator, "locks", { configurable: true, value: locks });
});
afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
});

describe("D07 original route launch command / fail-closed recovery", () => {
  it("survives a genuine lost 201, verifies original GET and fresh login without any duplicate POST", async () => {
    const api = server();
    api.lose("after");
    const first = controller(api.fetch);
    const answer = await first.launch(draft());
    expect(answer.kind).toBe("committed");
    expect(api.posts).toHaveLength(1);
    expect(api.getGets()).toBe(1);
    const saved = await record();
    expect(saved?.requestId).toBe(api.posts[0].request_id);
    expect(saved?.payload).toEqual(draft());
    expect(first.acknowledge("00000000-0000-4000-8000-000000000001")).toBe(false);
    first.dispose();

    // The browser and login generation restart; no server-side ephemeral state.
    const next = controller(api.fetch);
    const recovered = await next.recover();
    expect(recovered.kind).toBe("committed");
    if (recovered.kind !== "committed") throw new Error("No verified receipt");
    expect(recovered.receipt.route_id).toBe(300);
    expect(api.posts).toHaveLength(1);
    expect(next.acknowledge(recovered.requestId)).toBe(true);
    expect(await record()).toBeNull();
  });

  it("never creates a different UUID for UNKNOWN; only explicit retry can POST exact original payload", async () => {
    const api = server();
    api.lose("before");
    const command = controller(api.fetch);
    const unknown = await command.launch(draft());
    expect(unknown.kind).toBe("unknown");
    const saved = await record();
    expect(saved?.requestId).toBe(api.posts[0].request_id);
    expect(api.records.size).toBe(0);
    const noOp = await command.launch(draft());
    expect(noOp.kind).toBe("unknown");
    expect(api.posts).toHaveLength(1); // repeated button does GET only
    command.dispose();

    const rebooted = controller(api.fetch);
    const committed = await rebooted.retryOriginal();
    expect(committed.kind).toBe("committed");
    expect(api.posts).toHaveLength(2);
    expect(api.posts[1]).toEqual(api.posts[0]); // same complete body + UUID
    expect(api.records.size).toBe(1);
    expect(await rebooted.readPending()).toEqual(saved);
  });

  it("blocks changed payload, cross-company/actor or warehouse attempts, and malformed server success", async () => {
    const api = server();
    api.lose("before");
    const command = controller(api.fetch);
    await command.launch(draft());
    expect((await command.launch(draft("6"))).kind).toBe("conflict");
    expect(api.posts).toHaveLength(1);
    expect((await createRouteLaunchRecovery({
      actor: { ...actor, actorScope: "2:11:110" },
      current: () => true, authorized: () => true, fetch: api.fetch,
    }).recover()).kind).toBe("idle");
    expect((await createRouteLaunchRecovery({
      actor: { ...actor, warehouseId: 21 },
      current: () => true, authorized: () => true, fetch: api.fetch,
    }).recover()).kind).toBe("idle");
    expect((await command.launch({ ...draft(), vehicle_id: 32 })).kind).toBe("conflict");
    api.corrupt();
    const tried = await command.retryOriginal();
    expect(tried.kind).toBe("unknown");
    expect(await record()).not.toBeNull();
    expect(routeLaunchReadback({
      request_id: api.posts[0].request_id, state: "COMMITTED",
      response: committed("ffffffff-ffff-4fff-8fff-ffffffffffff"),
    }, api.posts[0].request_id)).toBeNull();
  });

  it("401/403 revoke and late old response are never displayed, posted again or acknowledged", async () => {
    const api = server();
    api.lose("before");
    const access = { current: true, authorized: true };
    const old = controller(api.fetch, access);
    expect((await old.launch(draft())).kind).toBe("unknown");
    api.deny(403);
    expect((await old.recover()).kind).toBe("blocked");
    api.deny(null);
    expect((await old.retryOriginal()).kind).toBe("blocked");
    expect(api.posts).toHaveLength(1);
    expect(await record()).not.toBeNull();

    // Simulate logout / account change while original GET is suspended.
    let release!: (result: unknown) => void;
    const deferred = vi.fn((_path: string) => new Promise<unknown>(resolve => { release = resolve; }));
    const fresh = controller(deferred, access);
    const read = fresh.recover();
    await vi.waitFor(() => expect(deferred).toHaveBeenCalledTimes(1));
    access.current = false;
    fresh.dispose();
    release({ request_id: (await record())!.requestId, state: "COMMITTED",
      response: committed((await record())!.requestId) });
    expect((await read).kind).toBe("stale");
    expect(api.posts).toHaveLength(1);
  });

  it("refuses unpersistable, corrupt or unlocked attempts and translates AR/EN uncertainty", async () => {
    const api = server();
    localStorage.setItem(routeLaunchScopeKey(actor), "{corrupt");
    expect((await controller(api.fetch).launch(draft())).kind).toBe("blocked");
    expect(api.posts).toHaveLength(0);
    localStorage.clear();
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    expect((await controller(api.fetch).launch(draft())).kind).toBe("busy");
    expect(api.posts).toHaveLength(0);
    expect(routeLaunchText("ar", "unknown")).toContain("الطلب الأصلي");
    expect(routeLaunchText("en", "unknown")).toContain("original request");
    expect(() => routeLaunchIntent({ ...draft(), inventory_base: { "44": "-1" } })).toThrow();
  });

  it("mountable React adapter restores same-user state and prevents success callbacks on denied access", async () => {
    localStorage.setItem("admin_token", "not-a-real-token-for-ui-test");
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "11");
    localStorage.setItem("backoffice_user_id", "110");
    beginDashboardSession();
    const session = captureDashboardSession();
    const api = server();
    api.lose("before");
    const notifications = vi.fn();
    const hook = renderHook(({ allowed }) => useRouteLaunchRecovery({
      actor, session, authorized: allowed, language: "ar",
      fetch: api.fetch, onCommitted: notifications,
    }), { initialProps: { allowed: true } });
    await waitFor(() => expect(hook.result.current.busy).toBe(false));
    await act(async () => {
      expect((await hook.result.current.launch(draft())).kind).toBe("unknown");
    });
    expect(api.posts).toHaveLength(1);
    expect(notifications).not.toHaveBeenCalled();
    hook.rerender({ allowed: false });
    await waitFor(() => expect(hook.result.current.result.kind).toBe("blocked"));
    expect((await hook.result.current.retryOriginal()).kind).toBe("blocked");
    expect(api.posts).toHaveLength(1);
    hook.unmount();
    // The durable command is deliberately not cleared by revoked UI state.
    expect(await record()).not.toBeNull();
  });
});
