import { useState, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { RouteLoadProductTable } from "@/components/dispatch/RouteLoadProductTable";
import { RouteManagementModal } from "@/components/dispatch/RouteManagementModal";
import { ShortageProductPicker } from "@/components/dispatch/ShortageProductPicker";
import { parseDispatchProductPage } from "@/features/dispatch/useDispatchProductSearch";
import type { RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import type { PendingRoute } from "@/types/dispatch";

const fake = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/components/ui/modal", () => ({ Modal: ({ children, isOpen }: { children: ReactNode; isOpen: boolean }) =>
  isOpen ? <div role="dialog">{children}</div> : null }));
const unit: RouteLoadUom = { base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH", quantity_scale: 0,
  quantity_step: "1", display_uom_name: "PACK", display_factor_to_base: "8" };
const products = Array.from({ length: 200 }, (_, index) => {
  const id = String(index + 1000), name = `Matching ${index + 1}`;
  return { id, name, load: { ...unit, product_id: id, product_name: name, current_base_quantity: "0",
    reserved_base_quantity: "0", pending_base_quantity: "0" } };
});
const route = { id: "9", driverId: "31", driverName: "Rep", vehicleId: "17", sessionBound: false, sessionEnded: false } as PendingRoute;
beforeEach(async () => {
  await setAppLanguage("en"); fake.fetch.mockReset();
  fake.fetch.mockImplementation(async (url: string) => {
    const params = new URL(url, "http://test").searchParams;
    const cursor = params.get("cursor");
    const start = cursor === "p3" ? 160 : cursor === "p2" ? 80 : 0;
    const next_cursor = start === 160 ? null : start === 80 ? "p3" : "p2";
    return { items: products.slice(start, start + 80).map((product) => params.get("purpose") === "SHORTAGE"
      ? { ...product, load: null } : product), next_cursor, has_more: !!next_cursor };
  });
});
async function lastPage(search = false) {
  if (search) fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "Matching" } });
  await screen.findByText("Matching 1");
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("Matching 160");
  expect(screen.queryByText("Matching 1")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("Matching 200");
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  expect(fake.fetch.mock.calls).toHaveLength(3);
  expect(fake.fetch.mock.calls.every(([url]) => url.includes("limit=80"))).toBe(true);
}

describe("Dispatch cursor pickers", () => {
  it("Route Launch reaches result 200, preserves exact target/UOM and pins across previous/search", async () => {
    const changed = vi.fn();
    function Launch() {
      const [targets, setTargets] = useState<Record<string, string>>({});
      const [units, setUnits] = useState<Record<string, RouteLoadUom>>({});
      const [names, setNames] = useState<Record<string, string>>({});
      return <RouteLoadProductTable vehicleId="17" warehouseId="21" scope="1:3" current={{}} targets={targets} units={units} names={names}
        onClear={() => setTargets({})} onTargetChange={(id, name, metadata, value) => {
          setTargets((v) => ({ ...v, [id]: value })); setUnits((v) => ({ ...v, [id]: metadata }));
          setNames((v) => ({ ...v, [id]: name })); changed(id, value);
        }} />;
    }
    render(<Launch />);
    await lastPage();
    expect(screen.getAllByRole("row")).toHaveLength(41);
    const input = screen.getByRole("textbox", { name: /Target.*Matching 200/ });
    fireEvent.change(input, { target: { value: "25" } });
    expect(changed).toHaveBeenLastCalledWith("1199", "25");
    expect(within(input.closest("tr")!).getAllByText("3 PACK + 1 EACH")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Previous results" }));
    await screen.findByText("Matching 160");
    expect(screen.getByRole("textbox", { name: /Target.*Matching 200/ })).toHaveValue("25");
    expect(screen.getAllByRole("row")).toHaveLength(82);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "Matching" } });
    await screen.findByText("Matching 1");
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "" } });
    await screen.findByText("Matching 1");
    expect(screen.getAllByRole("row")).toHaveLength(82);
    expect(screen.getByText("Matching 200")).toBeVisible();
    expect(fake.fetch.mock.calls[0][0]).toContain("purpose=LOAD&vehicle_id=17&warehouse_id=21");
  });

  it("Route Management searches route/source context and retains selected target outside the window", async () => {
    const changed = vi.fn();
    function Management() {
      const [targets, setTargets] = useState<Record<string, number>>({});
      return <RouteManagementModal isOpen onClose={vi.fn()} routeModalType="follow_up" activeRoute={route} drivers={[]}
        transferDriverId="" onTransferDriverChange={vi.fn()} vehicles={[]} selectedVehicleId="17" onVehicleChange={vi.fn()}
        productScope="1:3" productNames={{}} preloadQuantities={targets} onPreloadQuantitiesChange={(value) => { setTargets(value); changed(value); }}
        onClearInventory={vi.fn()} onConfirmAction={vi.fn()} />;
    }
    render(<Management />);
    await lastPage();
    const row = screen.getByText("Matching 200").closest("tr")!;
    const input = within(row).getByRole("textbox");
    fireEvent.change(input, { target: { value: "2" } }); fireEvent.blur(input);
    expect(changed).toHaveBeenLastCalledWith({ "1199": 2 });
    fireEvent.click(screen.getByRole("button", { name: "Previous results" }));
    await screen.findByText("Matching 160");
    expect(within(screen.getByText("Matching 200").closest("tr")!).getByRole("textbox")).toHaveValue("2");
    expect(screen.getAllByRole("row")).toHaveLength(82);
    expect(fake.fetch.mock.calls[0][0]).toContain("purpose=LOAD&route_id=9&vehicle_id=17");
  });

  it("Shortages reach result 200 without stock metadata and pin selected plus drafted choices", async () => {
    const select = vi.fn();
    function Shortages() {
      const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
      return <ShortageProductPicker scope="1:3" selected={selected} drafted={[{ productId: "521", productName: "Drafted demand" }]}
        onSelect={(id, name) => { setSelected({ id, name }); select(id, name); }} />;
    }
    render(<Shortages />);
    expect(screen.getByText("Drafted demand")).toBeVisible();
    expect(fake.fetch).not.toHaveBeenCalled();
    await lastPage(true);
    fireEvent.click(screen.getByRole("button", { name: "Select Matching 200" }));
    expect(select).toHaveBeenCalledWith("1199", "Matching 200");
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "" } });
    expect(screen.getByText("Drafted demand")).toBeVisible();
    expect(screen.getByRole("button", { name: "Select Matching 200" })).toHaveAttribute("aria-pressed", "true");
    expect(fake.fetch.mock.calls[0][0]).toContain("purpose=SHORTAGE");
  });

  it("invalidates a continuation when source changes and does not search blank context", async () => {
    const props = { scope: "1:3", current: {}, targets: {}, units: {}, names: {}, onTargetChange: vi.fn(), onClear: vi.fn() };
    const view = render(<RouteLoadProductTable {...props} vehicleId="" warehouseId="" />);
    expect(screen.getByRole("textbox", { name: "Search products" })).toBeDisabled();
    expect(fake.fetch).not.toHaveBeenCalled();
    view.rerender(<RouteLoadProductTable {...props} vehicleId="17" warehouseId="21" />);
    await lastPage();
    view.rerender(<RouteLoadProductTable {...props} vehicleId="17" warehouseId="22" />);
    await waitFor(() => expect(fake.fetch).toHaveBeenCalledTimes(4));
    expect(fake.fetch.mock.calls[3][0]).toContain("warehouse_id=22");
    expect(fake.fetch.mock.calls[3][0]).not.toContain("cursor=");
  });

  it.each(["launch", "management"])("%s pins custody and drafts before stock rows, retaining them after stock disappears without duplicates", async (kind) => {
    const current = { id: "521", name: "Vehicle A with zero source stock", load: { ...products[0].load, product_id: "521", product_name: "Vehicle A with zero source stock", current_base_quantity: "25" } };
    fake.fetch.mockImplementation(async (url: string) => ({ items: new URL(url, "http://test").searchParams.get("search") ? [current] : [products[0]], has_more: false, next_cursor: null }));
    function Pinned() {
      const [quantities, setQuantities] = useState<Record<string, number>>({});
      const [targets, setTargets] = useState<Record<string, string>>({});
      const [names, setNames] = useState<Record<string, string>>({ "521": current.name });
      return kind === "launch" ? <RouteLoadProductTable vehicleId="17" warehouseId="21" scope="1:3"
        current={{ "521": "25" }} targets={targets} units={{ "521": unit, "1000": unit }} names={names}
        onClear={() => setTargets({})} onTargetChange={(id, name, metadata, value) => { setTargets((q) => ({ ...q, [id]: value })); setNames((n) => ({ ...n, [id]: name })); }} />
        : <RouteManagementModal isOpen onClose={vi.fn()} routeModalType="follow_up" activeRoute={route} drivers={[]}
          transferDriverId="" onTransferDriverChange={vi.fn()} vehicles={[]} selectedVehicleId="17" onVehicleChange={vi.fn()}
          productScope="1:3" productNames={names} custodyProductIds={["521"]} preloadQuantities={quantities}
          onPreloadQuantitiesChange={setQuantities} onClearInventory={() => setQuantities({})} onConfirmAction={vi.fn()} />;
    }
    render(<Pinned />);
    await screen.findByText("Matching 1");
    expect(screen.getAllByRole("row")[1]).toHaveTextContent(current.name);
    expect(screen.queryByText("Zero stock C")).not.toBeInTheDocument();
    const input = within(screen.getByText("Matching 1").closest("tr")!).getByRole("textbox");
    fireEvent.change(input, { target: { value: "5" } }); fireEvent.blur(input);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "changed" } });
    await waitFor(() => expect(fake.fetch.mock.calls.some(([url]) => url.includes("search=changed"))).toBe(true));
    await waitFor(() => expect(screen.getByText("End of results. Selected products stay visible when searching or changing pages.")).toBeVisible());
    expect(screen.getAllByText(current.name)).toHaveLength(1);
    expect(screen.getByText("Matching 1")).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(within(screen.getByText("Matching 1").closest("tr")!).getByRole("textbox")).toHaveValue("5");
    fireEvent.click(screen.getByRole("button", { name: "Clear all quantities" }));
    expect(screen.getByText(current.name)).toBeVisible();
  });

  it("rejects duplicate or oversized pages and missing load metadata", () => {
    expect(() => parseDispatchProductPage({ items: [products[0], products[0]], has_more: false, next_cursor: null })).toThrow();
    expect(() => parseDispatchProductPage({ items: products.slice(0, 81), has_more: false, next_cursor: null })).toThrow();
    expect(() => parseDispatchProductPage({ items: [{ ...products[0], load: null }], has_more: false, next_cursor: null })).toThrow();
    expect(parseDispatchProductPage({ items: [{ ...products[0], load: null }], has_more: false, next_cursor: null }, "SHORTAGE").items).toHaveLength(1);
  });
});
