import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { PREFLIGHT_AREAS, parseCommercialPreflight, preflightReason,
  preflightUrl, type CommercialPreflight } from
  "@/features/dispatch/commercialPreflight/contract";
import { useCommercialPreflight } from
  "@/features/dispatch/commercialPreflight/useCommercialPreflight";
import { CommercialPreflightPanel } from
  "@/features/dispatch/commercialPreflight/CommercialPreflightPanel";

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
    expect(screen.getByRole("link", { name: "اذهب للإعداد" })).toHaveAttribute("href", "/commercial-rules");
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
    expect(screen.getByRole("link", { name: "Open settings" })).toHaveAttribute("href", "/products");
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

  it("hides the entire empty card and explanatory text before all selections exist", () => {
    const view = renderPanel("choose", "ar", server());
    expect(view.container).toBeEmptyDOMElement();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a neutral inline busy indicator with live status, not a header or card", () => {
    const view = renderPanel("loading");
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("status")).toHaveTextContent("جاري التحقق");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(view.container.querySelector(".shadow-sm, .rounded-2xl, .border-slate-200"))
      .not.toBeInTheDocument();
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
      expect(screen.getByRole("list").querySelectorAll("li")).toHaveLength(6);
      expect(screen.getByText(/نسبة 0% المنشورة صالحة/)).toBeInTheDocument();
      expect(screen.getByText(/جرد شامل/)).toBeInTheDocument();
      expect(screen.getAllByText(/عهدة المركبة/).length).toBeGreaterThan(0);
      expect(screen.getAllByRole("link", { name: "اذهب للإعداد" })
        .map(a => a.getAttribute("href"))).toEqual([
          "/products", "/commercial-rules", "/commercial-rules", "/inventory",
          "/representatives-vehicles", "/representatives-vehicles",
        ]);
      expect(view.container.querySelector("section")).toHaveAttribute("dir", "rtl");
      expect(view.container.querySelector("ul")).toHaveClass("min-w-0");
      expect(view.container.textContent).not.toContain("PRICE_NOT_RESOLVED");
      fireEvent.click(screen.getByRole("button", { name: "إعادة التحقق" }));
      expect(retry).toHaveBeenCalledOnce();
    } finally {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: priorWidth });
    }
  });

  it("EN LTR preserves specific failed tax and custody reasons and keyboard focus", () => {
    const view = renderPanel("blocked", "en", blockers({
      tax: "TAX_CONFIGURATION_REQUIRED", custody: "VEHICLE_CUSTODY_LOCATION_MISSING",
    }));
    expect(view.container.querySelector("section")).toHaveAttribute("dir", "ltr");
    expect(screen.getByRole("status")).toHaveTextContent("Launch is blocked");
    expect(screen.getByText(/published 0% tax is valid/)).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Open settings" });
    expect(links).toHaveLength(2);
    links[0].focus();
    expect(links[0]).toHaveFocus();
    expect(screen.getByRole("button", { name: "Recheck readiness" })).toBeEnabled();
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
