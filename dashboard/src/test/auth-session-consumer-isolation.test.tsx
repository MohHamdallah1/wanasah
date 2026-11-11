import "@testing-library/jest-dom/vitest";
import { useMemo, useState, type ReactNode } from "react";
import { webcrypto } from "node:crypto";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { setAppLanguage } from "@/i18n";
import {
  beginDashboardSession, clearLocalStoragePreservingLoginHintsAndPreferences,
  notifyDashboardSessionChange, invalidateDashboardSession,
} from "@/lib/authStorage";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";
import DispatchBoard from "@/pages/DispatchBoard";
import { writeDispatchPreferences } from "@/features/dispatch/sessionScope";
import { durableScope, getOrCreateDurableCommand, readDurableCommand } from "@/lib/durableOperations";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";

const fake = vi.hoisted(() => ({
  tenantStub: true,
  fetch: vi.fn(), owner: true,
  warning: vi.fn(), error: vi.fn(), success: vi.fn(), dismiss: vi.fn(),
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
// Keep SEC-CACHE-01 exercising the REAL tenant hook; only the older socket
// consumer fixture renders without QueryClient, so stub that context alone.
vi.mock("@/features/tenantIdentity/useTenantIdentity", async importOriginal => {
  const original = await importOriginal<typeof import("@/features/tenantIdentity/useTenantIdentity")>();
  return {
    ...original,
    useTenantIdentity: () => fake.tenantStub
      ? { data: { company_id: Number(localStorage.getItem("company_id")),
          currency_code: localStorage.getItem("company_id") === "1" ? "QAR" : "OMR" } }
      : original.useTenantIdentity(),
  };
});
vi.mock("@/hooks/useInventoryAccess", () => ({ useInventoryAccess: () => {
  const company = Number(localStorage.getItem("company_id"));
  const principal = Number(localStorage.getItem("principal_id"));
  const owner = fake.owner;
  // D09 requires real effective grants. Keep stable objects across React rerenders,
  // as the production capability query does; do not grant a non-owner shortage.read.
  const data = useMemo(() => ({
    company_id: company, principal_id: principal, backoffice_user_id: principal * 10,
    is_company_owner: owner, location_id: null,
    permissions: owner ? ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"] : [],
    any_permissions: owner ? ["dispatch.read", "dispatch.execute", "shortage.read", "shortage.create", "shortage.cancel"] : ["dispatch.read"],
    location_permissions: [],
  }), [company, principal, owner]);
  return {
    isCompanyOwner: owner, data, can: () => true,
    isFetching: false, isError: false, error: null, dataUpdatedAt: 100,
    refetch: async () => ({ data }),
  };
} }));
vi.mock("sonner", () => ({ toast: {
  warning: fake.warning, error: fake.error, success: fake.success, dismiss: fake.dismiss,
} }));
vi.mock("@/components/ui/custom-select", () => ({ CustomSelect: ({ label, value, options, onChange }: {
  label: string; value: string; options: { id: string; label: string }[]; onChange: (value: string) => void;
}) => <select aria-label={label} value={value} onChange={event => onChange(event.target.value)}>
  <option value="" />{options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
</select> }));
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
  fake.fetch.mockReset(); fake.owner = true; fake.tenantStub = true;
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
  beforeEach(() => { fake.tenantStub = false; });
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
  for (const locale of ["ar", "en"] as const) {
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
  let readCompanies: string[];
  async function mountDispatch() {
    vi.useFakeTimers();
    readCompanies = [];
    fake.fetch.mockImplementation(async (path: string) => {
      readCompanies.push(localStorage.getItem("company_id")!);
      return path === "/dispatch/init" ? { zones: [], drivers: [], vehicles: [], warehouses: [] } : [];
    });
    render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
    await act(async () => {});
    return Socket.instances[0];
  }
  for (const locale of ["ar", "en"] as const) {
    it("ignores a delayed A message/open/close after cross-tab B login in " + locale, async () => {
      await setAppLanguage(locale);
      const socket = await mountDispatch();
      act(() => socket.open());
      expect(socket.sent).toEqual([JSON.stringify({ type: "auth", token: "1-access" })]);
      const message = socket.onmessage!, open = socket.onopen!, close = socket.onclose!;
      const reads = fake.fetch.mock.calls.length;
      act(() => install("2", "22", "storage"));
      // B starts its OWN tab-specific signed reads, not the old four-request
      // aggregate. Its existing Routes tab needs init, routes, shortages.
      const bReads = fake.fetch.mock.calls.length;
      expect(bReads).toBe(reads + 3);
      act(() => {
        message(new MessageEvent("message", { data: JSON.stringify({ event: "INTEGRITY_ALERT", message: "A secret" }) }));
        message(new MessageEvent("message", { data: JSON.stringify({ event: "ROUTE_UPDATED" }) }));
        open(); close();
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
      expect(socket.closed).toBeGreaterThan(0);
      expect(Socket.instances).toHaveLength(2); // one A (closed), one fresh B
      expect(socket.sent).not.toContain(JSON.stringify({ type: "auth", token: "2-access" }));
      expect(fake.fetch).toHaveBeenCalledTimes(bReads);
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
    const bReads = fake.fetch.mock.calls.length;
    expect(bReads).toBe(reads + 3);
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(fake.warning).not.toHaveBeenCalled();
    expect(fake.fetch).toHaveBeenCalledTimes(bReads);
    expect(Socket.instances).toHaveLength(2);
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
    const aReads = readCompanies.filter(company => company === "1").length;
    act(() => install("2", "22", "storage"));
    const before = fake.fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
    expect(readCompanies.filter(company => company === "1")).toHaveLength(aReads);
    expect(readCompanies.slice(before)).toEqual(Array(4).fill("2"));
    expect(fake.fetch).toHaveBeenCalledTimes(before + 4);
    expect(Socket.instances).toHaveLength(0);
  });
});

describe("D09 actual DispatchBoard effective grants and revoked view", () => {
  it.each([{ width: 390, locale: "ar" }, { width: 1440, locale: "en" }] as const)(
    "keeps non-owner scoped Zones visible/read-only then hides private rows at $width in $locale",
    async ({ width, locale }) => {
      await setAppLanguage(locale);
      fake.owner = false;
      Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
      fake.fetch.mockImplementation(async (path: string) => {
        if (path === "/dispatch/init") return {
          zones: [{ id: "41", name: "Scoped Zone", intervalDays: null, startDate: "",
            scheduleStatus: "null", shopsCount: 1 }],
          drivers: [], vehicles: [], warehouses: [],
        };
        if (path === "/dispatch/shops") return [{
          id: "17", name: "Scoped Shop", owner: "Private Owner", phone: "55555555",
          initialDebt: "130", maxDebtLimit: "300", zoneId: "41", archived: false,
          sequence: 1,
        }];
        return [];
      });
      render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
      const tab = await screen.findByRole("tab", { name: /هيكلة المناطق/ });
      // Public chrome exists immediately, but dispatch data/actions still
      // await fresh signed Backend admission before becoming interactive.
      await waitFor(() => expect(tab).toBeEnabled());
      fireEvent.click(tab);
      await screen.findAllByText("Scoped Zone");
      await screen.findByText("Scoped Shop");
      expect(screen.queryByText("[+ منطقة جديدة]")).not.toBeInTheDocument();
      act(() => window.dispatchEvent(new Event("inventory-permission-denied")));
      expect(screen.queryByText("Scoped Shop")).not.toBeInTheDocument();
      expect(screen.queryByText("Private Owner")).not.toBeInTheDocument();
      expect(screen.queryAllByText("Scoped Zone")).toHaveLength(0);
      expect(screen.getByRole("alert")).toHaveTextContent(
        locale === "ar" ? "لا تملك صلاحية" : "You do not have access",
      );
    },
  );
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

it("unmounts all A Dispatch state/actions on B login, rejects late A, admits only fresh B and preserves durable drafts", async () => {
  vi.stubGlobal("crypto", webcrypto);
  const scope = durableScope(1, 11, "dispatch-adjust-base", "9");
  const draft = await getOrCreateDurableCommand(scope, { deltas: [{ product_id: 701, delta_base: "8" }] });
  const persisted = localStorage.getItem(scope);
  vi.useFakeTimers();
  writeDispatchPreferences("1:11:110", {
    activeTab: "launch", zoneForShops: "1", launchZone: "1",
    driver: "31", vehicle: "17", sourceWarehouse: "21",
  });
  const lateA = deferred<void>(), allowB = deferred<void>();
  const requests: Array<{ company: string; path: string; signal?: AbortSignal | null }> = [];
  let aInit = 0;
  const data = (company: string, path: string, late = false): unknown => {
    const a = company === "1", tag = a ? "A-" : "B-";
    const zone = a ? "1" : "2", driver = a ? "31" : "32", vehicle = a ? "17" : "27";
    const warehouse = a ? "21" : "22", product = a ? "701" : "702", shop = a ? "51" : "52";
    const name = (suffix: string) => tag + (late ? "LATE-" : "") + suffix;
    if (path === "/dispatch/init") return {
      zones: [{ id: zone, name: name("zone"), scheduleStatus: "active" }],
      drivers: [{ id: driver, name: name("driver") }],
      vehicles: [{ id: vehicle, label: name("vehicle"), can_execute: true }],
      warehouses: [{ id: warehouse, label: name("warehouse"), can_execute: true }],
    };
    if (path === "/dispatch/shops") return [{ id: shop, name: name("shop"), owner: name("owner"),
      phone: "123", zoneId: zone, initialDebt: 0, maxDebtLimit: 0, archived: false, sequence: 1 }];
    if (path === "/dispatch/active_routes") return [{ id: a ? "9" : "10", zoneId: zone,
      zoneName: name("route"), driverId: driver, driverName: name("driver"), vehicleId: vehicle,
      shopsRemaining: 2, status: "active", sessionBound: false, sessionEnded: false,
      can_execute: true, commercial_context: null }];
    if (path === "/dispatch/shortages") return [{ id: a ? "61" : "62", shopId: shop, shopName: name("shop"),
      zoneId: zone, zoneName: name("zone"), driverId: driver, driverName: name("driver"),
      productId: product, productName: name("shortage"), quantity: 7, createdAt: "2026-10-31T00:00:00Z" }];
    const unit = { base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH", quantity_scale: 0,
      quantity_step: "1", display_uom_name: "PACK", display_factor_to_base: "8" };
    if (path.startsWith("/dispatch/inventory/")) return [{ ...unit, product_id: product,
      product_name: name("custody"), current_base_quantity: "25", current_quantity: 3 }];
    if (path.startsWith("/dispatch/products?")) return { items: [{ id: product, name: name("custody"),
      load: { ...unit, product_id: product, product_name: name("custody"), current_base_quantity: "0",
        reserved_base_quantity: "0", pending_base_quantity: "0" } }], next_cursor: null, has_more: false };
    if (path.startsWith("/warehouse/status")) return { status: "ACTIVE" };
    throw new Error("Unexpected focused Dispatch read: " + path);
  };
  fake.fetch.mockImplementation(async (path: string, opts?: RequestInit) => {
    expect(opts?.method ?? "GET").toBe("GET");
    const company = localStorage.getItem("company_id")!;
    requests.push({ company, path, signal: opts?.signal });
    if (company === "2") { await allowB.promise; return data(company, path); }
    if (path === "/dispatch/init" && ++aInit > 1) {
      await lateA.promise; // Deliberately ignore abort to challenge stale response admission.
      return data(company, path, true);
    }
    return data(company, path);
  });
  render(<MemoryRouter initialEntries={["/dispatch"]}><DispatchBoard /></MemoryRouter>);
  await act(async () => {});
  expect(screen.getByRole("option", { name: "A-zone" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "A-driver" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "A-vehicle" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "مستودع المصدر" }), { target: { value: "21" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.getByRole("option", { name: "A-warehouse" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: /Target.*A-custody/ })).toHaveValue("25");
  fireEvent.click(screen.getByRole("tab", { name: "الخطوط النشطة" }));
  await act(async () => {}); // actual independent signed Routes response
  expect(screen.getByText("A-route")).toBeInTheDocument();
  const oldAction = screen.getByRole("button", { name: /تعديل الحمولة/ });
  fireEvent.click(screen.getByRole("button", { name: /طلبات ونواقص/ }));
  await act(async () => {}); // demand-only signed Shops GET if not admitted yet
  const shopAccordion = screen.getByRole("button", { name: /(?:عرض منتجات|Show items for) A-shop/ });
  expect(shopAccordion).toBeInTheDocument();
  fireEvent.click(shopAccordion);
  expect(screen.getByText("A-shortage")).toBeInTheDocument();
  const oldModal = screen.getByRole("dialog"), oldPage = document.querySelector(".dispatch-board");
  act(() => Socket.instances[0].message("ROUTE_UPDATED"));
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(aInit).toBeGreaterThanOrEqual(2); // tab refresh may also read init, without reusing old actor

  act(() => {
    // Canonical Login clears only these transient company selections before publishing.
    for (const key of ["activeTab", "wanasah_selected_zone", "wanasah_route_zone",
      "wanasah_route_driver", "wanasah_route_vehicle"]) localStorage.removeItem(key);
    install("2", "22", "storage");
  });
  expect(oldPage).not.toBeInTheDocument();
  expect(oldModal).not.toBeInTheDocument();
  expect(oldAction).not.toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(/A-(zone|shop|route|driver|vehicle|warehouse|custody|stock|shortage)/);
  expect(document.body.textContent).not.toMatch(/B-(route|shop|stock)/);
  expect(requests.some(request => request.company === "2" && request.path === "/dispatch/init")).toBe(true);
  expect(requests.filter(request => request.company === "1" && request.path === "/dispatch/init")
    .every(request => request.signal?.aborted)).toBe(true);
  // D15: the public tab structure stays on screen, but NONE can execute
  // during B's pending permission/data read, and all A private rows were fenced.
  for (const tab of screen.getAllByRole("tab")) expect(tab).toBeDisabled();
  expect(screen.getAllByRole("tab")).toHaveLength(3);
  expect(screen.getByTestId("dispatch-shared-topbar")).toBeInTheDocument();
  // #918: same real FLEX-card route surface throughout B's pending signed reads.
  expect(screen.getByTestId("dispatch-routes-workspace")).toBeInTheDocument();
  expect(screen.getByTestId("dispatch-routes-read-status")).toHaveTextContent(/Verifying routes/);
  expect(screen.queryByTestId("dispatch-structural-workspace")).not.toBeInTheDocument();
  expect(screen.queryByTestId("dispatch-quiet-loading")).not.toBeInTheDocument();
  expect(document.querySelector('[aria-label="هيكل جدول التوزيع"]')).toBeNull();
  expect(document.body.textContent).not.toContain("Checking access permissions");
  await act(async () => lateA.resolve());
  expect(document.body.textContent).not.toContain("A-LATE");
  expect(localStorage.getItem(scope)).toBe(persisted);

  await act(async () => allowB.resolve());
  expect(screen.getByText("B-route")).toBeInTheDocument();
  for (const tab of ["إطلاق خط جديد", "هيكلة المناطق", "الخطوط النشطة"]) {
    fireEvent.click(screen.getByRole("tab", { name: tab }));
    expect(document.body.textContent).not.toMatch(/A-(zone|shop|route|driver|vehicle|warehouse|custody|stock|shortage)/);
  }
  fireEvent.click(screen.getByRole("tab", { name: "الخطوط النشطة" }));
  expect(document.body.textContent).not.toMatch(/A-(zone|shop|route|driver|vehicle|warehouse|custody|stock|shortage|LATE)/);
  fireEvent.click(screen.getByRole("button", { name: /طلبات ونواقص/ }));
  await act(async () => {});
  expect(screen.getByRole("button", { name: /(?:عرض منتجات|Show items for) B-shop/ })).toBeInTheDocument();
  expect(await readDurableCommand(scope)).toEqual(draft);

  // The production auth-expiry logout also emits the existing session event.
  act(() => {
    invalidateDashboardSession();
    localStorage.removeItem("admin_token"); localStorage.removeItem("refresh_token");
    notifyDashboardSessionChange();
  });
  expect(document.querySelector(".dispatch-board")).toBeNull();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(localStorage.getItem(scope)).toBe(persisted);
});
