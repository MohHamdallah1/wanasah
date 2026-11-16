import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import type { Shop, Zone } from "@/types/dispatch";
import { ShortageShopPicker } from "@/components/dispatch/ShortageShopPicker";
import { ShortageRequestComposer } from "@/components/dispatch/ShortageRequestComposer";

vi.mock("@/features/dispatch/useDispatchProductSearch", () => ({
  useDispatchProductSearch: (_endpoint: string | null, query: string) => ({
    mode: "paged",
    items: query.trim().length >= 2 ? [{ id: "41", name: "Lolo Chips", load: null }] : [],
    loading: false, error: null, searchRequired: true, hasMore: false,
    hasPrevious: false, pageNumber: 1, loadMore: vi.fn(), previous: vi.fn(), retry: vi.fn(),
  }),
}));

const zones = [
  { id: "11", name: "Zone A" },
  { id: "22", name: "Zone B" },
] as Zone[];
const shops = [
  { id: "101", name: "Grocery A", zoneId: "11", owner: "Omar", phone: "123",
    archived: false },
  { id: "102", name: "Special Grocery", zoneId: "22", owner: "Ali", phone: "456",
    archived: false },
  { id: "103", name: "Archived Grocery", zoneId: "22", owner: "Hidden", phone: "789",
    archived: true },
] as Shop[];

beforeEach(async () => { await setAppLanguage("en"); });

describe("V1 urgent shop request quick composer", () => {
  it("searches shops across the authorized company rather than the current zone, deriving actual zone", () => {
    const onChoose = vi.fn();
    render(<ShortageShopPicker shops={shops} zones={zones} shopId="" zoneId=""
      disabled={false} onChoose={onChoose}/>);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search shop name, phone, or zone" }),
      { target: { value: "Special" } });
    expect(screen.getByText(/Zone B/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Special Grocery/ }));
    expect(onChoose).toHaveBeenCalledExactlyOnceWith("22", "102");
    expect(screen.queryByText("Archived Grocery")).not.toBeInTheDocument();
  });

  it("adds the searched product with one click, keeps one quantity row, and only submits valid shop + draft", () => {
    const send = vi.fn();
    function Harness() {
      const [selected, setSelected] = useState({ shop: "", zone: "" });
      const [draft, setDraft] = useState<{ productId: string; productName: string; quantity: number }[]>([]);
      return <ShortageRequestComposer zones={zones} shops={shops} shopId={selected.shop}
        zoneId={selected.zone} onChooseShop={(zone, shop) => setSelected({ shop, zone })}
        drivers={[{ id: "31", name: "Active rep" }]} driverId=""
        onDriverChange={vi.fn()} productScope="1:1:1" draft={draft}
        onQuickAdd={(id, name) => setDraft(rows => {
          const index = rows.findIndex(row => row.productId === id);
          return index === -1 ? [...rows, { productId: id, productName: name, quantity: 1 }]
            : rows.map((row, i) => i === index ? { ...row, quantity: row.quantity + 1 } : row);
        })}
        onUpdateQuantity={(index, qty) => setDraft(rows => rows.map((row, i) =>
          index === i ? { ...row, quantity: qty } : row))}
        onRemove={index => setDraft(rows => rows.filter((_, i) => index !== i))}
        onClear={() => setDraft([])} onSubmit={send} editing={false}
        onCancelEdit={vi.fn()} blocked={false}/>;
    }
    render(<Harness />);
    expect(screen.getByRole("button", { name: "Save request (0 items)" })).toBeDisabled();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search shop name, phone, or zone" }),
      { target: { value: "Special" } });
    fireEvent.click(screen.getByRole("button", { name: /Special Grocery/ }));
    expect(screen.getByText(/Zone B/)).toBeVisible();

    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }),
      { target: { value: "Lo" } });
    const quickAdd = screen.getByRole("button", { name: "Add one unit of Lolo Chips to request" });
    fireEvent.click(quickAdd);
    expect(screen.getByRole("spinbutton", { name: "Quantity of Lolo Chips" })).toHaveValue(1);
    fireEvent.click(quickAdd);
    expect(screen.getByRole("spinbutton", { name: "Quantity of Lolo Chips" })).toHaveValue(2);
    expect(screen.getByRole("button", { name: "Save request (1 items)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Save request (1 items)" }));
    expect(send).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Remove Lolo Chips from draft" }));
    expect(screen.getByRole("button", { name: "Save request (0 items)" })).toBeDisabled();
  });

  it("keeps the existing shop identity fixed in group edit mode", () => {
    render(<ShortageRequestComposer zones={zones} shops={shops} shopId="102" zoneId="22"
      onChooseShop={vi.fn()} drivers={[]} driverId="" onDriverChange={vi.fn()}
      productScope="1:1:1" draft={[{ productId: "41", productName: "Lolo Chips", quantity: 3 }]}
      onQuickAdd={vi.fn()} onUpdateQuantity={vi.fn()} onRemove={vi.fn()} onClear={vi.fn()}
      onSubmit={vi.fn()} editing onCancelEdit={vi.fn()} blocked={false}/>);
    expect(screen.getByText("Special Grocery")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Change shop" })).not.toBeInTheDocument();
    expect(screen.getByText(/Edit mode/)).toBeInTheDocument();
  });
});
