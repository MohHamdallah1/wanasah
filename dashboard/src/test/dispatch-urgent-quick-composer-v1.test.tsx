import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import type { Shop, Zone } from "@/types/dispatch";
import { ShortageShopPicker } from "@/components/dispatch/ShortageShopPicker";
import { ShortageRequestComposer } from "@/components/dispatch/ShortageRequestComposer";

vi.mock("@/features/dispatch/useShortageVehicleAvailability", () => ({
  useShortageVehicleAvailability: () => ({
    status: "UNKNOWN", reason: "NO_ACCEPTED_VEHICLE_CUSTODY",
    byProduct: new Map(), loading: false, refresh: vi.fn(),
  }),
}));

vi.mock("@/features/dispatch/useDispatchProductWindow", () => ({
  useDispatchProductWindow: () => ({
    mode: "windowed", queryKey: "test-company:search", firstPageReady: true,
    pages: [{ index: 0, items: [{ id: "41", name: "Lolo Chips", load: null }] }],
    items: [{ id: "41", name: "Lolo Chips", load: null }],
    topSpacerHeight: 0, bottomSpacerHeight: 0, loading: false, loadingWindow: false,
    error: null, hasMore: false, hasPrevious: false,
    loadMore: vi.fn(), loadPrevious: vi.fn(), retry: vi.fn(), registerPageHeight: vi.fn(),
  }),
}));

const zones = [
  { id: "11", name: "Zone A" }, { id: "22", name: "Zone B" },
] as Zone[];
const shops = [
  { id: "101", name: "Grocery A", zoneId: "11", owner: "Omar", phone: "123", archived: false },
  { id: "102", name: "Special Grocery", zoneId: "22", owner: "Ali", phone: "456", archived: false },
  { id: "103", name: "Archived Grocery", zoneId: "22", owner: "Hidden", phone: "789", archived: true },
] as Shop[];

beforeEach(async () => { await setAppLanguage("en"); });

describe("V1 urgent shop request single-row layout and fixed scrolling", () => {
  it("selects the authorized zone and shop from native dropdowns, excluding archived shops", () => {
    const onChoose = vi.fn();
    render(<ShortageShopPicker shops={shops} zones={zones} shopId="" zoneId=""
      disabled={false} onChoose={onChoose}/>);
    const zone = screen.getByRole("combobox", { name: "Zone" });
    expect(zone).toHaveValue("");
    fireEvent.change(zone, { target: { value: "22" } });
    expect(onChoose).toHaveBeenLastCalledWith("22", "");
    const shop = screen.getByRole("combobox", { name: /Destination shop/ });
    expect(within(shop).getByRole("option", { name: /Special Grocery/ })).toBeInTheDocument();
    expect(within(shop).queryByRole("option", { name: /Archived Grocery/ })).not.toBeInTheDocument();
  });

  it("adds visible catalog products without typing; keeps all chosen items in the fixed scroll area", () => {
    function Harness() {
      const [selected, setSelected] = useState({ shop: "", zone: "" });
      const [driver, setDriver] = useState("31");
      const [rows, setRows] = useState<{ productId: string; productName: string; quantity: number }[]>([]);
      return <ShortageRequestComposer zones={zones} shops={shops}
        shopId={selected.shop} zoneId={selected.zone}
        onChooseShop={(zone,shop) => setSelected({ zone,shop })}
        drivers={[{ id: "31", name: "Active rep" }]} driverId={driver}
        onDriverChange={setDriver} productScope="1:1:1" draft={rows}
        onQuickAdd={(id,name) => setRows(previous => {
          const index=previous.findIndex(row => row.productId===id);
          return index===-1 ? [...previous,{productId:id,productName:name,quantity:1}] :
            previous.map((row,i) => index===i ? {...row,quantity:row.quantity+1} : row);
        })}
        onUpdateQuantity={(index,qty) => setRows(previous =>
          previous.map((row,i) => index===i ? {...row,quantity:qty} : row))}
        onRemove={index => setRows(previous => previous.filter((_,i)=>i!==index))}
        onClear={() => setRows([])} editing={false} blocked={false}
        allowUnassigned={false} onAllowUnassigned={vi.fn()}/>;
    }
    render(<Harness />);
    const destination = screen.getByRole("combobox", { name: /Destination shop/ });
    fireEvent.change(destination, { target: { value: "101" } });
    expect(screen.getByRole("combobox", { name: "Assign to representative" })).toHaveValue("31");
    const order = screen.getByTestId("shortage-current-order");
    expect(order).toHaveClass("h-60", "flex-col", "overflow-hidden");
    expect(screen.getByText("Lolo Chips")).toBeVisible();
    const add = screen.getByRole("button", { name: "Add one unit of Lolo Chips to request" });
    fireEvent.click(add);
    fireEvent.click(add);
    expect(screen.getByRole("spinbutton", { name: "Quantity of Lolo Chips" })).toHaveValue(2);
    const scroller = order.querySelector(".min-h-0.flex-1.overflow-y-auto");
    expect(scroller).toBeInTheDocument();
    expect(scroller).toHaveClass("overscroll-contain");
    fireEvent.click(screen.getByRole("button", { name: "Remove Lolo Chips from request" }));
    expect(screen.queryByRole("spinbutton", { name: "Quantity of Lolo Chips" })).not.toBeInTheDocument();
    expect(order).toHaveClass("h-60");
  });

  it("keeps the existing shop and representative fixed when editing a grouped request", () => {
    render(<ShortageRequestComposer zones={zones} shops={shops} shopId="102" zoneId="22"
      onChooseShop={vi.fn()} drivers={[{id:"31",name:"Active rep"}]} driverId="31"
      onDriverChange={vi.fn()} productScope="1:1:1"
      draft={[{productId:"41",productName:"Lolo Chips",quantity:3}]}
      onQuickAdd={vi.fn()} onUpdateQuantity={vi.fn()} onRemove={vi.fn()} onClear={vi.fn()}
      editing blocked={false} allowUnassigned={false} onAllowUnassigned={vi.fn()}/>);
    expect(screen.getByRole("combobox", { name: "Zone" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: /Destination shop/ })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Assign to representative" })).toBeDisabled();
    expect(screen.getByText(/Edit mode/)).toBeVisible();
  });
});
