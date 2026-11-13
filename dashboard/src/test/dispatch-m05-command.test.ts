import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dispatchRouteLifecycle } from "@/features/dispatch/routeLifecycle/command";
import type { RouteLifecycleIntent } from "@/features/dispatch/routeLifecycle/contract";

const original: RouteLifecycleIntent = {
  action: "POSTPONE", expected_context_revision: 3,
  expected_period_id: 41, expected_vehicle_custody_revision: null,
  target_driver_id: null, target_vehicle_id: null,
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: async (_key: string, _options: unknown,
      callback: (lock: object) => Promise<unknown>) => callback({}) },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
});

describe("M05 exact original M02 lifecycle command", () => {
  it("retries lost HTTP success with identical UUID and exact locked epoch", async () => {
    const posted: Array<Record<string, unknown>> = [];
    let lose = true;
    const fetch = vi.fn(async (_path: string, init?: RequestInit) => {
      const payload = JSON.parse(String(init?.body)) as Record<string, unknown>;
      posted.push(payload);
      if (lose) {
        lose = false;
        throw new TypeError("server 200 lost");
      }
      return {
        state: "COMMITTED", request_id: payload.request_id,
        route_id: 17, action: "POSTPONE", status: "postponed",
        context_revision: 4, zone_reserved: true, live_assets_reserved: false,
      };
    });
    const context = { actorScope: "1:2:3", routeId: 17,
      fetch, authorized: () => true };
    const first = await dispatchRouteLifecycle({ ...context, intent: original });
    expect(first.kind).toBe("unknown");
    const retry = await dispatchRouteLifecycle(context);
    expect(retry.kind).toBe("committed");
    expect(posted).toHaveLength(2);
    expect(posted[0]).toEqual(posted[1]);
    expect(posted[0]).toMatchObject({
      action: "POSTPONE", expected_context_revision: 3, expected_period_id: 41,
    });
    expect(typeof posted[0].request_id).toBe("string");
    expect((posted[0].request_id as string).length).toBeGreaterThan(10);
  });

  it("blocks a changed intent while an original unknown request is durable", async () => {
    const fetch = vi.fn(async () => { throw new TypeError("connection lost"); });
    const context = { actorScope: "1:2:3", routeId: 17, fetch, authorized: () => true };
    expect((await dispatchRouteLifecycle({ ...context, intent: original })).kind).toBe("unknown");
    await expect(dispatchRouteLifecycle({
      ...context, intent: { ...original, expected_context_revision: 4 },
    })).rejects.toMatchObject({ code: "DURABLE_OPERATION_PENDING" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("never sends when permissions are revoked or Web Locks unavailable", async () => {
    const fetch = vi.fn(async () => ({}));
    expect((await dispatchRouteLifecycle({
      actorScope: "1:2:3", routeId: 17, intent: original, fetch,
      authorized: () => false,
    })).kind).toBe("denied");
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    expect((await dispatchRouteLifecycle({
      actorScope: "1:2:3", routeId: 17, intent: original, fetch,
      authorized: () => true,
    })).kind).toBe("busy");
    expect(fetch).not.toHaveBeenCalled();
  });
});
