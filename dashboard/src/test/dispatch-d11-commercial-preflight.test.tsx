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
