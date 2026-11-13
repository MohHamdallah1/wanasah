import { webcrypto } from "node:crypto";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import DispatchBoard from "@/pages/DispatchBoard";
import { setAppLanguage } from "@/i18n";
// D13 Shop children read tenant currency. This isolated Board test does not
// mount React Query, so supply the actual test tenant's verified currency.
vi.mock("@/features/tenantIdentity/useTenantIdentity", () => ({
  useTenantIdentity: () => ({ data: { company_id: 1, currency_code: "QAR" } }),
}));
import { PREFLIGHT_AREAS } from "@/features/dispatch/commercialPreflight/contract";
import { writeDispatchPreferences } from "@/features/dispatch/sessionScope";
import { captureDashboardSession, beginDashboardSession } from "@/lib/authStorage";
import { readDurableCommand } from "@/lib/durableOperations";
import {
  readRouteLaunchPendingOwner, routeLaunchIntent, routeLaunchReadback,
  routeLaunchPendingKey, routeLaunchScopeKey, routeLaunchText,
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

// Same real Board and D10 session/permission wiring as the accepted D10
// browser-focused test. Only transport and discovery are deterministic.
const board = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => board.fetch }));
const boardOwner = {
  company_id: 1, principal_id: 3, backoffice_user_id: 13,
  is_company_owner: true, location_id: null,
  permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  any_permissions: ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"],
  location_permissions: [],
};
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  isCompanyOwner: true, data: boardOwner, can: () => true,
  isFetching: false, isError: false, error: null, dataUpdatedAt: 100,
  refetch: async () => ({ data: boardOwner }),
}) }));
vi.mock("@/components/ui/custom-select", () => ({
  CustomSelect: ({ label, value, options, onChange }: {
    label: string; value: string; options: { id: string; label: string }[];
    onChange: (value: string) => void;
  }) => <select aria-label={label} value={value}
    onChange={event => onChange(event.target.value)}>
    <option value="" />{options.map(option =>
      <option key={option.id} value={option.id}>{option.label}</option>)}
  </select>,
}));

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
  cleanup();
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
    }).recover()).kind).toBe("conflict");
    expect((await command.launch({ ...draft(), vehicle_id: 32 })).kind).toBe("blocked");
    // Retry commits only the original UUID. A later forged GET cannot turn
    // an unrelated or altered response into verified business success.
    expect((await command.retryOriginal()).kind).toBe("committed");
    api.corrupt();
    const tried = await command.recover();
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
    await waitFor(() => expect(hook.result.current.restoring).toBe(false));
    await act(async () => {
      expect((await hook.result.current.launch(draft())).kind).toBe("unknown");
    });
    expect(api.posts).toHaveLength(1);
    expect(notifications).not.toHaveBeenCalled();
    hook.rerender({ allowed: false });
    await waitFor(() => expect(hook.result.current.result.kind).toBe("blocked"));
    expect((await hook.result.current.retryOriginal()).kind).toBe("blocked");
    expect(api.posts).toHaveLength(1);
    // The same canonical session cannot impersonate another company even if
    // its numeric Warehouse/Vehicle IDs happen to match.
    const spoof = renderHook(() => useRouteLaunchRecovery({
      actor: { ...actor, actorScope: "2:11:110" }, session,
      authorized: true, language: "en", fetch: api.fetch,
    }));
    expect(spoof.result.current.result.kind).toBe("blocked");
    expect((await spoof.result.current.launch(draft())).kind).toBe("blocked");
    expect(api.posts).toHaveLength(1);
    spoof.unmount();
    hook.unmount();
    // The durable command is deliberately not cleared by revoked UI state.
    expect(await record()).not.toBeNull();
  });
});


describe("D07 live DispatchBoard launch at 390px (D05/D09/D10 kept)", () => {
  const unit = {
    base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH",
    quantity_scale: 0, quantity_step: "1",
    display_uom_name: "PACK", display_factor_to_base: "8",
  };
  const custody = [{ ...unit, product_id: "44", product_name: "Chips",
    current_base_quantity: "25", current_quantity: 3 }];
  const page = { items: [{ id: "44", name: "Chips",
    load: { ...unit, product_id: "44", product_name: "Chips",
      current_base_quantity: "0", reserved_base_quantity: "0", pending_base_quantity: "0" } }],
    next_cursor: null, has_more: false };

  it.each([
    ["ar", "التحقق من الإطلاق"],
    ["en", "Retry original request"],
  ] as const)("%s: physical launch loses 201, visible original UUID verifies after reentry with one POST", async (language, verifyLabel) => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    vi.stubGlobal("WebSocket", class {
      static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
      readyState = 0;
      send() {}
      close() { this.readyState = 3; }
    });
    localStorage.setItem("admin_token", "synthetic-board-integration-only");
    localStorage.setItem("company_id", "1");
    localStorage.setItem("principal_id", "3");
    localStorage.setItem("backoffice_user_id", "13");
    writeDispatchPreferences("1:3:13", {
      activeTab: "launch", zoneForShops: "", launchZone: "7",
      driver: "9", vehicle: "31", sourceWarehouse: "20",
    });
    await setAppLanguage(language);
    board.fetch.mockReset();
    let original: ReturnType<typeof committed> | null = null;
    const posts: Recorded[] = [];
    let lookups = 0;
    board.fetch.mockImplementation(async (path: string, opts?: RequestInit): Promise<unknown> => {
      // Signed read-only availability must be explicitly provided by this
      // authorized owner fixture: never bypass the fail-closed production read.
      if (path.startsWith("/dispatch/launch/resource-availability")) return {
        advisory: true,
        zones: [{ id: "7", label: "Zone seven", available: true, code: "AVAILABLE" }],
        drivers: [{ id: "9", label: "Driver", available: true, code: "AVAILABLE" }],
        vehicles: [{ id: "31", label: "Vehicle", available: true, code: "AVAILABLE" }],
        warehouses: [{ id: "20", label: "Warehouse", available: true, code: "AVAILABLE" }],
      };
      if (path === "/dispatch/init") return {
        zones: [{ id: "7", name: "Zone seven", shopsCount: 1 }],
        drivers: [{ id: "9", name: "Driver" }],
        vehicles: [{ id: "31", label: "Vehicle", can_execute: true }],
        warehouses: [{ id: "20", label: "Warehouse", can_execute: true }],
      };
      if (path === "/dispatch/shops") return [{
        id: "77", zoneId: "7", name: "Shop", archived: false,
        initialDebt: "0", maxDebtLimit: "0",
      }];
      if (path === "/dispatch/active_routes" || path === "/dispatch/shortages") return [];
      if (path.startsWith("/dispatch/inventory/")) return custody;
      if (path.startsWith("/dispatch/products?")) return page;
      if (path.startsWith("/warehouse/status")) return { is_locked: false };
      if (path.startsWith("/dispatch/route/commercial-preflight?")) return {
        ready: true, advisory: true, currency_code: "QAR",
        checks: Object.fromEntries(PREFLIGHT_AREAS.map(area =>
          [area, { ready: true, code: "READY", context: {} }])),
      };
      if (path === "/dispatch/route") {
        const payload = JSON.parse(String(opts?.body)) as Recorded;
        posts.push(payload);
        if (!original) {
          original = committed(payload.request_id, 901);
          throw new TypeError("A real HTTP 201 response disappears after DB commit");
        }
        expect(payload.request_id).toBe(original.request_id);
        return original;
      }
      if (path.startsWith("/dispatch/route/create-operations/")) {
        const requestId = path.split("/").at(-1)!;
        lookups++;
        // AR uses verified GET. EN explicitly retries when two GETs remain
        // UNKNOWN, with the same canonical UUID and original body.
        if (lookups === 1 || (language === "en" && lookups === 2))
          return { request_id: requestId, state: "UNKNOWN" };
        return { request_id: requestId, state: "COMMITTED", response: original };
      }
      return [];
    });

    render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
    await screen.findByText("Chips");
    const target = await screen.findByRole("textbox", { name: /Chips/ });
    await waitFor(() => expect(target).not.toBeDisabled());
    fireEvent.change(target, { target: { value: "5" } });
    const launch = screen.getByRole("button", { name: language === "ar" ? "اعتماد وإطلاق خط السير" : "Confirm and launch route" });
    await waitFor(() => expect(launch).not.toBeDisabled());
    fireEvent.click(launch);
    await waitFor(() => expect(posts).toHaveLength(1));
    await screen.findByTestId("d07-route-recovery");
    await waitFor(() => expect(screen.getByRole("button", { name: verifyLabel })).not.toBeDisabled());
    expect(launch).toBeDisabled();
    expect(posts[0].request_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(posts[0]).toMatchObject({
      zone_id: 7, driver_id: 9, vehicle_id: 31, source_location_id: 20,
      inventory_base: { "44": "5" }, expected_inventory_base: { "44": "25" },
    });
    const pointer = readRouteLaunchPendingOwner("1:3:13");
    expect(pointer).toMatchObject({ requestId: posts[0].request_id, warehouseId: 20, vehicleId: 31 });
    fireEvent.click(screen.getByRole("button", { name: verifyLabel }));
    await waitFor(() => expect(localStorage.getItem(routeLaunchPendingKey("1:3:13"))).toBeNull());
    expect(posts).toHaveLength(language === "en" ? 2 : 1);
    if (language === "en") expect(posts[1]).toEqual(posts[0]);
    expect(lookups).toBe(2);
    expect(screen.queryByTestId("d07-route-recovery")).not.toBeInTheDocument();
    expect(launch).toBeDisabled(); // D10 form selection cleared on verified original
  });
});
