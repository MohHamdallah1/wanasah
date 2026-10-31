import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import DashboardLayout from "@/components/operations/DashboardLayout";
import { TabTransfers } from "@/pages/inventory/TabTransfers";
import { beginDashboardSession, captureDashboardSession, clearLocalStoragePreservingLoginHintsAndPreferences, notifyDashboardSessionChange } from "@/lib/authStorage";

vi.mock("@/components/operations/OperationsSidebar", () => ({ OperationsSidebar: () => null }));
vi.mock("@/hooks/useNetworkStatus", () => ({ useNetworkStatus: () => true }));
vi.mock("sonner", () => ({ toast: {
  error: vi.fn(), success: vi.fn(), warning: vi.fn(), dismiss: vi.fn(),
} }));

const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "Content-Type": "application/json" },
});
function login(company = "1", principal = "11", marker = "a") {
  beginDashboardSession();
  localStorage.setItem("company_id", company);
  localStorage.setItem("principal_id", principal);
  localStorage.setItem("backoffice_user_id", principal + "0");
  localStorage.setItem("admin_token", marker + "-access");
  localStorage.setItem("refresh_token", marker + "-refresh");
}
const auth = (init?: RequestInit) => new Headers(init?.headers).get("Authorization");
const run = (fetcher: ReturnType<typeof useAuthFetch>, signal?: AbortSignal) =>
  fetcher("/protected", { signal }).then(
    value => ({ value, error: null }),
    (error: unknown) => ({ value: null, error: error as Error }),
  );
beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

for (const status of [200, 401, 403, 500]) {
  it("fences an old refresh status " + status + " after a new company/principal login", async () => {
    login();
    const held = deferred<Response>(), started = deferred<void>();
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      requests.push(url + " " + auth(init));
      if (url.endsWith("/refresh")) { started.resolve(); return held.promise; }
      if (url.endsWith("/logout")) return json({});
      return json({}, 401);
    }));
    const { result } = renderHook(() => useAuthFetch(), { wrapper });
    const pending = run(result.current);
    await started.promise;
    login("2", "22", "b");
    held.resolve(json({ token: "old-rotated", refresh_token: "old-rotated-refresh" }, status));
    const outcome = await pending;
    expect(outcome.error?.name).toBe("AbortError");
    expect(localStorage.getItem("admin_token") === "b-access").toBe(true);
    expect(localStorage.getItem("refresh_token") === "b-refresh").toBe(true);
    expect(localStorage.getItem("company_id")).toBe("2");
    expect(requests.filter(url => url.includes("/logout"))).toHaveLength(0);
    expect(requests.filter(url => url.includes("/protected"))).toHaveLength(1);
  });
}

it("never lets a late old initial401 use the new company's refresh credential", async () => {
  login();
  const held = deferred<Response>();
  const fetchMock = vi.fn(() => held.promise);
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pending = run(result.current);
  login("2", "22", "b");
  held.resolve(json({}, 401));
  expect((await pending).error?.name).toBe("AbortError");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem("admin_token")).toBe("b-access");
});

it("keeps concurrent different-session refreshes and retries separate", async () => {
  login();
  const a = deferred<Response>(), b = deferred<Response>();
  const aStarted = deferred<void>(), bStarted = deferred<void>();
  const seen: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/refresh")) {
      const token = JSON.parse(String(init?.body)).refresh_token;
      if (token === "a-refresh") { aStarted.resolve(); return a.promise; }
      if (token === "b-refresh") { bStarted.resolve(); return b.promise; }
      throw new Error("Unexpected refresh identity");
    }
    seen.push(auth(init) || "");
    return json({ company: "2" }, auth(init) === "Bearer b-new" ? 200 : 401);
  }));
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pa = run(result.current);
  await aStarted.promise;
  login("2", "22", "b");
  const pb = run(result.current);
  await bStarted.promise;
  b.resolve(json({ token: "b-new", refresh_token: "b-new-refresh" }));
  expect((await pb).value).toEqual({ company: "2" });
  a.resolve(json({ token: "a-new", refresh_token: "a-new-refresh" }));
  expect((await pa).error?.name).toBe("AbortError");
  expect(seen).toEqual(["Bearer a-access", "Bearer b-access", "Bearer b-new"]);
  expect(localStorage.getItem("admin_token")).toBe("b-new");
});

it("coalesces same-session401s and preserves legitimate token rotation", async () => {
  login();
  const held = deferred<Response>(), started = deferred<void>();
  let refreshes = 0, initial = 0;
  const both = deferred<void>();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/refresh")) { refreshes++; started.resolve(); return held.promise; }
    if (auth(init) === "Bearer a-access") { if (++initial === 2) both.resolve(); return json({}, 401); }
    expect(auth(init)).toBe("Bearer rotated");
    return json({ ok: true });
  }));
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const p1 = run(result.current), p2 = run(result.current);
  await both.promise; await started.promise;
  held.resolve(json({ token: "rotated", refresh_token: "rotated-refresh" }));
  expect((await p1).value).toEqual({ ok: true });
  expect((await p2).value).toEqual({ ok: true });
  expect(refreshes).toBe(1);
  expect(localStorage.getItem("refresh_token")).toBe("rotated-refresh");
});

it("does not resurrect credentials after explicit logout", async () => {
  login();
  const held = deferred<Response>(), started = deferred<void>();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/refresh")) { started.resolve(); return held.promise; }
    return json({}, 401);
  }));
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pending = run(result.current);
  await started.promise;
  clearLocalStoragePreservingLoginHintsAndPreferences();
  held.resolve(json({ token: "resurrected", refresh_token: "resurrected" }));
  expect((await pending).error?.name).toBe("AbortError");
  expect(localStorage.getItem("admin_token")).toBeNull();
  expect(localStorage.getItem("refresh_token")).toBeNull();
});

it("distinguishes same-principal re-login from same-session rotation", async () => {
  login();
  const held = deferred<Response>(), started = deferred<void>();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/refresh")) { started.resolve(); return held.promise; }
    return json({}, 401);
  }));
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  const pending = run(result.current);
  await started.promise;
  login("1", "11", "second-login");
  held.resolve(json({}, 401));
  expect((await pending).error?.name).toBe("AbortError");
  expect(localStorage.getItem("admin_token")).toBe("second-login-access");
});

for (const status of [200, 403]) {
  it("rejects a stale ordinary response/body without data admission or permission side effects " + status, async () => {
    login();
    const body = deferred<string>(), started = deferred<void>();
    vi.stubGlobal("fetch", vi.fn(async () => {
      const response = json({}, status);
      response.text = async () => { started.resolve(); return body.promise; };
      return response;
    }));
    const denied = vi.fn();
    window.addEventListener("inventory-permission-denied", denied);
    const { result } = renderHook(() => useAuthFetch(), { wrapper });
    const pending = run(result.current);
    await started.promise;
    login("2", "22", "b");
    body.resolve(JSON.stringify({ code: "ACCOUNT_DISABLED", items: ["old-company"] }));
    expect((await pending).error?.name).toBe("AbortError");
    expect(denied).not.toHaveBeenCalled();
    expect(localStorage.getItem("admin_token")).toBe("b-access");
    window.removeEventListener("inventory-permission-denied", denied);
  });
}

it("preserves current-session expiry logout", async () => {
  login();
  const fetchMock = vi.fn(async () => json({}, 401));
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useAuthFetch(), { wrapper });
  expect((await run(result.current)).error).toMatchObject({ status: 401 });
  expect(localStorage.getItem("admin_token")).toBeNull();
  expect(fetchMock.mock.calls.length).toBe(3);
});

it("an aborted sole refresh cannot write tokens, while another live waiter may rotate", async () => {
  // jsdom lacks AbortSignal.any; provide only the standard cancellation composition.
  const original = Object.getOwnPropertyDescriptor(AbortSignal, "any");
  if (typeof AbortSignal.any !== "function") Object.defineProperty(AbortSignal, "any", {
    configurable: true, value: (signals: AbortSignal[]) => {
      const c = new AbortController();
      for (const signal of signals) {
        if (signal.aborted) c.abort();
        else signal.addEventListener("abort", () => c.abort(), { once: true });
      }
      return c.signal;
    },
  });
  try {
    for (const liveWaiter of [false, true]) {
      login();
      const held = deferred<Response>(), started = deferred<void>(), secondSent = deferred<void>();
      let initial = 0;
      vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/refresh")) { started.resolve(); return held.promise; }
        if (auth(init) === "Bearer a-access") { if (++initial === 2) secondSent.resolve(); return json({}, 401); }
        return json({ ok: true });
      }));
      const { result, unmount } = renderHook(() => useAuthFetch(), { wrapper });
      const controller = new AbortController();
      const p1 = run(result.current, controller.signal);
      await started.promise;
      const p2 = liveWaiter ? run(result.current) : null;
      if (p2) { await secondSent.promise; await act(async () => {}); }
      controller.abort();
      held.resolve(json({ token: "rotated", refresh_token: "rotated-refresh" }));
      expect((await p1).error?.name).toBe("AbortError");
      if (p2) expect((await p2).value).toEqual({ ok: true });
      await act(async () => {});
      expect(localStorage.getItem("admin_token")).toBe(liveWaiter ? "rotated" : "a-access");
      unmount();
    }
  } finally {
    if (original) Object.defineProperty(AbortSignal, "any", original);
    else Reflect.deleteProperty(AbortSignal, "any");
  }
});

it("late explicit logout finalization cannot clear a newer company or same-principal login", () => {
  for (const samePrincipal of [false, true]) {
    login();
    const oldLogout = captureDashboardSession();
    login(samePrincipal ? "1" : "2", samePrincipal ? "11" : "22", "new");
    expect(clearLocalStoragePreservingLoginHintsAndPreferences(oldLogout)).toBe(false);
    expect(localStorage.getItem("admin_token")).toBe("new-access");
    expect(localStorage.getItem("refresh_token")).toBe("new-refresh");
    expect(clearLocalStoragePreservingLoginHintsAndPreferences(captureDashboardSession())).toBe(true);
    expect(localStorage.getItem("admin_token")).toBeNull();
  }
});


const accessPayload = (
  companyId: number,
  principalId: number,
  permissions = ["transfer.read", "transfer.send", "transfer.destination"],
) => ({
  company_id: companyId,
  principal_id: principalId,
  backoffice_user_id: principalId * 10,
  is_company_owner: true,
  location_id: null,
  permissions: [],
  any_permissions: permissions,
  location_permissions: [],
});

const transferRow = (companyId: number) => {
  const a = companyId === 1;
  return {
    id: a ? 1001 : 2001,
    reference_number: a ? "A-TRANSFER" : "B-TRANSFER",
    source_location_id: a ? 101 : 201,
    source_location_name: a ? "A Source" : "B Source",
    destination_location_id: a ? 102 : 202,
    destination_location_name: a ? "A Destination" : "B Destination",
    status: "IN_TRANSIT",
    transfer_purpose: "WAREHOUSE_BALANCING",
    dispatched_by: a ? 110 : 220,
    dispatched_by_name: a ? "A Operator" : "B Operator",
    received_by: null,
    received_by_name: null,
    cancelled_by: null,
    cancelled_by_name: null,
    line_count: 1,
    total_quantity: "8",
    notes: null,
    decision_reason: null,
    created_at: "2026-10-31T00:00:00Z",
    updated_at: "2026-10-31T00:00:00Z",
    accepted_at: null,
    rejected_at: null,
    cancelled_at: null,
    posted_at: null,
  };
};

const tenantIdentityPayload = (companyId: number) => ({
  company_id: companyId,
  company_name: companyId === 1 ? "Company A" : "Company B",
  company_code: companyId === 1 ? "A" : "B",
  currency_code: "JOD",
  timezone: "Asia/Amman",
  country_id: null,
  country_name: null,
  display_location: companyId === 1 ? "A Location" : "B Location",
});

const publishStorageLogin = (company: string, principal: string, marker: string) => {
  login(company, principal, marker);
  window.dispatchEvent(new StorageEvent("storage", {
    key: "wanasah:auth-session:generation",
    newValue: localStorage.getItem("wanasah:auth-session:generation"),
  }));
};

it("remounts A Transfers before fresh B authorization, ignores late A and preserves durable drafts", async () => {
  const q = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const warmWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={q}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>
  );
  const bAccessGate = deferred<void>();
  const bListGate = deferred<void>();
  const bListStarted = deferred<void>();
  const aLateListGate = deferred<void>();
  const aLateListStarted = deferred<void>();
  let aListReads = 0;

  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), "http://wanasah.test");
    const authorization = auth(init);
    const companyId =
      authorization === "Bearer a-access" ? 1 :
      authorization === "Bearer warm-b-access" || authorization === "Bearer b-access" ? 2 :
      0;

    if (url.pathname === "/inventory/access/me") {
      if (authorization === "Bearer b-access") {
        await bAccessGate.promise;
        return json(accessPayload(2, 22));
      }
      if (companyId) return json(accessPayload(companyId, companyId === 1 ? 11 : 22));
    }
    if (url.pathname === "/tenant/identity" && companyId) {
      return json(tenantIdentityPayload(companyId));
    }
    if (url.pathname === "/inventory/access/locations/capabilities" && companyId) {
      const ids = companyId === 1 ? [101, 102] : [201, 202];
      return json({ locations: {
        [ids[0]]: ["transfer.cancel"],
        [ids[1]]: ["transfer.receive", "transfer.reject"],
      } });
    }
    if (url.pathname === "/warehouse/unified/transfers" && companyId === 1) {
      aListReads += 1;
      if (aListReads > 1) {
        aLateListStarted.resolve();
        await aLateListGate.promise;
        return json({ items: [{ ...transferRow(1), source_location_name: "A LATE SECRET" }],
          next_cursor: null, has_more: false, total: 1 });
      }
      return json({ items: [transferRow(1)], next_cursor: null, has_more: false, total: 1 });
    }
    if (url.pathname === "/warehouse/unified/transfers" && companyId === 2) {
      bListStarted.resolve();
      await bListGate.promise;
      return json({ items: [transferRow(2)], next_cursor: null, has_more: false, total: 1 });
    }
    throw new Error(`Unexpected platform-boundary request: ${url.pathname} ${authorization}`);
  }));

  login("2", "22", "warm-b");
  const warm = renderHook(() => useInventoryAccess(), { wrapper: warmWrapper });
  await waitFor(() => expect(warm.result.current.data?.company_id).toBe(2));
  const warmedGeneration = captureDashboardSession().generation;
  warm.unmount();

  login("1", "11", "a");
  const durableKey = "wanasah:durable:v1:1:11:dispatch-adjust-base:9";
  const durableValue = JSON.stringify({ requestId: "keep-me", payload: { delta_base: "-5" } });
  localStorage.setItem(durableKey, durableValue);

  render(
    <QueryClientProvider client={q}>
      <MemoryRouter initialEntries={["/inventory"]}>
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/inventory" element={<TabTransfers onInventoryChanged={() => undefined} />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await waitFor(() => expect(screen.queryAllByText("A Source").length).toBeGreaterThan(0));
  await waitFor(() => {
    const receive = document.querySelector<HTMLButtonElement>('[data-cp13-transfer-decision="receive"]');
    expect(receive).not.toBeNull();
    expect(receive?.disabled).toBe(false);
  });
  const oldAction = document.querySelector<HTMLButtonElement>('[data-cp13-transfer-decision="receive"]')!;
  fireEvent.click(oldAction);
  const oldDialog = screen.getByRole("dialog");

  const refresh = document.querySelector<HTMLButtonElement>('[data-cp13-controls="transfer-list"] button[title]');
  expect(refresh).not.toBeNull();
  fireEvent.click(refresh!);
  await aLateListStarted.promise;

  act(() => publishStorageLogin("2", "22", "b"));
  expect(captureDashboardSession().generation).not.toBe(warmedGeneration);
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(screen.queryAllByText("A Destination")).toHaveLength(0);
  expect(oldAction).not.toBeInTheDocument();
  expect(oldDialog).not.toBeInTheDocument();
  expect(screen.queryAllByText("B Source")).toHaveLength(0);
  expect(localStorage.getItem(durableKey)).toBe(durableValue);

  await act(async () => bAccessGate.resolve());
  await bListStarted.promise;
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(screen.queryAllByText("B Source")).toHaveLength(0);

  await act(async () => aLateListGate.resolve());
  expect(document.body.textContent).not.toContain("A LATE SECRET");
  expect(screen.queryAllByText("A Source")).toHaveLength(0);

  await act(async () => bListGate.resolve());
  await waitFor(() => expect(screen.queryAllByText("B Source").length).toBeGreaterThan(0));
  expect(screen.queryAllByText("A Source")).toHaveLength(0);
  expect(document.body.textContent).not.toContain("A LATE SECRET");
  await waitFor(() => {
    const receive = document.querySelector<HTMLButtonElement>('[data-cp13-transfer-decision="receive"]');
    expect(receive).not.toBeNull();
    expect(receive?.disabled).toBe(false);
  });
  expect(localStorage.getItem(durableKey)).toBe(durableValue);
  q.clear();
});

it("same-principal re-login generation never reuses cached inventory authorization", async () => {
  const q = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const access2Gate = deferred<void>();
  let accessReads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
    const url = new URL(String(input), "http://wanasah.test");
    if (url.pathname !== "/inventory/access/me") throw new Error("Unexpected access request");
    accessReads += 1;
    if (accessReads === 1) return json(accessPayload(1, 11, ["transfer.read"]));
    await access2Gate.promise;
    return json(accessPayload(1, 11, []));
  }));
  login("1", "11", "first");
  const scopedWrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={q}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>
  );
  const view = renderHook(() => useInventoryAccess(), { wrapper: scopedWrapper });
  await waitFor(() => expect(view.result.current.canAny("transfer.read")).toBe(true));

  act(() => {
    login("1", "11", "second");
    notifyDashboardSessionChange();
  });
  expect(view.result.current.data).toBeUndefined();
  expect(view.result.current.canAny("transfer.read")).toBe(false);
  await waitFor(() => expect(accessReads).toBe(2));

  await act(async () => access2Gate.resolve());
  await waitFor(() => expect(view.result.current.data?.company_id).toBe(1));
  expect(view.result.current.canAny("transfer.read")).toBe(false);
  q.clear();
});
