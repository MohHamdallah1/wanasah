import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { RouteLoadProductTable } from "@/components/dispatch/RouteLoadProductTable";
import type { RouteLoadUom } from "@/features/dispatch/routeLoadUom";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
const signedSession = vi.hoisted(() => ({
  current: null as { generation: string; identity: string } | null,
}));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => api.fetch }));
vi.mock("@/hooks/useDashboardSession", () => ({ useDashboardSession: () => signedSession.current }));
const unit: RouteLoadUom = {
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "Each",
  quantity_scale: 0, quantity_step: "1", display_uom_name: "Each", display_factor_to_base: "1",
};
const warehouseProducts = Array.from({ length: 80 }, (_, i) => ({
  id: String(1000 + i), name: "Warehouse " + (i + 1),
  load: { ...unit, product_id: String(1000 + i), product_name: "Warehouse " + (i + 1),
    current_base_quantity: "0", reserved_base_quantity: "0", pending_base_quantity: "0" },
}));
type Response = { items: typeof warehouseProducts; next_cursor: string | null; has_more: boolean };
function response(items = warehouseProducts, next_cursor: string | null = "page2"): Response {
  return { items, next_cursor, has_more: !!next_cursor };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const fakeObservers: Array<{ node: Element; observer: IntersectionObserver; callback: IntersectionObserverCallback }> = [];
class FakeObserver {
  root = null; rootMargin = "0px"; thresholds = [0];
  constructor(private callback: IntersectionObserverCallback) {}
  observe = (node: Element) => fakeObservers.push({
    node, callback: this.callback, observer: this as unknown as IntersectionObserver,
  });
  unobserve = () => {};
  disconnect = () => {};
  takeRecords = () => [];
}
function Product({ ready, vehicle = "17", warehouse = "21", scope = "company:one",
  carId = "9000", carName = "Car custody", pending = false }: {
  ready: boolean; vehicle?: string; warehouse?: string; scope?: string;
  carId?: string; carName?: string; pending?: boolean;
}) {
  return <div data-testid="dispatch-launch-workspace">
    <RouteLoadProductTable vehicleId={vehicle} warehouseId={warehouse} scope={scope}
      current={{ [carId]: "4" }} targets={{}} names={{ [carId]: carName }}
      units={{ [carId]: unit }} custodyReady={ready} pending={pending}
      onClear={vi.fn()} onRestoreClear={vi.fn()} onTargetChange={vi.fn()} />
  </div>;
}
const rows = () => [...document.querySelectorAll<HTMLTableRowElement>("[data-product-id]")];
beforeEach(async () => {
  api.fetch.mockReset();
  signedSession.current = null;
  fakeObservers.length = 0;
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  await setAppLanguage("en");
});
describe("D17 joined first window, actual API-shaped deferred responses", () => {
  for (const order of ["vehicle-first", "warehouse-first"] as const) {
    it("never paints a custody-only or warehouse-only frame (" + order + "); commits real 80+car in ONE reveal", async () => {
      const initial = deferred<Response>();
      api.fetch.mockReturnValueOnce(initial.promise);
      const view = render(<Product ready={false} />);
      await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
      expect(rows()).toHaveLength(0);
      expect(screen.getByTestId("dispatch-first-window-pending")).toBeInTheDocument();

      if (order === "vehicle-first") {
        view.rerender(<Product ready />);
        expect(rows()).toHaveLength(0);
        await act(async () => initial.resolve(response()));
      } else {
        await act(async () => initial.resolve(response()));
        expect(rows()).toHaveLength(0);
        view.rerender(<Product ready />);
      }
      await waitFor(() => expect(rows()).toHaveLength(81));
      expect(rows()[0]).toHaveTextContent("Car custody");
      expect(rows()[1]).toHaveTextContent("Warehouse 1");
      expect(rows()[80]).toHaveTextContent("Warehouse 80");
      expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "true");
      expect(api.fetch.mock.calls[0][0]).toContain("limit=80");
      expect(api.fetch).toHaveBeenCalledTimes(1);

      // An early visible bottom sentinel must not opportunistically fetch next 80.
      const bottom = await waitFor(() => {
        const el = document.querySelector('[data-window-boundary="bottom"]');
        const obs = [...fakeObservers].reverse().find(o => o.node === el);
        if (!obs) throw new Error("sentinel not subscribed");
        return obs;
      });
      act(() => bottom.callback([{ target: bottom.node, isIntersecting: true } as IntersectionObserverEntry], bottom.observer));
      expect(api.fetch).toHaveBeenCalledTimes(1);
      const workspace = screen.getByTestId("dispatch-launch-workspace");
      fireEvent.wheel(workspace, { deltaY: 125 });
      await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(2));
      expect(api.fetch.mock.calls[1][0]).toContain("cursor=page2");
    });
  }

  it("signed empty first page is READY with car pins, without false no-products", async () => {
    api.fetch.mockResolvedValue(response([], null));
    render(<Product ready />);
    await screen.findByText("Car custody");
    expect(rows()).toHaveLength(1);
    expect(screen.queryByText("No products found")).not.toBeInTheDocument();
    expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "true");
    expect(api.fetch).toHaveBeenCalledTimes(1);
  });

  it("initial discovery failure is not signed readiness, exposes retry, never draws custody", async () => {
    const initial = deferred<Response>();
    api.fetch.mockReturnValueOnce(initial.promise).mockResolvedValueOnce(response());
    render(<Product ready />);
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    await act(async () => initial.reject(new Error("HTTP 403 access denied")));
    expect(rows()).toHaveLength(0);
    expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "false");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));
    await screen.findByText("Warehouse 80");
    expect(rows()).toHaveLength(81);
  });

  it("invalidates wrong warehouse/actor and late stale 80 without showing old car or products", async () => {
    const old = deferred<Response>(), newer = deferred<Response>();
    api.fetch.mockImplementation((url: string) => url.includes("warehouse_id=21") ? old.promise : newer.promise);
    const view = render(<Product ready carName="OLD CAR" />);
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    view.rerender(<Product ready={false} warehouse="22" scope="company:two" carName="NEW CAR" />);
    expect(rows()).toHaveLength(0);
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(2));
    await act(async () => old.resolve(response()));
    expect(rows()).toHaveLength(0);
    await act(async () => newer.resolve(response()));
    expect(rows()).toHaveLength(0);
    view.rerender(<Product ready warehouse="22" scope="company:two" carName="NEW CAR" />);
    await screen.findByText("Warehouse 80");
    expect(rows()).toHaveLength(81);
    expect(screen.queryByText("OLD CAR")).not.toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent("NEW CAR");
    expect(api.fetch.mock.calls[1][0]).toContain("warehouse_id=22");
  });

  it("no duplicate when a car pin is also in the first signed page; unchanged-context SPA rerender does not refetch", async () => {
    api.fetch.mockResolvedValue(response());
    const view = render(<Product ready carId="1000" carName="Pinned warehouse duplicate" />);
    await screen.findByText("Warehouse 80");
    expect(rows()).toHaveLength(80);
    expect(rows().filter(row => row.dataset.productId === "1000")).toHaveLength(1);
    view.rerender(<Product ready carId="1000" carName="Pinned warehouse duplicate" />);
    expect(rows()).toHaveLength(80);
    expect(api.fetch).toHaveBeenCalledTimes(1);
  });

  it("pending tab with signed response never paints a partial row or zero", async () => {
    api.fetch.mockResolvedValue(response());
    const view = render(<Product ready pending />);
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "false"));
    expect(rows()).toHaveLength(0);
    view.rerender(<Product ready pending={false} />);
    await screen.findByText("Warehouse 80");
    expect(rows()).toHaveLength(81);
  });

  it("retains a signed first window across tab unmount, but never across login generations", async () => {
    signedSession.current = { generation: "d18-session-one", identity: "company:actor-one" };
    api.fetch.mockResolvedValue(response(warehouseProducts.slice(0, 2), null));
    const first = render(<Product ready />);
    await screen.findByText("Warehouse 1");
    expect(api.fetch).toHaveBeenCalledTimes(1);
    first.unmount();

    const sameSession = render(<Product ready />);
    expect(screen.getByText("Warehouse 1")).toBeInTheDocument();
    await act(async () => { await Promise.resolve(); });
    expect(api.fetch).toHaveBeenCalledTimes(1);
    sameSession.unmount();

    signedSession.current = { generation: "d18-session-two", identity: "company:actor-one" };
    const newLogin = render(<Product ready />);
    expect(screen.queryByText("Warehouse 1")).not.toBeInTheDocument();
    await waitFor(() => expect(api.fetch).toHaveBeenCalledTimes(2));
    await screen.findByText("Warehouse 1");
    newLogin.unmount();
  });
});
