import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";

const API = import.meta.env.VITE_API_URL;
if (API !== "http://127.0.0.1:4174" || process.env.WANASAH_INFLIGHT_AUTH_GATE !== "1") {
  throw new Error("This real-HTTP evidence requires the isolated PG16 workflow");
}
const fixture = JSON.parse(readFileSync(process.env.WANASAH_OPERATIONAL_BROWSER_STATE!, "utf8")) as {
  companyId: number; warehouse: number; mainId: number; firstBatch: number;
  credentials: Record<string, { code: string; username: string; password: string }>;
};
type Session = {
  token: string; refresh_token: string; company_id: number;
  principal_id: number; backoffice_user_id: number;
};
const wire = globalThis.fetch.bind(globalThis);
const originalAny = Object.getOwnPropertyDescriptor(AbortSignal, "any");
const evidence: Record<string, unknown>[] = [];
const output = resolve("node_modules/.cache/live-stock-inflight");
mkdirSync(output, { recursive: true });
const persist = () => writeFileSync(resolve(output, "http-evidence.json"), JSON.stringify(evidence, null, 2));
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
};
const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;
async function login(actor: string): Promise<Session> {
  const c = fixture.credentials[actor];
  const res = await wire(API + "/login", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company_code: c.code, username: c.username, password: c.password }),
  });
  expect(res.status, "real canonical login status").toBe(200);
  const data = await res.json() as Session;
  expect(typeof data.token).toBe("string");
  expect(typeof data.refresh_token).toBe("string");
  for (const id of [data.company_id, data.principal_id, data.backoffice_user_id]) {
    expect(Number.isSafeInteger(id) && id > 0).toBe(true);
  }
  return data;
}
function install(session: Session) {
  localStorage.setItem("admin_token", session.token);
  localStorage.setItem("refresh_token", session.refresh_token);
  localStorage.setItem("company_id", String(session.company_id));
  localStorage.setItem("principal_id", String(session.principal_id));
  localStorage.setItem("backoffice_user_id", String(session.backoffice_user_id));
}
const headers = (token: string) => ({ Authorization: "Bearer " + token });
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); localStorage.clear(); persist();
  if (originalAny) Object.defineProperty(AbortSignal, "any", originalAny);
  else Reflect.deleteProperty(AbortSignal, "any");
});

it("real same-bearer warehouse revocation denies all four readers after previously authorized snapshots", async () => {
  const reader = await login("reader");
  const paths = [
    "/warehouse/inventory/cursor?location_id=" + fixture.warehouse + "&limit=50",
    "/warehouse/inventory/summary?location_id=" + fixture.warehouse,
    "/warehouse/inventory/" + fixture.mainId + "/batches?location_id=" + fixture.warehouse,
    "/warehouse/inventory/" + fixture.mainId + "/batches/" + fixture.firstBatch + "/source?location_id=" + fixture.warehouse,
  ];
  const snapshots = [];
  for (const path of paths) {
    const res = await wire(API + path, { headers: headers(reader.token) });
    expect(res.status).toBe(200);
    expect(Boolean(res.headers.get("x-request-id"))).toBe(true);
    snapshots.push(await res.json());
  }
  const page = snapshots[0] as { items: Array<Record<string, unknown>> };
  expect(page.items.find(row => row.id === fixture.mainId)).toMatchObject({
    on_hand_quantity: "1000", total_quantity: "1000", total_quantity_scope: "WAREHOUSE_PHYSICAL",
    vehicle_quantity: null, vehicle_quantity_scope: "NO_ACCESS",
  });
  expect(snapshots[1]).toEqual({ stock_total: 109, alert_count: 1 });
  const result = execFileSync(process.env.PYTHON || "python", [
    resolve("../wa_backend/tests/live_stock_operational_browser_support.py"), "revoke",
  ], { encoding: "utf8", env: process.env });
  expect(result).toContain("OPERATIONAL_COMMAND PASS revoke");
  const statuses = [];
  for (const path of paths) {
    const res = await wire(API + path, { headers: headers(reader.token) });
    statuses.push(res.status);
    expect(res.status).toBe(403);
    expect(Boolean(res.headers.get("x-request-id"))).toBe(true);
    expect(await res.json()).not.toHaveProperty("items");
  }
  // The held snapshots predate revocation; they cannot establish new admission.
  evidence.push({ case: "same-token-revocation", authorizedBefore: [200, 200, 200, 200],
    after: statuses, oldSnapshotWarehouse: "1000", vehicleScope: "NO_ACCESS", vehicle: null });
  persist();
});

it("an aborted old inventory refresh must not overwrite a genuinely logged-in different company's session", async () => {
  const old = await login("owner");
  install(old);
  // A real server401 drives the production hook into its genuine refresh flow.
  localStorage.setItem("admin_token", "invalid-expired-access-for-disposable-test");
  const captured = deferred<Response>(), release = deferred<void>();
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await wire(input, init);
    if (new URL(String(input)).pathname === "/refresh") {
      captured.resolve(response);
      await release.promise;
    }
    return response;
  });
  // jsdom lacks this standard API; production Chromium supplies it natively.
  // This shim changes cancellation composition only, never HTTP/auth responses.
  if (typeof AbortSignal.any !== "function") {
    Object.defineProperty(AbortSignal, "any", { configurable: true, value: (signals: AbortSignal[]) => {
      const combined = new AbortController();
      const listeners = new Map<AbortSignal, () => void>();
      const cancel = (signal: AbortSignal) => {
        combined.abort(signal.reason);
        for (const [source, listener] of listeners) source.removeEventListener("abort", listener);
      };
      for (const signal of signals) {
        if (signal.aborted) { cancel(signal); break; }
        const listener = () => cancel(signal);
        listeners.set(signal, listener);
        signal.addEventListener("abort", listener, { once: true });
      }
      return combined.signal;
    } });
  }
  const probe = new AbortController(), combinedProbe = AbortSignal.any([probe.signal]);
  probe.abort();
  expect(combinedProbe.aborted, "test DOM must propagate real cancellation").toBe(true);
  const controller = new AbortController();
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pending = result.current("/warehouse/inventory/cursor?location_id=" + fixture.warehouse,
    { signal: controller.signal }).then(
      () => ({ ok: true, name: "", message: "" }),
      (error: unknown) => ({ ok: false, name: error instanceof Error ? error.name : "Unknown",
        message: error instanceof Error ? error.message : "non-Error rejection" }),
    );
  try {
  const stage = await Promise.race([
    captured.promise.then(response => ({ kind: "held" as const, response })),
    pending.then(outcome => ({ kind: "ended" as const, outcome })),
  ]);
  if (stage.kind === "ended") throw new Error("Reader ended before refresh capture: " + JSON.stringify(stage.outcome));
  const held = stage.response;
  expect(held.status, "real old-session refresh response").toBe(200);
  const current = await login("foreign");
  expect(current.company_id === old.company_id).toBe(false);
  expect(current.principal_id === old.principal_id).toBe(false);
  install(current);
  const verified = await wire(API + "/inventory/access/me", { headers: headers(current.token) });
  expect(verified.status).toBe(200);
  expect(await verified.json()).toMatchObject({
    company_id: current.company_id, principal_id: current.principal_id,
  });
  act(() => {
    controller.abort();
    window.dispatchEvent(new StorageEvent("storage", { key: "principal_id", newValue: String(current.principal_id) }));
  });
  await act(async () => { release.resolve(); await pending; });
  const accessPreserved = localStorage.getItem("admin_token") === current.token;
  const refreshPreserved = localStorage.getItem("refresh_token") === current.refresh_token;
  const credential = localStorage.getItem("admin_token") || "";
  const actual = await wire(API + "/inventory/access/me", { headers: headers(credential) });
  const identity = await actual.json() as { company_id?: number; principal_id?: number };
  evidence.push({ case: "old-refresh-after-company-principal-switch", oldCompany: old.company_id,
    expectedCompany: current.company_id, expectedPrincipal: current.principal_id,
    actualCompany: identity.company_id, actualPrincipal: identity.principal_id,
    accessPreserved, refreshPreserved, originalReaderAborted: controller.signal.aborted });
  persist();
  // Boolean assertions deliberately avoid putting bearer/refresh tokens in CI artifacts.
  expect(accessPreserved, "new session access credential must survive stale refresh").toBe(true);
  expect(refreshPreserved, "new session refresh credential must survive stale refresh").toBe(true);
  } finally {
    controller.abort();
    release.resolve();
    await pending;
  }
});
