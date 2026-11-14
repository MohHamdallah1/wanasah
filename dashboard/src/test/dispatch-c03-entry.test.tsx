import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent, screen, waitFor, cleanup } from "@testing-library/react";
import type { ReactNode } from "react";
import { VehicleCustodyRecoveryEntry } from "../features/dispatch/custodyRecovery/VehicleCustodyRecoveryEntry";

vi.mock("react-i18next", async importOriginal=>({
  ...await importOriginal<typeof import("react-i18next")>(),
  useTranslation:()=>({i18n:{language:"en",dir:()=> "ltr"},t:(s:string)=>s}),
}));
vi.mock("@/components/ui/modal",()=>({
  Modal:({isOpen,title,children}: {isOpen:boolean;title:string;children:ReactNode})=>
    isOpen?<div role="dialog" aria-label={title}>{children}</div>:null,
}));
const snapshot="b".repeat(64),vehicleId="13";
const readiness={vehicle_id:13,vehicle_location_id:22,context_revision:1,
  state:"NO_EPOCH",custodian_kind:null,stocked:true,stock_snapshot:snapshot,
  stock_line_count:2,recovery_action:"CUSTODY_FIRST_ACCEPT"};
const stock={vehicle_id:13,context_revision:1,stock_snapshot:snapshot,stock_lines:[
  {product_name:"Rice",sku:"R",batch_number:"",expiry_date:null,
    base_uom:"EACH",base_uom_name:"حبة",display_uom_name:null,
    display_factor_to_base:null,stock_status:"AVAILABLE",
    on_hand_base:"5",reserved_base:"0"},
  {product_name:"Rice",sku:"R",batch_number:"",expiry_date:null,
    base_uom:"EACH",base_uom_name:"حبة",display_uom_name:null,
    display_factor_to_base:null,stock_status:"AVAILABLE",
    on_hand_base:"20",reserved_base:"0"},
]};
const props={vehicleId,vehicleLabel:"Vehicle 12-25132",
  reasonCode:"CUSTODY_NEEDS_REVIEW",
  drivers:[{id:"7",label:"Khaled"},{id:"8",label:"Samer"}],
  selectedDriverId:"7",actorScope:"1:2",authorized:()=>true,onAccepted:vi.fn(),
};
type RecordState="PENDING"|"CONFIRMED"|"DECLINED"|"CANCELLED"|"EXPIRED"|"COMMITTED";
function server(){
  let current:Record<string,unknown>|null=null;
  const calls:{path:string;body:Record<string,unknown>}[]=[];
  const fetch=vi.fn(async(path:string,init?:RequestInit)=>{
    if(path.endsWith("/current"))return current;
    if(path.endsWith("/readiness"))return readiness;
    if(path.endsWith("/stock-review"))return stock;
    if(path.includes("/history?limit=20"))return {items:[
      {recipient_label:"False attribution",evidence_origin:"M01_BACKFILL",started_at:"2026-11-01T10:00:00Z"},
    ]};
    const body=init?.body?JSON.parse(String(init.body)):{};
    if(init?.method!=="POST")throw Error("Unknown "+path);
    calls.push({path,body});
    if(path.endsWith("/handoffs")){
      current={handoff_id:"11111111-1111-4111-8111-111111111111",
        state:"PENDING",target_driver_id:body.target_driver_id,
        recipient_label:body.target_driver_id===7?"Khaled":"Samer",
        expires_at:"2026-11-14T12:00:00Z",vehicle_id:13,context_revision:1};
      return current;
    }
    if(path.endsWith("/cancel")){
      current={...current,state:"CANCELLED"};
      return current;
    }
    if(path.endsWith("/approve")){
      if(current?.state!=="CONFIRMED")throw Error("WRONG_STATE");
      current={...current,state:"COMMITTED"};
      return {state:"ACCEPTED",vehicle_id:13,epoch_id:19,context_revision:2,
        replayed:false,stock_movements:0};
    }
    throw Error("Unknown "+path);
  });
  return {fetch,calls,get:()=>current,update:(state:RecordState)=>{
    if(current)current={...current,state};
  }};
}
beforeEach(()=>{sessionStorage.clear();vi.restoreAllMocks();});
describe("CUSTODY P0 server-owned manager handoff",()=>{
  it("never gives unauthorized employee a manager action",()=>{
    const s=server();
    render(<VehicleCustodyRecoveryEntry {...props} fetch={s.fetch} authorized={()=>false}/>);
    expect(screen.getByText("Vehicle 12-25132")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(s.fetch).not.toHaveBeenCalled();
  });
  it("persists the exact recipient on reentry, groups only no-lot physical stock and never writes proof",async()=>{
    const s=server();
    const {unmount}=render(<VehicleCustodyRecoveryEntry {...props} openOnMount fetch={s.fetch}/>);
    await waitFor(()=>expect(screen.getByText("Rice")).toBeTruthy());
    expect(screen.getByText(/25 حبة/)).toBeTruthy();
    expect(screen.getByText("Previous custodian not documented")).toBeTruthy();
    fireEvent.click(screen.getByRole("button",{name:"Send custody receipt request"}));
    await waitFor(()=>expect(screen.getByText("Waiting for representative's response")).toBeTruthy());
    expect(screen.getByText(/Khaled/)).toBeTruthy();
    expect(s.calls[0].body).toMatchObject({
      target_driver_id:7,expected_context_revision:1,expected_stock_snapshot:snapshot,
    });
    expect(s.calls[0].body).not.toHaveProperty("offer_token");
    unmount();
    render(<VehicleCustodyRecoveryEntry {...props} openOnMount fetch={s.fetch}/>);
    await waitFor(()=>expect(screen.getByText("Waiting for representative's response")).toBeTruthy());
    expect(screen.getByText(/Khaled/)).toBeTruthy();
    expect(s.calls).toHaveLength(1);
    expect(document.body.textContent).not.toContain("PRIVATE-SIGNED");
  });
  it("requires actual server cancel before switching recipient and confirms only server-signed receipt",async()=>{
    const s=server(),onAccepted=vi.fn();
    render(<VehicleCustodyRecoveryEntry {...props} openOnMount fetch={s.fetch}
      onAccepted={onAccepted}/>);
    await waitFor(()=>expect(screen.getByRole("button",{name:"Send custody receipt request"})).toBeTruthy());
    fireEvent.click(screen.getByRole("button",{name:"Send custody receipt request"}));
    await waitFor(()=>expect(screen.getByText("Waiting for representative's response")).toBeTruthy());
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Change representative"}));
    expect(screen.getByText(/Cancellation revokes/)).toBeTruthy();
    expect(s.calls).toHaveLength(1);
    fireEvent.click(screen.getByRole("button",{name:"Confirm cancellation"}));
    await waitFor(()=>expect(s.calls.some(c=>c.path.endsWith("/cancel"))).toBe(true));
    await waitFor(()=>expect(screen.getByRole("combobox")).toBeTruthy());
    fireEvent.change(screen.getByRole("combobox"),{target:{value:"8"}});
    fireEvent.click(screen.getByRole("button",{name:"Send custody receipt request"}));
    await waitFor(()=>expect(screen.getByText(/Samer/)).toBeTruthy());
    expect(s.calls.filter(c=>c.path.endsWith("/handoffs"))).toHaveLength(2);
    s.update("CONFIRMED");
    fireEvent.click(screen.getByRole("button",{name:"Refresh request status"}));
    await waitFor(()=>expect(screen.getByRole("button",{name:"Approve custody"})).toBeTruthy());
    fireEvent.click(screen.getByRole("button",{name:"Approve custody"}));
    await waitFor(()=>expect(onAccepted).toHaveBeenCalledTimes(1));
    expect(onAccepted.mock.calls[0][0]).toMatchObject({state:"ACCEPTED",stock_movements:0});
    expect(s.calls.at(-1)?.body).not.toHaveProperty("receiver_proof");
  });
});
