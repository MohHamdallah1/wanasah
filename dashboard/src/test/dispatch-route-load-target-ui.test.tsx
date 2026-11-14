import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RouteLoadProductTable } from "@/components/dispatch/RouteLoadProductTable";
import { INVALID_ROUTE_LOAD_TARGET, buildRouteLoadBaseTargets, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import { setAppLanguage } from "@/i18n";

const api = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => api.fetch }));
class ObserverStub {
  readonly root = null;
  readonly rootMargin = "1200px 0px";
  readonly thresholds = [0];
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return []; }
  constructor(_callback: IntersectionObserverCallback) { void _callback; }
}
const unit = (display: string | null, factor: string | null, scale = 0, step = "1"): RouteLoadUom => ({
  base_uom_id: 1, base_uom_code: "EACH", base_uom_name: "EACH",
  quantity_scale: scale, quantity_step: step,
  display_uom_name: display, display_factor_to_base: factor,
});
type Item = { id: string; name: string; metadata: RouteLoadUom; current: string; target: string };
const item = (name: string | null, factor: string | null, current: string, target: string,
  id = "1000", scale = 0, step = "1"): Item => ({
  id, name: "SKU " + id, metadata: unit(name, factor, scale, step), current, target,
});
function Fixture({ rows }: { rows: Item[] }) {
  const [targets, setTargets] = useState<Record<string, string>>(
    () => Object.fromEntries(rows.map(x => [x.id, x.target])),
  );
  const [units, setUnits] = useState<Record<string, RouteLoadUom>>(
    () => Object.fromEntries(rows.map(x => [x.id, x.metadata])),
  );
  const [names, setNames] = useState<Record<string, string>>(
    () => Object.fromEntries(rows.map(x => [x.id, x.name])),
  );
  return <div data-testid="dispatch-launch-workspace">
    <RouteLoadProductTable scope="1:3:4" vehicleId="17" warehouseId="21" intentScope="zone1:driver1"
      current={Object.fromEntries(rows.map(x => [x.id, x.current]))}
      targets={targets} units={units} names={names}
      onClear={() => setTargets({})} onRestoreClear={setTargets}
      onTargetChange={(id, name, metadata, base) => {
        setTargets(prev => ({ ...prev, [id]: base }));
        setUnits(prev => ({ ...prev, [id]: metadata }));
        setNames(prev => ({ ...prev, [id]: name }));
      }} />
    <output data-testid="u02-targets">{JSON.stringify(targets)}</output>
    <button type="button" data-testid="u02-launch"
      disabled={Object.values(targets).includes(INVALID_ROUTE_LOAD_TARGET)}
      onClick={() => { buildRouteLoadBaseTargets(targets, units); }}>Launch</button>
  </div>;
}
const tr = (id = "1000") => screen.getByText("SKU " + id).closest("tr")!;
const input = (kind: "display" | "base", id = "1000") =>
  tr(id).querySelector<HTMLInputElement>('input[data-route-target-input="' + kind + '"]');
const base = (id = "1000") => JSON.parse(screen.getByTestId("u02-targets").textContent || "{}")[id] as string | undefined;
async function ready() {
  await waitFor(() => expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "true"));
}
beforeEach(async () => {
  api.fetch.mockReset();
  api.fetch.mockResolvedValue({ items: [], has_more: false, next_cursor: null });
  vi.stubGlobal("IntersectionObserver", ObserverStub);
  await setAppLanguage("en");
});

describe("U02 dual largest-UOM target only; BASE warehouse/vehicle authority unchanged", () => {
  it.each([
    ["CARTON","50","1250","25",""],
    ["CARTON","50","1253","25","3"],
    ["PALLET","4800","9607","2","7"],
    ["PACK","8","25","3","1"],
  ])("prefills %s/%s from canonical %s without stock POST", async (display,factor,target,outer,rest) => {
    render(<Fixture rows={[item(display,factor,"10",target)]} />);
    await ready();
    expect(input("display")).toHaveValue(outer);
    expect(input("base")).toHaveValue(rest);
    expect(base()).toBe(target);
    expect(tr()).toHaveTextContent(display);
    expect(tr()).toHaveTextContent("EACH");
    expect(api.fetch.mock.calls.every(([url]: [string]) => !url.includes("/dispatch/route"))).toBe(true);
  });
  it("updates desired TOTAL not delta; instantly reviews LOAD/UNLOAD and zero", async () => {
    render(<Fixture rows={[item("CARTON","50","1300","1253")]} />);
    await ready();
    expect(tr()).toHaveTextContent("Return from vehicle");
    fireEvent.change(input("display")!, { target: { value:"26" } });
    expect(base()).toBe("1303");
    expect(tr()).toHaveTextContent("Load from selected warehouse");
    fireEvent.change(input("base")!, { target: { value:"0" } });
    expect(base()).toBe("1300");
    expect(tr()).toHaveTextContent("No movement");
  });
  it("has ONE labelled control for base only and allows full vehicle unload", async () => {
    render(<Fixture rows={[item(null,null,"25","25")]} />);
    await ready();
    expect(input("display")).toBeNull();
    expect(input("base")).toHaveValue("25");
    fireEvent.change(input("base")!,{target:{value:""}});
    expect(base()).toBe("0");
    expect(tr()).toHaveTextContent("Return from vehicle");
  });
  it("invalid partial input preserves draft, shows local error and blocks launch", async () => {
    render(<Fixture rows={[item("CARTON","50","10","1253")]} />);
    await ready();
    fireEvent.change(input("base")!,{target:{value:"50"}});
    expect(input("base")).toHaveValue("50");
    expect(input("base")).toHaveAttribute("aria-invalid","true");
    expect(within(tr()).getByRole("alert")).toHaveTextContent("Remainder must be less");
    expect(base()).toBe(INVALID_ROUTE_LOAD_TARGET);
    expect(screen.getByTestId("u02-launch")).toBeDisabled();
    fireEvent.change(input("base")!,{target:{value:"3"}});
    expect(base()).toBe("1253");
    fireEvent.change(input("display")!,{target:{value:"2.5"}});
    expect(input("display")).toHaveValue("2.5");
    expect(screen.getByTestId("u02-launch")).toBeDisabled();
    expect(within(tr()).getByRole("alert")).toHaveTextContent("whole number");
    fireEvent.change(input("display")!,{target:{value:"25"}});
    expect(base()).toBe("1253");
    expect(screen.getByTestId("u02-launch")).toBeEnabled();
  });
  it("fractional precision/step + Arabic and Persian input digits stay EXACT", async () => {
    render(<Fixture rows={[item("PACK","8","20.25","20.25","1000",2,"0.25")]} />);
    await ready();
    expect(input("display")).toHaveValue("2");
    expect(input("base")).toHaveValue("4.25");
    fireEvent.change(input("base")!,{target:{value:"4.1"}});
    expect(base()).toBe(INVALID_ROUTE_LOAD_TARGET);
    fireEvent.change(input("base")!,{target:{value:"٤٫٢٥"}});
    expect(base()).toBe("20.25");
    fireEvent.change(input("display")!,{target:{value:"۳"}});
    expect(base()).toBe("28.25");
    expect(input("display")).toHaveValue("۳");
  });
  it("blocks an already edited draft when the authenticated SKU conversion changes mid-edit", async () => {
    function ChangingUnit() {
      const [metadata, setMetadata] = useState(unit("CARTON", "50"));
      const [targets, setTargets] = useState<Record<string, string>>({ "1000": "1253" });
      return <>
        <button onClick={() => setMetadata(unit("CARTON", "80"))}>New unit definition</button>
        <RouteLoadProductTable scope="1:3:4" intentScope="zone1:driver1"
          vehicleId="17" warehouseId="21" current={{ "1000": "25" }}
          targets={targets} units={{ "1000": metadata }} names={{ "1000": "SKU 1000" }}
          onClear={() => setTargets({})} onRestoreClear={setTargets}
          onTargetChange={(id, _name, _metadata, value) =>
            setTargets(previous => ({ ...previous, [id]: value }))} />
        <output data-testid="changing-uom-target">{targets["1000"]}</output>
      </>;
    }
    render(<ChangingUnit />);
    await ready();
    fireEvent.change(input("base")!, { target: { value: "4" } });
    expect(screen.getByTestId("changing-uom-target")).toHaveTextContent("1254");
    fireEvent.click(screen.getByRole("button", { name: "New unit definition" }));
    await waitFor(() => expect(screen.getByTestId("changing-uom-target"))
      .toHaveTextContent(INVALID_ROUTE_LOAD_TARGET));
    expect(input("base")).toHaveAttribute("aria-invalid", "true");
    expect(within(tr()).getByRole("alert")).toBeVisible();
    // Only an explicit replacement under the NEW verified factor can recover.
    fireEvent.change(input("display")!, { target: { value: "25" } });
    expect(screen.getByTestId("changing-uom-target")).toHaveTextContent("2000");
  });

  it("new C01 custody gate never exposes an editable target while custody is unconfirmed", async () => {
    const changed = vi.fn();
    render(<RouteLoadProductTable vehicleId="17" warehouseId="21" scope="1:3:4"
      current={{ "1000": "25" }} targets={{ "1000": "25" }}
      units={{ "1000": unit("PACK", "8") }} names={{ "1000": "Vehicle load" }}
      custodyReady={false} commandReady={false}
      onClear={vi.fn()} onRestoreClear={vi.fn()} onTargetChange={changed} />);
    expect(screen.getByTestId("dispatch-launch-products")).toHaveAttribute("data-first-window-ready", "false");
    expect(screen.queryByText("Vehicle load")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear all" })).toBeDisabled();
    expect(changed).not.toHaveBeenCalled();
  });

  it("arrow navigation stays in the SAME input kind; Clear+Undo restore exact BASE", async () => {
    render(<Fixture rows={[
      item("PACK","8","25","25","1000"),
      item(null,null,"5","5","1001"),
      item("CARTON","50","1250","1253","1002"),
    ]} />);
    await ready();
    expect(input("display","1001")).toBeNull();
    fireEvent.keyDown(input("display","1000")!,{key:"ArrowDown"});
    expect(input("display","1002")).toHaveFocus();
    fireEvent.keyDown(input("display","1002")!,{key:"ArrowUp"});
    expect(input("display","1000")).toHaveFocus();
    fireEvent.keyDown(input("base","1000")!,{key:"ArrowDown"});
    expect(input("base","1001")).toHaveFocus();
    expect(input("display")).toHaveAttribute("autocomplete","off");
    expect(screen.getByRole("table").querySelectorAll("colgroup col")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button",{name:"Clear all"}));
    expect(base()).toBeUndefined();
    fireEvent.click(screen.getByRole("button",{name:"Undo clear"}));
    expect(base()).toBe("25");
    expect(input("display","1002")).toHaveValue("25");
  });
});
