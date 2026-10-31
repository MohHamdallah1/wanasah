import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, fireEvent, render, renderHook, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { beginDashboardSession } from "@/lib/authStorage";
import Login from "@/pages/Login";

const API = import.meta.env.VITE_API_URL;
if (API !== "http://127.0.0.1:4174" || process.env.WANASAH_INFLIGHT_AUTH_GATE !== "1") {
  throw new Error("This real-HTTP evidence requires the isolated PG16 workflow");
}
const fixture = JSON.parse(readFileSync(process.env.WANASAH_OPERATIONAL_BROWSER_STATE!, "utf8")) as {
  companyId: number; warehouse: number; foreignWarehouse: number; mainId: number; firstBatch: number;
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
  beginDashboardSession();
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

const safeRun = (fetcher: ReturnType<typeof useAuthFetch>, path: string) =>
  fetcher(path).then(value => ({ value, error: null }),
    (error: unknown) => ({ value: null, error: error as Error }));
const cursorA = () => "/warehouse/inventory/cursor?location_id=" + fixture.warehouse;
const cursorB = () => "/warehouse/inventory/cursor?location_id=" + fixture.foreignWarehouse;
async function verifyCurrent(session: Session) {
  expect(localStorage.getItem("admin_token") === session.token).toBe(true);
  expect(localStorage.getItem("refresh_token") === session.refresh_token).toBe(true);
  expect(localStorage.getItem("company_id")).toBe(String(session.company_id));
  expect(localStorage.getItem("principal_id")).toBe(String(session.principal_id));
  const res = await wire(API + "/inventory/access/me", { headers: headers(session.token) });
  expect(res.status).toBe(200);
  expect(await res.json()).toMatchObject({ company_id: session.company_id, principal_id: session.principal_id });
}

it("a genuinely rejected old refresh cannot log out a newer company's real session", async () => {
  const old = await login("owner");
  const logout = await wire(API + "/logout", { method: "POST",
    headers: { ...headers(old.token), "X-Refresh-Token": old.refresh_token } });
  expect(logout.status).toBe(200);
  install(old);
  localStorage.setItem("admin_token", "invalid-expired-access-for-disposable-test");
  const captured = deferred<Response>(), release = deferred<void>();
  let logoutCalls = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (new URL(String(input)).pathname === "/logout") logoutCalls++;
    const response = await wire(input, init);
    if (new URL(String(input)).pathname === "/refresh") {
      captured.resolve(response); await release.promise;
    }
    return response;
  });
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pending = safeRun(result.current, cursorA());
  try {
    expect((await captured.promise).status).toBe(401);
    const current = await login("foreign");
    install(current);
    release.resolve();
    expect((await pending).error?.name).toBe("AbortError");
    await verifyCurrent(current);
    expect(logoutCalls).toBe(0);
    evidence.push({ case: "real-stale-refresh-failure", oldRefreshStatus: 401,
      newCompany: current.company_id, loggedIn: true, staleLogoutCalls: logoutCalls });
  } finally { release.resolve(); await pending; }
});

it("real concurrent refreshes never share credentials or retries across companies", async () => {
  const a = await login("owner"); install(a);
  localStorage.setItem("admin_token", "invalid-a-for-disposable-test");
  const b = await login("foreign");
  const aHeld = deferred<Response>(), bHeld = deferred<Response>();
  const aRelease = deferred<void>(), bRelease = deferred<void>();
  let aRefreshes = 0, bRefreshes = 0;
  const retries: Array<{ company: string | null; status: number }> = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const res = await wire(input, init);
    if (url.pathname === "/refresh") {
      const refresh = JSON.parse(String(init?.body)).refresh_token;
      if (refresh === a.refresh_token) { aRefreshes++; aHeld.resolve(res); await aRelease.promise; }
      else if (refresh === b.refresh_token) { bRefreshes++; bHeld.resolve(res); await bRelease.promise; }
      else throw new Error("Unexpected real refresh lineage");
    } else if (url.pathname === "/warehouse/inventory/cursor" && res.ok) {
      retries.push({ company: localStorage.getItem("company_id"), status: res.status });
    }
    return res;
  });
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pa = safeRun(result.current, cursorA());
  let pb: ReturnType<typeof safeRun> | null = null;
  try {
    expect((await aHeld.promise).status).toBe(200);
    install(b); localStorage.setItem("admin_token", "invalid-b-for-disposable-test");
    pb = safeRun(result.current, cursorB());
    expect((await bHeld.promise).status).toBe(200);
    bRelease.resolve();
    const outcome = await pb;
    expect(outcome.error).toBeNull();
    expect(outcome.value).toHaveProperty("items");
    const bAccess = localStorage.getItem("admin_token")!;
    const bRefresh = localStorage.getItem("refresh_token")!;
    aRelease.resolve();
    expect((await pa).error?.name).toBe("AbortError");
    expect(localStorage.getItem("admin_token") === bAccess).toBe(true);
    expect(localStorage.getItem("refresh_token") === bRefresh).toBe(true);
    const verified = await wire(API + "/inventory/access/me", { headers: headers(bAccess) });
    expect(verified.status).toBe(200);
    expect(await verified.json()).toMatchObject({ company_id: b.company_id, principal_id: b.principal_id });
    expect([aRefreshes, bRefreshes]).toEqual([1, 1]);
    expect(retries).toEqual([{ company: String(b.company_id), status: 200 }]);
    evidence.push({ case: "real-cross-session-refresh-concurrency", refreshes: [aRefreshes, bRefreshes],
      successfulRetries: retries, newIdentityVerified: true });
  } finally { aRelease.resolve(); bRelease.resolve(); await pa; if (pb) await pb; }
});

it("real same-session concurrent401s rotate once and retain canonical identity", async () => {
  const session = await login("owner"); install(session);
  localStorage.setItem("admin_token", "invalid-a-for-disposable-test");
  const held = deferred<Response>(), release = deferred<void>(), both = deferred<void>();
  let refreshes = 0, initials = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await wire(input, init);
    const path = new URL(String(input)).pathname;
    if (path === "/refresh") { refreshes++; held.resolve(res); await release.promise; }
    if (path === "/warehouse/inventory/cursor" && res.status === 401 && ++initials === 2) both.resolve();
    return res;
  });
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const p1 = safeRun(result.current, cursorA()), p2 = safeRun(result.current, cursorA());
  try {
    await both.promise;
    expect((await held.promise).status).toBe(200);
    release.resolve();
    for (const outcome of await Promise.all([p1, p2])) {
      expect(outcome.error).toBeNull(); expect(outcome.value).toHaveProperty("items");
    }
    expect(refreshes).toBe(1);
    const rotated = { ...session, token: localStorage.getItem("admin_token")!,
      refresh_token: localStorage.getItem("refresh_token")! };
    expect(rotated.refresh_token === session.refresh_token).toBe(false);
    await verifyCurrent(rotated);
    evidence.push({ case: "real-same-session-rotation", refreshes, retries: 2, identityPreserved: true });
  } finally { release.resolve(); await Promise.all([p1, p2]); }
});

it("real company A bearer denies company B readers and mutation with unchanged inventory and cost", async () => {
  const a = await login("owner"), b = await login("foreign");
  const own = await wire(API + cursorB(), { headers: headers(b.token) });
  expect(own.status).toBe(200);
  const page = await own.json() as { items: Array<{ id: number; base_uom_id: number }> };
  expect(page.items.length).toBeGreaterThan(0);
  const product = page.items[0];
  const batchesPath = "/warehouse/inventory/" + product.id + "/batches?location_id=" + fixture.foreignWarehouse;
  const batchResponse = await wire(API + batchesPath, { headers: headers(b.token) });
  expect(batchResponse.status).toBe(200);
  const detail = await batchResponse.json() as { batches: Array<{ batch_id: number }> };
  expect(detail.batches.length).toBeGreaterThan(0);
  const batch = detail.batches[0].batch_id;
  const paths = [cursorB(), "/warehouse/inventory/summary?location_id=" + fixture.foreignWarehouse,
    batchesPath, "/warehouse/inventory/" + product.id + "/batches/" + batch + "/source?location_id=" + fixture.foreignWarehouse];
  const snapshot = () => JSON.parse(execFileSync(process.env.PYTHON || "python", [
    resolve("../wa_backend/tests/live_stock_inflight_security_probe.py"),
    String(a.company_id), String(b.company_id),
  ], { encoding: "utf8", env: process.env }));
  const before = snapshot();
  const denied = [];
  for (const path of paths) {
    const res = await wire(API + path, { headers: headers(a.token) });
    denied.push(res.status);
    expect([403, 404].includes(res.status)).toBe(true);
    expect(Boolean(res.headers.get("x-request-id"))).toBe(true);
    const body = await res.json();
    for (const field of ["items", "batches", "latest_purchase_cost", "total_quantity"]) expect(body).not.toHaveProperty(field);
  }
  const res = await wire(API + "/warehouse/inventory/status-change", {
    method: "POST", headers: { ...headers(a.token), "Content-Type": "application/json" },
    body: JSON.stringify({ request_id: crypto.randomUUID(), location_id: fixture.foreignWarehouse,
      product_variant_id: product.id, batch_id: batch, uom_id: product.base_uom_id,
      source_status: "AVAILABLE", destination_status: "BLOCKED", quantity: "1",
      reason: "Disposable cross-company authorization rejection" }),
  });
  expect([403, 404].includes(res.status)).toBe(true);
  expect(Boolean(res.headers.get("x-request-id"))).toBe(true);
  await res.json();
  const after = snapshot();
  expect(after).toEqual(before);
  evidence.push({ case: "real-cross-company-reads-and-mutation", readerStatuses: denied,
    mutationStatus: res.status, before, after, inventoryAndCostUnchanged: true });
});

it("an older real production Login response cannot overwrite a newer successful company login", async () => {
  localStorage.clear();
  const held = deferred<Response>(), release = deferred<void>();
  const a = fixture.credentials.owner;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await wire(input, init);
    if (new URL(String(input)).pathname === "/login" &&
        JSON.parse(String(init?.body)).company_code === a.code) {
      held.resolve(response); await release.promise;
    }
    return response;
  });
  const view = render(<Login />, { wrapper });
  const company = view.container.querySelector<HTMLInputElement>("#company-code")!;
  const user = view.container.querySelector<HTMLInputElement>("#username")!;
  const password = view.container.querySelector<HTMLInputElement>("#password")!;
  const submit = view.container.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  fireEvent.change(company, { target: { value: a.code } });
  fireEvent.change(user, { target: { value: a.username } });
  fireEvent.change(password, { target: { value: a.password } });
  fireEvent.submit(view.container.querySelector("form")!);
  try {
    expect((await held.promise).status).toBe(200);
    expect(submit.disabled).toBe(true);
    const b = await login("foreign"); install(b);
    release.resolve();
    await waitFor(() => expect(submit.disabled).toBe(false));
    await verifyCurrent(b);
    evidence.push({ case: "real-stale-production-login", newCompany: b.company_id,
      newPrincipal: b.principal_id, credentialsAndIdentityPreserved: true });
  } finally {
    release.resolve();
    await waitFor(() => expect(submit.disabled).toBe(false));
  }
});
