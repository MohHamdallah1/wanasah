import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { PREFLIGHT_AREAS, parseCommercialPreflight, preflightReason,
  preflightUrl, type CommercialPreflight } from
  "@/features/dispatch/commercialPreflight/contract";
import { useCommercialPreflight } from
  "@/features/dispatch/commercialPreflight/useCommercialPreflight";
import { CommercialPreflightPanel } from
  "@/features/dispatch/commercialPreflight/CommercialPreflightPanel";
import { DispatchChrome } from "@/features/dispatch/stableUi/DispatchChrome";

const selection = { zoneId: "7", driverId: "9", vehicleId: "31", warehouseId: "20" };
const server = (broken?: [typeof PREFLIGHT_AREAS[number], string]): CommercialPreflight => {
  const checks = Object.fromEntries(PREFLIGHT_AREAS.map(area =>
    [area, { ready: true, code: "READY", context: {} }])) as CommercialPreflight["checks"];
  if (broken) checks[broken[0]] = { ready: false, code: broken[1], context: {} };
  return { advisory: true, currency_code: "QAR", checks, ready: !broken };
};
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("D11 canonical commercial route-launch evidence", () => {
  it("refuses guessed tax zero or missing revision: published tax 0% is valid only with server READY", () => {
    const actualZero = parseCommercialPreflight(server());
    expect(actualZero.checks.tax.ready).toBe(true);
    expect(actualZero.ready).toBe(true);
    const missing = parseCommercialPreflight(server(["tax", "TAX_CONFIGURATION_REQUIRED"]));
    expect(missing.ready).toBe(false);
    expect(preflightReason("ar", missing.checks.tax.code).text).toContain("0%");
    expect(preflightReason("en", missing.checks.tax.code).text).toContain("0%");
    expect(() => parseCommercialPreflight({ ...server(), checks: { tax: { ready: true } } })).toThrow();
    expect(() => parseCommercialPreflight({ ...server(["pricing", "PRICE_NOT_RESOLVED"]), ready: true })).toThrow();
  });

  it("constructs only precise selected route context and refuses malformed selection", () => {
    expect(preflightUrl(selection)).toContain("source_location_id=20");
    expect(preflightUrl(selection)).toContain("vehicle_id=31");
    expect(() => preflightUrl({ ...selection, warehouseId: "0" })).toThrow();
    expect(() => preflightUrl({ ...selection, driverId: "not-an-id" })).toThrow();
  });

  it("AR 390px shows actionable pricing, tax, rounding and audit-lock instructions without raw codes", () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    const tax = server(["tax", "TAX_CONFIGURATION_REQUIRED"]);
    const view = render(<MemoryRouter><CommercialPreflightPanel language="ar"
      evidence={tax} status="blocked" onRefresh={vi.fn()} /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("الإطلاق ممنوع");
    expect(screen.getByText(/نسبة 0% المنشورة صالحة/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "فتح القواعد التجارية" })).toHaveAttribute("href", "/commercial-rules");
    expect(view.container.textContent).not.toContain("TAX_CONFIGURATION_REQUIRED");
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="ar"
      evidence={server(["warehouse", "SOURCE_WAREHOUSE_AUDIT_LOCK"])}
      status="blocked" onRefresh={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(/جرد شامل/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/inventory");
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="en"
      evidence={server(["pricing", "PRICE_NOT_RESOLVED"])}
      status="blocked" onRefresh={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(/Publish an approved price list/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open products" })).toHaveAttribute("href", "/products");
  });

  it("opens the actual Dispatch subtab for blocked route/zone instead of a dead same-route settings link", () => {
    const navigateTab = vi.fn();
    const allowed = vi.fn(() => true);
    const view = render(<MemoryRouter><CommercialPreflightPanel language="ar"
      evidence={server(["route", "ROUTE_ALREADY_ASSIGNED"])} status="blocked" onRefresh={vi.fn()}
      onNavigateToTab={navigateTab} canNavigateToTab={allowed} /></MemoryRouter>);
    expect(screen.queryByRole("link", { name: "اذهب للإعداد" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "عرض الخطوط النشطة" }));
    expect(navigateTab).toHaveBeenCalledWith("routes");
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="ar"
      evidence={server(["zone", "ZONE_UNAVAILABLE"])} status="blocked" onRefresh={vi.fn()}
      onNavigateToTab={navigateTab} canNavigateToTab={allowed} /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "فتح المناطق" }));
    expect(navigateTab).toHaveBeenCalledWith("zones");
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="ar"
      evidence={server(["route", "ROUTE_ALREADY_ASSIGNED"])} status="blocked" onRefresh={vi.fn()}
      onNavigateToTab={navigateTab} canNavigateToTab={() => false} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: "عرض الخطوط النشطة" })).not.toBeInTheDocument();
  });

  it("fails closed on authentic 401/403, read error, and does not fabricate ready", async () => {
    const denied = Object.assign(new Error("private"), { status: 403 });
    const fetch = vi.fn().mockRejectedValue(denied);
    const { result, rerender } = renderHook(({ authorized }) =>
      useCommercialPreflight({ selection, actorScope: "1:3:13",
        authorized, current: () => true, fetch }), { initialProps: { authorized: true } });
    await waitFor(() => expect(result.current.status).toBe("denied"));
    expect(result.current.canLaunch).toBe(false);
    rerender({ authorized: false });
    expect(result.current.canLaunch).toBe(false);
    expect(result.current.evidence).toBeNull();
  });

  it("discards delayed old-account READY and requires a NEW HTTP read immediately before launch", async () => {
    let release!: (result: CommercialPreflight) => void;
    const old = new Promise<CommercialPreflight>(resolve => { release = resolve; });
    const fetch = vi.fn().mockReturnValueOnce(old).mockResolvedValue(server(["rounding", "COMMERCIAL_ROUNDING_NOT_CONFIGURED"]));
    let owner = true;
    const { result, rerender } = renderHook(({ actor }) =>
      useCommercialPreflight({ selection, actorScope: actor,
        authorized: true, current: () => owner, fetch }), { initialProps: { actor: "1:3:13" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    rerender({ actor: "2:4:14" });
    expect(result.current.canLaunch).toBe(false);
    await act(async () => release(server()));
    await waitFor(() => expect(result.current.status).toBe("blocked"));
    expect(result.current.evidence?.checks.rounding.code).toBe("COMMERCIAL_ROUNDING_NOT_CONFIGURED");
    expect(result.current.canLaunch).toBe(false);

    fetch.mockResolvedValueOnce(server());
    await act(async () => {
      expect((await result.current.verifyBeforeLaunch())?.ready).toBe(true);
    });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(result.current.canLaunch).toBe(true);
    expect(fetch.mock.calls[2][1]).toMatchObject({ method: "GET", cache: "no-store" });
    owner = false;
    expect(await result.current.verifyBeforeLaunch()).toBeNull();
  });

  it("rechecks after pressing refresh; blocked backend cannot be overridden by UI state", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(server())
      .mockResolvedValueOnce(server(["vehicle", "VEHICLE_NOT_OPERATIONAL"]));
    const { result } = renderHook(() =>
      useCommercialPreflight({ selection, actorScope: "1:3:13",
        authorized: true, current: () => true, fetch }));
    await waitFor(() => expect(result.current.canLaunch).toBe(true));
    await act(async () => result.current.refresh());
    await waitFor(() => expect(result.current.status).toBe("blocked"));
    expect(result.current.canLaunch).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});


describe("D15 compact preflight presentation — independent panel states", () => {
  const renderPanel = (
    status: "choose" | "loading" | "ready" | "blocked" | "error" | "denied",
    language = "ar", evidence: CommercialPreflight | null = null, onRefresh = vi.fn(),
  ) => render(<MemoryRouter><CommercialPreflightPanel language={language}
    status={status} evidence={evidence} onRefresh={onRefresh} /></MemoryRouter>);

  const blockers = (failures: Partial<Record<typeof PREFLIGHT_AREAS[number], string>>) => {
    const state = server();
    for (const area of PREFLIGHT_AREAS) {
      if (failures[area]) state.checks[area] = {
        ready: false, code: failures[area]!, context: {},
      };
    }
    state.ready = false;
    return state;
  };

  it("preserves the real compact readiness footprint without a fake choice message", () => {
    const view = renderPanel("choose", "ar", server());
    expect(view.container.querySelector("section")).toHaveClass("min-h-6");
    expect(view.container.querySelector("section")).toHaveAttribute("aria-busy", "false");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps a silent aria-busy slot during true revalidation without shifting the layout", () => {
    const view = renderPanel("loading");
    const section = view.container.querySelector("section");
    expect(section).toHaveAttribute("aria-busy", "true");
    expect(section).toHaveClass("min-h-6");
    expect(view.container).not.toHaveTextContent("جاري التحقق");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const evidence = server();
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="ar"
      status="ready" evidence={evidence} onRefresh={vi.fn()} /></MemoryRouter>);
    expect(view.container.querySelector("section")).toBe(section);
    expect(section).toHaveClass("min-h-6");
    expect(screen.getByRole("status")).toHaveTextContent("تم التحقق");
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="ar"
      status="loading" evidence={null} onRefresh={vi.fn()} /></MemoryRouter>);
    expect(view.container.querySelector("section")).toBe(section);
    expect(section).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("تم التحقق")).not.toBeInTheDocument();
  });

  it("shows only the compact ready check for authoritative published 0%-tax READY", () => {
    const verified = server();
    verified.checks.tax = { ready: true, code: "READY", context: { published_rate: "0" } };
    const view = renderPanel("ready", "ar", verified);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", expect.stringContaining("التحقق ناجح"));
    expect(screen.getByRole("status")).toHaveTextContent("تم التحقق");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(view.container.querySelector(".shadow-sm, .rounded-2xl")).not.toBeInTheDocument();
  });

  it("does not display a fake successful check without authoritative ready evidence", () => {
    const retry = vi.fn();
    renderPanel("ready", "ar", null, retry);
    expect(screen.queryByText("تم التحقق")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("تعذّر التحقق");
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("AR 390px preserves ALL price, tax, rounding, warehouse, vehicle and custody blockers", () => {
    const priorWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    try {
      const retry = vi.fn();
      const view = renderPanel("blocked", "ar", blockers({
        pricing: "PRICE_NOT_RESOLVED",
        tax: "TAX_CONFIGURATION_REQUIRED",
        rounding: "COMMERCIAL_ROUNDING_NOT_CONFIGURED",
        warehouse: "SOURCE_WAREHOUSE_AUDIT_LOCK",
        vehicle: "VEHICLE_NOT_OPERATIONAL",
        custody: "VEHICLE_CUSTODY_UNAVAILABLE",
      }), retry);
      expect(screen.getByRole("status")).toHaveTextContent("الإطلاق ممنوع");
      expect(screen.queryByRole("list")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "البنود (6)" }));
      expect(screen.getByRole("list").querySelectorAll("li")).toHaveLength(6);
      expect(screen.getByText(/نسبة 0% المنشورة صالحة/)).toBeInTheDocument();
      expect(screen.getByText(/جرد شامل/)).toBeInTheDocument();
      expect(screen.getAllByText(/عهدة المركبة/).length).toBeGreaterThan(0);
      expect(screen.getAllByRole("link")
        .map(a => a.getAttribute("href"))).toEqual([
          "/products", "/commercial-rules", "/commercial-rules", "/inventory",
          "/representatives-vehicles", "/representatives-vehicles",
        ]);
      expect(view.container.querySelector("section")).toHaveAttribute("dir", "rtl");
      expect(view.container.querySelector("ul")).toHaveClass("min-w-0");
      expect(view.container.textContent).not.toContain("PRICE_NOT_RESOLVED");
      expect(screen.queryByRole("button", { name: "إعادة التحقق" })).not.toBeInTheDocument();
      expect(retry).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: priorWidth });
    }
  });

  it("EN LTR preserves specific failed tax and custody reasons and keyboard focus", () => {
    const view = renderPanel("blocked", "en", blockers({
      tax: "TAX_CONFIGURATION_REQUIRED", custody: "VEHICLE_CUSTODY_LOCATION_MISSING",
    }));
    expect(view.container.querySelector("section")).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("status")).toHaveTextContent("Launch blocked");
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", expect.stringContaining("Launch is blocked"));
    expect(screen.getByText(/published 0% tax is valid/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Issues (2)" }));
    const links = screen.getAllByRole("link");
    expect(links.map(a => a.getAttribute("href"))).toEqual([
      "/commercial-rules", "/representatives-vehicles",
    ]);
    expect(links).toHaveLength(2);
    links[0].focus();
    expect(links[0]).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Recheck readiness" })).not.toBeInTheDocument();
  });

  it("provides retry on read errors but no misleading retry or success after permission denial", () => {
    const retry = vi.fn();
    const view = renderPanel("error", "ar", null, retry);
    expect(screen.getByRole("status")).toHaveTextContent("تعذّر التحقق");
    fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
    expect(retry).toHaveBeenCalledOnce();
    view.rerender(<MemoryRouter><CommercialPreflightPanel language="en"
      status="denied" evidence={null} onRefresh={retry} /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Access was revoked");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
  });
});


describe("D15 automatic commercial preflight: bounded visible evidence only", () => {
  const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
  const originalOnline = Object.getOwnPropertyDescriptor(navigator, "onLine");
  const visible = (value: "visible" | "hidden") =>
    Object.defineProperty(document, "visibilityState", { configurable: true, value });
  const online = (value: boolean) =>
    Object.defineProperty(navigator, "onLine", { configurable: true, value });
  const advance = async (ms: number) => {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  };
  const settle = async () => { await act(async () => { await Promise.resolve(); }); };

  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-11T03:00:00.000Z"));
    visible("visible");
    online(true);
  });
  afterEach(() => {
    cleanup(); // unmount before returning real clocks; cancel pending timers/listeners
    vi.useRealTimers();
    if (originalVisibility) Object.defineProperty(document, "visibilityState", originalVisibility);
    else delete (document as unknown as Record<string, unknown>).visibilityState;
    if (originalOnline) Object.defineProperty(navigator, "onLine", originalOnline);
    else delete (navigator as unknown as Record<string, unknown>).onLine;
  });

  it("starts automatically only after all four selectors and route authorization are complete", async () => {
    const fetch = vi.fn().mockResolvedValue(server());
    const { result, rerender } = renderHook(({ warehouse, allowed }) =>
      useCommercialPreflight({ selection: { ...selection, warehouseId: warehouse },
        actorScope: "company-A:owner", authorized: allowed,
        current: () => true, fetch }), { initialProps: { warehouse: "", allowed: true } });
    expect(result.current.status).toBe("choose");
    expect(fetch).not.toHaveBeenCalled();
    rerender({ warehouse: "20", allowed: true });
    await settle();
    expect(result.current.status).toBe("ready");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("source_location_id=20");
    rerender({ warehouse: "22", allowed: true });
    expect(result.current.canLaunch).toBe(false);
    await settle();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain("source_location_id=22");
    rerender({ warehouse: "22", allowed: false });
    expect(result.current.status).toBe("choose");
    await advance(90_000);
    expect(fetch).toHaveBeenCalledTimes(2);
    rerender({ warehouse: "22", allowed: true });
    await settle();
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("turns genuine blocked published rules into READY within 30 seconds, preserving failure text during refresh", async () => {
    let release!: (value: CommercialPreflight) => void;
    const fetch = vi.fn()
      .mockResolvedValueOnce(server(["tax", "TAX_CONFIGURATION_REQUIRED"]))
      .mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    expect(result.current.status).toBe("blocked");
    expect(result.current.canLaunch).toBe(false);
    await advance(29_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("blocked"); // no polling flash / lost reasons
    await act(async () => { release(server()); });
    expect(result.current.status).toBe("ready");
    expect(result.current.canLaunch).toBe(true);
    await advance(90_000);
    expect(fetch).toHaveBeenCalledTimes(2); // no perpetual READY polling
  });

  it("coalesces focus + visibility + online events into one genuine authorized GET", async () => {
    const fetch = vi.fn().mockResolvedValue(server(["pricing", "PRICE_NOT_RESOLVED"]));
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    await advance(1_300);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("blocked");
    await advance(29_999);
    expect(fetch).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls.every((call) =>
      call[1].method === "GET" && call[1].cache === "no-store")).toBe(true);
  });

  it("stops every timer while hidden, invalidates READY, resumes on visible without a click", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(server())
      .mockResolvedValueOnce(server(["warehouse", "SOURCE_WAREHOUSE_AUDIT_LOCK"]));
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    expect(result.current.canLaunch).toBe(true);
    visible("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(result.current.canLaunch).toBe(false);
    await advance(120_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    visible("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("blocked");
  });

  it("never issues automatic traffic offline and immediately rechecks when connection returns", async () => {
    const fetch = vi.fn().mockResolvedValue(server());
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    online(false);
    act(() => { window.dispatchEvent(new Event("offline")); });
    expect(result.current.canLaunch).toBe(false);
    await advance(120_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    online(true);
    await act(async () => { window.dispatchEvent(new Event("online")); await Promise.resolve(); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe("ready");
  });

  it("errors retry automatically with bounded 60s then 120s backoff and retain manual fallback", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("transient offline"));
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    expect(result.current.status).toBe("error");
    expect(result.current.canLaunch).toBe(false);
    await advance(59_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    await advance(119_999);
    expect(fetch).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(fetch).toHaveBeenCalledTimes(3);
    await act(async () => { result.current.refresh(); await Promise.resolve(); });
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(result.current.status).toBe("error");
  });

  it("fails closed on authentic 403 and never polls or retries after denial", async () => {
    const forbidden = Object.assign(new Error("forbidden"), { status: 403 });
    const fetch = vi.fn().mockRejectedValue(forbidden);
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    expect(result.current.status).toBe("denied");
    await advance(240_000);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("online"));
      await Promise.resolve();
    });
    act(() => { result.current.refresh(); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.current.evidence).toBeNull();
    expect(result.current.canLaunch).toBe(false);
  });

  it("aborts A's old request on company, warehouse and representative change; a late A READY cannot authorize B", async () => {
    let resolveOld!: (value: CommercialPreflight) => void;
    const fetch = vi.fn().mockImplementationOnce(() =>
      new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce(server(["tax", "TAX_CONFIGURATION_REQUIRED"]));
    const { result, rerender } = renderHook(({ actor, wh, driver }) =>
      useCommercialPreflight({ selection: { ...selection, warehouseId: wh, driverId: driver },
        actorScope: actor, authorized: true, current: () => true, fetch }),
    { initialProps: { actor: "A:owner", wh: "20", driver: "9" } });
    expect(fetch).toHaveBeenCalledTimes(1);
    const oldSignal = fetch.mock.calls[0][1].signal as AbortSignal;
    rerender({ actor: "B:limited", wh: "28", driver: "12" });
    await settle();
    expect(oldSignal.aborted).toBe(true);
    expect(fetch.mock.calls[1][0]).toContain("source_location_id=28");
    expect(fetch.mock.calls[1][0]).toContain("driver_id=12");
    await act(async () => { resolveOld(server()); });
    expect(result.current.status).toBe("blocked");
    expect(result.current.evidence?.checks.tax.ready).toBe(false);
    expect(result.current.canLaunch).toBe(false);
  });

  it("final pre-POST read supersedes an in-flight background poll with a NEW no-cache request", async () => {
    let late!: (value: CommercialPreflight) => void;
    const fetch = vi.fn().mockResolvedValueOnce(server(["rounding", "COMMERCIAL_ROUNDING_NOT_CONFIGURED"]))
      .mockImplementationOnce(() => new Promise(resolve => { late = resolve; }))
      .mockResolvedValueOnce(server());
    const { result } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    await advance(30_000);
    expect(fetch).toHaveBeenCalledTimes(2);
    const oldSignal = fetch.mock.calls[1][1].signal as AbortSignal;
    await act(async () => { expect((await result.current.verifyBeforeLaunch())?.ready).toBe(true); });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(oldSignal.aborted).toBe(true);
    expect(fetch.mock.calls[2][1]).toMatchObject({ method: "GET", cache: "no-store" });
    await act(async () => { late(server(["tax", "TAX_CONFIGURATION_REQUIRED"])); });
    expect(result.current.canLaunch).toBe(true);
    expect(result.current.evidence?.checks.rounding.ready).toBe(true);
  });

  it("removes automatic timers/listeners and aborts an unfinished request on unmount", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(server(["tax", "TAX_CONFIGURATION_REQUIRED"]))
      .mockImplementationOnce(() => new Promise(() => {}));
    const { unmount } = renderHook(() => useCommercialPreflight({
      selection, actorScope: "A:owner", authorized: true, current: () => true, fetch,
    }));
    await settle();
    await advance(30_000);
    expect(fetch).toHaveBeenCalledTimes(2);
    const signal = fetch.mock.calls[1][1].signal as AbortSignal;
    unmount();
    expect(signal.aborted).toBe(true);
    await advance(240_000);
    act(() => { window.dispatchEvent(new Event("focus")); });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});


describe("D15 P1 tab selection versus genuine authorization", () => {
  it("keeps the chosen Launch tab selected with the SAME node while all commands remain disabled on reentry", () => {
    const onTabChange = vi.fn();
    const view = render(<DispatchChrome
      activeTab="launch" admitted={true} permissionKnown allowedTabs={["routes", "launch", "zones"]}
      onTabChange={onTabChange} />);
    const launch = screen.getByRole("tab", { name: "إطلاق خط جديد" });
    const routes = screen.getByRole("tab", { name: "الخطوط النشطة" });
    expect(launch).toHaveAttribute("aria-selected", "true");
    expect(launch).not.toBeDisabled();
    view.rerender(<DispatchChrome
      activeTab="launch" admitted={false} permissionKnown={false} allowedTabs={[]}
      onTabChange={onTabChange} />);
    expect(screen.getByRole("tab", { name: "إطلاق خط جديد" })).toBe(launch);
    expect(launch).toHaveAttribute("aria-selected", "true");
    expect(launch).toHaveClass("bg-white");
    expect(launch).toBeDisabled();
    expect(routes).toHaveAttribute("aria-selected", "false");
    fireEvent.click(routes);
    expect(onTabChange).not.toHaveBeenCalled();
    view.rerender(<DispatchChrome
      activeTab="launch" admitted={true} permissionKnown allowedTabs={["routes"]}
      onTabChange={onTabChange} />);
    expect(launch).toHaveAttribute("aria-selected", "true");
    expect(launch).toBeDisabled();
    fireEvent.click(launch);
    expect(onTabChange).not.toHaveBeenCalled();
  });
});
