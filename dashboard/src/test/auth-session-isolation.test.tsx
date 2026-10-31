import { act, cleanup, renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { beginDashboardSession, captureDashboardSession, clearLocalStoragePreservingLoginHintsAndPreferences } from "@/lib/authStorage";

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
