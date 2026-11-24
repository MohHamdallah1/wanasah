import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { ShortageProductPicker } from "@/components/dispatch/ShortageProductPicker";
import { ShortageModal } from "@/components/dispatch/ShortageModal";
import type { Shop, Zone } from "@/types/dispatch";

const fake = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/hooks/useAuthFetch", () => ({ useAuthFetch: () => fake.fetch }));
vi.mock("@/hooks/useDashboardSession", () => ({
  useDashboardSession: () => ({ generation: "g1", identity: "company:1:owner:9" }),
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({ isOpen, children, footer }: { isOpen: boolean; children: React.ReactNode; footer?: React.ReactNode }) =>
    isOpen ? <div role="dialog">{children}<div className="app-modal-footer">{footer}</div></div> : null,
}));
vi.mock("@/components/dispatch/ShortageRequestComposer", () => ({
  ShortageRequestComposer: () => <div data-testid="mock-request-composer"/>,
}));
const products = Array.from({length: 500}, (_, i) => ({
  id: String(1000+i), name: `SKU ${String(i+1).padStart(3,"0")}`, load: null,
}));
const zones = [{id:"1",name:"Zone A"}] as Zone[];
const shops = [{id:"2",zoneId:"1",name:"Shop B",archived:false}] as Shop[];
const initial = {
  canCreate: true, canCancel: false, canEdit: false, focusShortageId: null,
  isOpen: true, onClose: vi.fn(), zones, activeShops: shops,
  shortageZoneId: "", shortageShopId: "", onZoneChange: vi.fn(), onShopChange: vi.fn(),
  productScope: "1:g1", shortageDraft: [] as {productId:string;productName:string;quantity:number}[],
  onAddProductToDraft: vi.fn(), onRemoveProductFromDraft: vi.fn(),
  onUpdateDraftQty: vi.fn(), onClearDraft: vi.fn(), onConfirmShortages: vi.fn(),
  shortages: [], onDeleteShortage: vi.fn(), onDeleteShortageGroup: vi.fn(),
  onEditShortageGroup: vi.fn(), editingShortageIds: [], onCancelEdit: vi.fn(),
  drivers: [{id:"31",name:"Driver A"}], shortageDriverId: "", onDriverChange: vi.fn(),
  groupRecovery: { pending:null, blocked:false, restoring:false, busy:false,
    feedback:null, httpReference:null, onRetry:vi.fn() },
};

beforeEach(async () => {
  await setAppLanguage("en");
  fake.fetch.mockReset();
  fake.fetch.mockImplementation(async (url:string) => {
    const q=new URL(url,"http://tests").searchParams;
    const search=(q.get("search")??"").toLocaleLowerCase();
    const filtered=products.filter(row=>row.name.toLocaleLowerCase().includes(search));
    const from=Number((q.get("cursor")??"p0").slice(1));
    const more=from+80<filtered.length;
    return { items: filtered.slice(from,from+80), has_more: more,
      next_cursor: more?`p${from+80}`:null };
  });
});

describe("#1055 authorized shortage infinite product catalog", () => {
  it("uses a 3-page bounded window for 500 products; backscroll restores evicted items; pins survive", async () => {
    function Harness() {
      const [rows,setRows]=useState<{productId:string;productName:string;quantity:number}[]>([]);
      return <><ShortageProductPicker scope="company:g1" drafted={rows}
        onAdd={(id,name)=>setRows(old=>[...old,{productId:id,productName:name,quantity:1}])}/>
        <div data-testid="selected-request">{rows.map(row=>row.productName).join(", ")}</div></>;
    }
    render(<Harness/>);
    await screen.findByText("SKU 001");
    expect(fake.fetch).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("heading", {name:"Product catalog"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button", {name:/^(Next|Previous)$/})).not.toBeInTheDocument();
    const list=screen.getByTestId("shortage-visible-products");
    Object.defineProperties(list,{scrollHeight:{configurable:true,value:1300},
      clientHeight:{configurable:true,value:360}});
    fireEvent.click(screen.getByRole("button",{name:"Add one unit of SKU 001 to request"}));
    for(const [top,sku] of [[900,"SKU 160"],[940,"SKU 240"],[980,"SKU 320"]] as const){
      fireEvent.scroll(list,{target:{scrollTop:top}});
      await screen.findByText(sku);
    }
    expect(document.querySelectorAll("[data-window-page]")).toHaveLength(3);
    expect(within(list).queryByText("SKU 001")).not.toBeInTheDocument();
    expect(screen.getByTestId("selected-request")).toHaveTextContent("SKU 001");
    fireEvent.scroll(list,{target:{scrollTop:0}});
    await screen.findByText("SKU 001");
    expect(document.querySelectorAll("[data-window-page]")).toHaveLength(3);
    expect(fake.fetch.mock.calls.every(([url])=>url.includes("purpose=SHORTAGE")&&url.includes("limit=80"))).toBe(true);
  });

  it("keeps the actual catalog viewport stable before the first signed page, without animated fake rows", async () => {
    let finish!: (page: {items: typeof products; has_more: boolean; next_cursor: null}) => void;
    fake.fetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(<ShortageProductPicker scope="company:g1" drafted={[]} onAdd={vi.fn()}/>);
    const list = screen.getByTestId("shortage-visible-products");
    expect(list).toHaveClass("h-[23rem]");
    expect(list).toHaveAttribute("aria-busy", "true");
    expect(list.querySelector(".animate-pulse")).toBeNull();
    expect(within(list).queryByRole("button")).not.toBeInTheDocument();
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    finish({items: products.slice(0,1), has_more:false, next_cursor:null});
    await screen.findByText("SKU 001");
    expect(list).toHaveClass("h-[23rem]");
    expect(list).toHaveAttribute("aria-busy", "false");
  });

  it("invalidates the visible window on search change without old company results", async () => {
    render(<ShortageProductPicker scope="company:g1" drafted={[]} onAdd={vi.fn()}/>);
    await screen.findByText("SKU 001");
    fireEvent.change(screen.getByRole("searchbox",{name:"Search name or product code (optional)"}),
      {target:{value:"SKU 450"}});
    await screen.findByText("SKU 450");
    expect(screen.queryByText("SKU 001")).not.toBeInTheDocument();
    expect(fake.fetch.mock.calls.some(([url])=>url.includes("search=SKU+450"))).toBe(true);
  });
});

describe("#1055 disabled request reason", () => {
  it.each([
    ["zone",{}, "Select a zone first."],
    ["shop",{shortageZoneId:"1"},"Select a shop."],
    ["driver",{shortageZoneId:"1",shortageShopId:"2"},"Select a representative or save unassigned."],
    ["product",{shortageZoneId:"1",shortageShopId:"2",shortageDriverId:"31"},"Add a product to the request."],
    ["quantity",{shortageZoneId:"1",shortageShopId:"2",shortageDriverId:"31",
      shortageDraft:[{productId:"41",productName:"Chips",quantity:0}]},
      "Check the request item quantities."],
    ["pending",{shortageZoneId:"1",shortageShopId:"2",shortageDriverId:"31",
      groupRecovery:{...initial.groupRecovery,busy:true}},"A previous request is still being verified."],
  ])("gives instant hover/focus feedback for %s",(_,overrides,reason)=>{
    render(<ShortageModal {...initial} {...overrides}/>);
    const hint=screen.getByRole("tooltip");
    const action=screen.getByRole("button",{name:/Save shortage demand|Save without representative/});
    expect(action).toBeDisabled();
    expect(hint).toHaveTextContent(reason);
    expect(action).toHaveAttribute("aria-describedby",hint.id);
    expect(hint).toHaveClass("group-hover:visible","group-focus:visible","end-0");
    expect(hint).not.toHaveClass("-translate-x-1/2");
    expect(screen.getByTestId("shortage-send-hint-anchor")).toHaveAttribute("tabindex","0");
  });

  it("enables send with valid scope and item, without showing a tooltip",()=>{
    render(<ShortageModal {...initial} shortageZoneId="1" shortageShopId="2"
      shortageDriverId="31" shortageDraft={[{productId:"41",productName:"Chips",quantity:2}]}/>);
    expect(screen.getByRole("button",{name:"Save shortage demand"})).toBeEnabled();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
