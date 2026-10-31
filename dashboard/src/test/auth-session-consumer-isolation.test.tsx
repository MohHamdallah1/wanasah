import { useState, type ReactNode } from "react";
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { setAppLanguage } from "@/i18n";
import {
  beginDashboardSession, clearLocalStoragePreservingLoginHintsAndPreferences,
  notifyDashboardSessionChange,
} from "@/lib/authStorage";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";
import DispatchBoard from "@/pages/DispatchBoard";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";

const fake = vi.hoisted(() => ({
  fetch: vi.fn(), owner: true,
  warning: vi.fn(), error: vi.fn(), success: vi.fn(), dismiss: vi.fn(),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => ({
  isCompanyOwner: fake.owner, data: { company_id: 1, principal_id: 11 }, can: () => true,
}) }));
vi.mock("sonner", () => ({ toast: {
  warning: fake.warning, error: fake.error, success: fake.success, dismiss: fake.dismiss,
} }));
// These are deterministic response-order tests, not substitutes for the seven
// genuine HTTP/PG16 auth invariants retained in the same workflow.
vi.mock("@/pages/products/contracts", async importOriginal => ({
  ...await importOriginal<typeof import("@/pages/products/contracts")>(),
  parseProductImportState: (value: unknown) => value,
}));

class Socket {
  static CONNECTING = 0; static OPEN = 1; static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = Socket.CONNECTING; closed = 0; sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) { Socket.instances.push(this); }
  send(value: string) { this.sent.push(value); }
  close() { this.closed++; this.readyState = Socket.CLOSED; }
  open() { this.readyState = Socket.OPEN; this.onopen?.(); }
  message(event: string, message = "Company A confidential alert") {
    this.onmessage?.(new MessageEvent("message", {
      data: JSON.stringify({ event, message, job_id: JOB }),
    }));
  }
}
const JOB = "11111111-1111-4111-8111-111111111111";
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
};
function install(company = "1", principal = "11", event: "local" | "storage" | "none" = "local") {
  beginDashboardSession();
  localStorage.setItem("admin_token", company + "-access");
  localStorage.setItem("refresh_token", company + "-refresh");
  localStorage.setItem("company_id", company);
  localStorage.setItem("principal_id", principal);
  localStorage.setItem("backoffice_user_id", principal + "0");
  if (event === "local") notifyDashboardSessionChange();
  if (event === "storage") window.dispatchEvent(new StorageEvent("storage", {
    key: "wanasah:auth-session:generation",
    newValue: localStorage.getItem("wanasah:auth-session:generation"),
  }));
}
const identity = (company: number, name = "Company " + company) => ({
  company_id: company, company_name: name, company_code: "C" + company,
  currency_code: company === 1 ? "JOD" : "USD",
  timezone: company === 1 ? "Asia/Amman" : "America/New_York",
  country_id: null, country_name: null, display_location: "Location " + company,
});
let clients: QueryClient[] = [];
function client() {
  const value = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(value); return value;
}
beforeEach(async () => {
  localStorage.clear(); install();
  fake.fetch.mockReset(); fake.owner = true;
  for (const fn of [fake.warning, fake.error, fake.success, fake.dismiss]) fn.mockReset();
  Socket.instances = []; vi.stubGlobal("WebSocket", Socket);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  await setAppLanguage("en");
});
afterEach(() => {
  cleanup(); clients.forEach(c => c.clear()); clients = [];
  vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear();
});
const router = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;

describe("SEC-CACHE-01 actual tenant hook with a persistent QueryClient", () => {
  function mountCache() {
    const q = client();
    const admissions: Array<{ session: string | null; rendered: number | undefined }> = [];
    function View() {
      const result = useTenantIdentity();
      admissions.push({ session: localStorage.getItem("company_id"), rendered: result.data?.company_id });
      return <output data-testid="identity">{result.data ? JSON.stringify(result.data) : "pending"}</output>;
    }
    render(<QueryClientProvider client={q}><MemoryRouter><View /></MemoryRouter></QueryClientProvider>);
    return { q, admissions };
  }
  for (const locale of ["ar", "en"]) {
    it("never presents fresh A metadata for B after same-SPA login in " + locale, async () => {
      await setAppLanguage(locale);
      const b = deferred<unknown>();
      fake.fetch.mockImplementation(() => localStorage.getItem("company_id") === "1"
        ? Promise.resolve(identity(1)) : b.promise);
      const { q, admissions } = mountCache();
      await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Company 1"));
      act(() => install("2", "22"));
      expect(screen.getByTestId("identity").textContent).toBe("pending");
      await waitFor(() => expect(fake.fetch).toHaveBeenCalledTimes(2));
      await act(async () => b.resolve(identity(2)));
      await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("America/New_York"));
      expect(admissions.some(row => row.session === "2" && row.rendered === 1)).toBe(false);
      const keys = JSON.stringify(q.getQueryCache().getAll().map(query => query.queryKey));
      expect(keys).not.toContain("1-access");
      expect(keys).not.toContain("1-refresh");
    });
  }
  it("reacts to another tab's generation event without manual rerender", async () => {
    fake.fetch.mockImplementation(async () => identity(Number(localStorage.getItem("company_id"))));
    const { admissions } = mountCache();
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Company 1"));
    act(() => install("2", "22", "storage"));
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Company 2"));
    expect(fake.fetch).toHaveBeenCalledTimes(2);
    expect(admissions.some(row => row.session === "2" && row.rendered === 1)).toBe(false);
  });
  it("rejects delayed A identity after B has already become current", async () => {
    const a = deferred<unknown>();
    fake.fetch.mockImplementation(() => localStorage.getItem("company_id") === "1"
      ? a.promise : Promise.resolve(identity(2)));
    const { admissions, q } = mountCache();
    await waitFor(() => expect(fake.fetch).toHaveBeenCalledTimes(1));
    act(() => install("2", "22", "storage"));
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Company 2"));
    await act(async () => a.resolve(identity(1)));
    expect(admissions.some(row => row.session === "2" && row.rendered === 1)).toBe(false);
    expect(q.getQueryCache().getAll().filter(query =>
      (query.state.data as { company_id?: number } | undefined)?.company_id === 1)).toHaveLength(0);
  });
  it("isolates same-principal new login generations while retaining same-session caching", async () => {
    let calls = 0;
    fake.fetch.mockImplementation(async () => identity(1, "Revision " + ++calls));
    mountCache();
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Revision 1"));
    act(() => notifyDashboardSessionChange());
    expect(fake.fetch).toHaveBeenCalledTimes(1);
    act(() => install("1", "11"));
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Revision 2"));
  });
  it("withdraws tenant metadata on explicit logout without a new inventory read", async () => {
    fake.fetch.mockResolvedValue(identity(1)); mountCache();
    await waitFor(() => expect(screen.getByTestId("identity").textContent).toContain("Company 1"));
    act(() => { clearLocalStoragePreservingLoginHintsAndPreferences(); });
    expect(screen.getByTestId("identity").textContent).toBe("pending");
    expect(fake.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("SEC-WS-01 actual DispatchBoard socket callbacks", () => {
  async function mountDispatch() {
    vi.useFakeTimers();
    fake.fetch.mockImplementation(async (path: string) => path === "/dispatch/init"
      ? { zones: [], drivers: [], vehicles: [], warehouses: [] } : []);
    render(<MemoryRouter><DispatchBoard /></MemoryRouter>);
    await act(async () => {});
    return Socket.instances[0];
  }
  for (const locale of ["ar", "en"]) {
    it("ignores a delayed A message/open/close after cross-tab B login in " + locale, async () => {
      await setAppLanguage(locale);
      const socket = await mountDispatch();
      act(() => socket.open());
      expect(socket.sent).toEqual([JSON.stringify({ type: "auth", token: "1-access" })]);
      const message = socket.onmessage!, open = socket.onopen!, close = socket.onclose!;
      const reads = fake.fetch.mock.calls.length;
      act(() => install("2", "22", "storage"));
      act(() => {
        message(new MessageEvent("message", { data: JSON.stringify({ event: "INTEGRITY_ALERT", message: "A secret" }) }));
        message(new MessageEvent("message", { data: JSON.stringify({ event: "ROUTE_UPDATED" }) }));
        open(); close();
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
      expect(socket.closed).toBeGreaterThan(0);
      expect(Socket.instances).toHaveLength(1);
      expect(socket.sent).not.toContain(JSON.stringify({ type: "auth", token: "2-access" }));
      expect(fake.fetch).toHaveBeenCalledTimes(reads);
      expect(fake.error).not.toHaveBeenCalled();
      expect(fake.warning).not.toHaveBeenCalled();
    });
  }
  it("clears queued A alerts, refresh and reconnect timers at the local login commit", async () => {
    const socket = await mountDispatch(); act(() => socket.open());
    const close = socket.onclose!;
    act(() => {
      socket.message("STALE_SESSION_WARNING");
      socket.message("ROUTE_UPDATED");
      close();
    });
    const reads = fake.fetch.mock.calls.length;
    act(() => install("2", "22"));
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.warning).not.toHaveBeenCalled();
    expect(fake.fetch).toHaveBeenCalledTimes(reads);
    expect(Socket.instances).toHaveLength(1);
  });
  it("dismisses already-visible A alerts and blocks pending A events without a storage notification", async () => {
    const socket = await mountDispatch(); act(() => socket.open());
    act(() => socket.message("INTEGRITY_ALERT", "A visible"));
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(fake.error).toHaveBeenCalledTimes(1);
    const id = fake.error.mock.calls[0][1].id;
    act(() => socket.message("STALE_SESSION_WARNING", "A pending"));
    const reads = fake.fetch.mock.calls.length;
    act(() => install("2", "22", "none"));
    // Even a callback preceding the native storage notification checks storage.
    act(() => socket.message("ROUTE_UPDATED"));
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.dismiss).toHaveBeenCalledWith(id);
    expect(fake.warning).not.toHaveBeenCalled();
    expect(fake.fetch).toHaveBeenCalledTimes(reads);
    expect(Socket.instances).toHaveLength(1);
  });
  it("never authenticates a connecting A socket with B credentials", async () => {
    const socket = await mountDispatch();
    const open = socket.onopen!;
    act(() => install("2", "22"));
    act(() => open());
    expect(socket.sent).toHaveLength(0);
    expect(socket.closed).toBeGreaterThan(0);
  });
  it("preserves same-session token rotation, valid alerts, refresh and reconnect", async () => {
    const socket = await mountDispatch();
    localStorage.setItem("admin_token", "rotated-access");
    act(() => notifyDashboardSessionChange());
    act(() => socket.open());
    expect(socket.sent).toEqual([JSON.stringify({ type: "auth", token: "rotated-access" })]);
    const initial = fake.fetch.mock.calls.length;
    act(() => { socket.message("STALE_SESSION_WARNING", "Authorized alert"); socket.message("ROUTE_UPDATED"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(fake.warning).toHaveBeenCalledWith("Authorized alert", expect.objectContaining({ id: expect.any(String) }));
    expect(fake.fetch.mock.calls.length).toBeGreaterThan(initial);
    act(() => {
      socket.readyState = Socket.CLOSED;
      socket.onclose?.();
      // Visibility can restore the feed before the queued reconnect fires.
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(Socket.instances).toHaveLength(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(Socket.instances).toHaveLength(2);
  });
  it("keeps restricted readers off the owner stream and stops their old polling", async () => {
    fake.owner = false; await mountDispatch();
    expect(Socket.instances).toHaveLength(0);
    const initial = fake.fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
    expect(fake.fetch.mock.calls.length).toBeGreaterThan(initial);
    act(() => install("2", "22", "storage"));
    const before = fake.fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.fetch).toHaveBeenCalledTimes(before);
  });
});

describe("adjacent Product Import uses the same captured-session boundary", () => {
  const progress = { status: "IMPORTING", imported_rows: 0, invalid_rows: 0,
    import_failed_rows: 0, default_lot_control_mode: "NONE", default_expiry_control_mode: "NONE" };
  const completed = { ...progress, status: "COMPLETED", imported_rows: 1 };
  function mountImport() {
    vi.useFakeTimers();
    const status = vi.fn(), error = vi.fn(), tracking = vi.fn(), mapping = vi.fn();
    const q = client(), invalidation = vi.spyOn(q, "invalidateQueries");
    function Hook() {
      const [, poll] = useState(0);
      return useImportProductPolling({ enabled: true, importJobId: JOB, importPollKey: 0,
        setImportPollKey: poll, authFetch: fake.fetch, queryClient: q,
        t: ((key: string) => key) as TFunction, isOnline: true,
        setImportPollError: error, setImportStatus: status,
        setImportLotControlMode: tracking, setImportExpiryControlMode: tracking, setMapping: mapping });
    }
    renderHook(Hook);
    return { status, error, tracking, mapping, invalidation };
  }
  it("closes A socket and rejects its late HTTP, progress, open and close after B login", async () => {
    const pending = deferred<unknown>();
    fake.fetch.mockReturnValue(pending.promise);
    const view = mountImport(), socket = Socket.instances[0];
    act(() => socket.open());
    const message = socket.onmessage!, open = socket.onopen!, close = socket.onclose!;
    const reads = fake.fetch.mock.calls.length;
    act(() => install("2", "22", "storage"));
    expect(view.status).toHaveBeenLastCalledWith(null);
    const changes = view.status.mock.calls.length;
    await act(async () => {
      message(new MessageEvent("message", { data: JSON.stringify({ event: "PRODUCT_IMPORT_PROGRESS", job_id: JOB }) }));
      open(); close(); pending.resolve(completed);
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(60000);
    });
    expect(socket.closed).toBeGreaterThan(0);
    expect(Socket.instances).toHaveLength(1);
    expect(fake.fetch).toHaveBeenCalledTimes(reads);
    expect(view.status).toHaveBeenCalledTimes(changes);
    expect(view.invalidation).not.toHaveBeenCalled();
    expect(fake.success).not.toHaveBeenCalled();
    expect(view.tracking).toHaveBeenLastCalledWith(null);
    expect(view.mapping).toHaveBeenLastCalledWith({});
  });
  it("drops pending A refresh and reconnect work even before the session event arrives", async () => {
    fake.fetch.mockResolvedValue(progress);
    mountImport(); const socket = Socket.instances[0];
    await act(async () => { socket.open(); await Promise.resolve(); });
    act(() => socket.message("PRODUCT_IMPORT_PROGRESS"));
    const reads = fake.fetch.mock.calls.length;
    act(() => install("2", "22", "none"));
    act(() => socket.onclose?.());
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.fetch).toHaveBeenCalledTimes(reads);
    expect(Socket.instances).toHaveLength(1);
  });
  it("clears an A completion notification and snapshot on a later login", async () => {
    fake.success.mockReturnValue("completed-A");
    fake.fetch.mockResolvedValue(completed);
    const view = mountImport();
    await act(async () => {});
    expect(view.status).toHaveBeenLastCalledWith(completed);
    expect(fake.success).toHaveBeenCalledTimes(1);
    act(() => install("2", "22"));
    expect(fake.dismiss).toHaveBeenCalledWith("completed-A");
    expect(view.status).toHaveBeenLastCalledWith(null);
    const reads = fake.fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.fetch).toHaveBeenCalledTimes(reads);
  });
});
