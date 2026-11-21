import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { setAppLanguage } from "@/i18n";
import { compareShortageVehicleBase } from "@/features/dispatch/useShortageVehicleAvailability";
import { parseDispatchProductPage } from "@/features/dispatch/useDispatchProductSearch";
import {
  saveShortageDraft, restoreShortageDraft, shortageDraftKey,
} from "@/features/dispatch/dispatchDrafts";
import { ShortageRequestComposer } from "@/components/dispatch/ShortageRequestComposer";
import type { Shop, Zone } from "@/types/dispatch";

const fake = vi.hoisted(() => ({
  fetch: vi.fn(), current: true,
  session: {generation: "g1", identity: "company:1:owner:9"},
}));
vi.mock("@/hooks/useAuthFetch", () => ({useAuthFetch: () => fake.fetch}));
vi.mock("@/hooks/useDashboardSession", () => ({useDashboardSession: () => fake.session}));
vi.mock("@/lib/authStorage", () => ({isDashboardSessionCurrent: () => fake.current}));
vi.mock("@/components/dispatch/ShortageProductPicker", () => ({
  ShortageProductPicker: () => <div data-testid="catalog-preserved"/>,
}));
vi.mock("@/components/dispatch/ShortageShopPicker", () => ({
  ShortageShopPicker: () => <div data-testid="shop-picker"/>,
}));
vi.mock("@/components/dispatch/ShortageDriverPicker", () => ({
  ShortageDriverPicker: () => <div data-testid="driver-picker"/>,
}));

const vehicle = (quantity: string, unit = "PACK") => ({
  status: "VERIFIED", source: "CANONICAL_VEHICLE_CUSTODY",
  vehicle_id: 3, vehicle_location_id: 9, custody_epoch_id: 8,
  stock_snapshot: "signed-synthetic",
  items: [{ product_id: "40", available_base: quantity, base_uom: unit }],
});
const item = {productId: "40", productName: "Chips", quantity: 10, baseUomCode: "PACK"};
const zones = [{id:"1",name:"Area"}] as Zone[];
const shops = [{id:"2",zoneId:"1",name:"Shop",archived:false}] as Shop[];
const scope = "1:9:1";

beforeEach(async () => {
  localStorage.clear();
  fake.current = true;
  fake.fetch.mockReset();
  await setAppLanguage("en");
});

describe("#1060 exact base-quantity quote (never delivery authorization)", () => {
  it.each([
    ["10", "FULL", "10", "0"],
    ["4", "PARTIAL", "4", "6"],
    ["0", "ZERO", "0", "10"],
    ["4.25", "PARTIAL", "4.25", "5.75"],
  ])("requested 10 PACK, vehicle %s PACK is %s", (available,kind,potential,outstanding) => {
    expect(compareShortageVehicleBase({
      requested:10,requestBaseUomCode:"PACK",verified:true,
      stock:{product_id:"40",available_base:available,base_uom:"PACK"},
    })).toEqual({kind, potentialBase:potential, outstandingBase:outstanding});
  });

  it("preserves decimal exactness beyond IEEE doubles", () => {
    expect(compareShortageVehicleBase({
      requested: Number.MAX_SAFE_INTEGER, requestBaseUomCode:"PACK", verified:true,
      stock:{product_id:"40",available_base:"9007199254740990.999999999",base_uom:"PACK"},
    })).toEqual({
      kind:"PARTIAL", potentialBase:"9007199254740990.999999999",
      outstandingBase:"0.000000001",
    });
  });

  it.each([
    ["UNKNOWN", false, "4", "PACK", "PACK"],
    ["UNKNOWN", true, "4", "CARTON", "PACK"],
    ["UNKNOWN", true, "4", "PACK", null],
    ["UNKNOWN", true, "NaN", "PACK", "PACK"],
    ["UNKNOWN", true, "-1", "PACK", "PACK"],
    ["UNKNOWN", true, "4.0e2", "PACK", "PACK"],
  ])("fails closed on stale/mismatched/invalid stock (%s %s %s %s %s)",
    (_status,verified,available,stockUnit,requestUnit) => {
      expect(compareShortageVehicleBase({
        requested:10,requestBaseUomCode:requestUnit,verified,
        stock:{product_id:"40",available_base:available,base_uom:stockUnit},
      })).toEqual({kind:"UNKNOWN",potentialBase:null,outstandingBase:null});
    });

  it("parses only additive signed shortage base-unit code; never filters catalog by vehicle stock", () => {
    const rows = Array.from({length:80},(_,i)=>({
      id:String(i+1),name:"SKU "+i, load:null, base_uom_code:"PACK",
    }));
    const result = parseDispatchProductPage({items:rows,has_more:true,next_cursor:"cursor"}, "SHORTAGE");
    expect(result.items).toHaveLength(80);
    expect(result.items[0].baseUomCode).toBe("PACK");
    expect(result.items[79].baseUomCode).toBe("PACK");
    expect(result.has_more).toBe(true);
    expect(parseDispatchProductPage({
      items:[{id:"90",name:"Old product",load:null}], has_more:false,next_cursor:null,
    },"SHORTAGE").items[0].baseUomCode).toBeNull();
  });

  it("retains all quantities and UOM on scoped new draft; old v1 draft restores UNKNOWN", () => {
    const draft = {zoneId:"1",shopId:"2",driverId:"11",rows:[item]};
    saveShortageDraft(scope,draft);
    expect(restoreShortageDraft(scope,zones,shops,[{id:"11"}])?.rows).toEqual([item]);
    expect(JSON.parse(localStorage.getItem(shortageDraftKey(scope)) || "{}").version).toBe(2);
    localStorage.setItem(shortageDraftKey(scope),JSON.stringify({...draft,scope,version:1}));
    const restored = restoreShortageDraft(scope,zones,shops,[{id:"11"}]);
    expect(restored?.rows).toEqual([{...item,baseUomCode:null}]);
    expect(restored?.rows[0].quantity).toBe(10);
    expect(compareShortageVehicleBase({
      requested:restored!.rows[0].quantity,
      requestBaseUomCode:restored!.rows[0].baseUomCode,
      stock:vehicle("4").items[0],verified:true,
    }).kind).toBe("UNKNOWN");
    expect(restoreShortageDraft("2:9:1",zones,shops,[{id:"11"}])).toBeNull();
  });

  it.each([
    ["en","4","Potentially available: 4 PACK"],
    ["ar","4","متاح محتملًا: 4 PACK"],
    ["en","10","Potentially available: 10 PACK"],
    ["en","0","Potentially available: 0 PACK"],
  ])("shows nonpromissory %s quote for %s",async(lang,available,expected)=>{
    await setAppLanguage(lang);
    fake.fetch.mockResolvedValue(vehicle(available));
    render(<ShortageRequestComposer
      zones={zones} shops={shops} zoneId="1" shopId="2" onChooseShop={vi.fn()}
      drivers={[{id:"11",name:"Driver"}]} driverId="11" onDriverChange={vi.fn()}
      productScope="signed:scope" draft={[item]}
      onQuickAdd={vi.fn()} onUpdateQuantity={vi.fn()} onRemove={vi.fn()} onClear={vi.fn()}
      editing={false} blocked={false} allowUnassigned={false} onAllowUnassigned={vi.fn()}
    />);
    await waitFor(()=>expect(screen.getByTestId("shortage-availability-40")).toHaveTextContent(expected));
    expect(screen.getByTestId("shortage-request-uom-40")).toHaveTextContent("PACK");
    expect(screen.getByTestId("shortage-current-order")).toHaveClass("h-60");
    expect(screen.getByTestId("catalog-preserved")).toBeInTheDocument();
    expect(screen.getByText(lang==="ar" ? /ليس حجزًا أو ضمان تسليم/ : /not reserved or guaranteed/)).toBeInTheDocument();
  });

  it("never upgrades revoked/unknown or legacy draft into FULL/PARTIAL",async()=>{
    fake.fetch.mockRejectedValue(new Error("403"));
    render(<ShortageRequestComposer
      zones={zones} shops={shops} zoneId="1" shopId="2" onChooseShop={vi.fn()}
      drivers={[{id:"11",name:"Driver"}]} driverId="11" onDriverChange={vi.fn()}
      productScope="signed:scope" draft={[{...item,baseUomCode:null}]}
      onQuickAdd={vi.fn()} onUpdateQuantity={vi.fn()} onRemove={vi.fn()} onClear={vi.fn()}
      editing={false} blocked={false} allowUnassigned={false} onAllowUnassigned={vi.fn()}
    />);
    await waitFor(()=>expect(fake.fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("shortage-availability-40")).toHaveTextContent("Vehicle stock unverified");
    expect(screen.getByTestId("shortage-request-uom-40")).toHaveTextContent("Request base unit unverified");
    expect(screen.queryByText(/Potentially available: 4/)).not.toBeInTheDocument();
  });
});
