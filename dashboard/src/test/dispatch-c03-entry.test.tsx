import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { VehicleCustodyRecoveryEntry } from "../features/dispatch/custodyRecovery/VehicleCustodyRecoveryEntry";

vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-i18next")>(),
  useTranslation: () => ({i18n:{language:"en",dir:()=> "ltr"}, t:(key:string)=>key}),
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({isOpen,children,title}: {isOpen:boolean;children:ReactNode;title:string}) => isOpen
    ? <div role="dialog" aria-label={title}>{children}</div> : null,
}));
const fingerprint = "b".repeat(64);
const ready = {
  vehicle_id: 13,vehicle_location_id: 22,context_revision:1,
  state:"NO_EPOCH",custodian_kind:null,stocked:true,
  stock_snapshot:fingerprint,stock_line_count:1,
  recovery_action:"CUSTODY_FIRST_ACCEPT",
};
const stock = {
  vehicle_id:13,context_revision:1,stock_snapshot:fingerprint,
  stock_lines:[{product_name:"Lolo",sku:"L",batch_number:"B01",expiry_date:null,
    base_uom:"EACH",base_uom_name:"حبة",display_uom_name:null,display_factor_to_base:null,
    stock_status:"AVAILABLE",on_hand_base:"15",reserved_base:"0"}],
};
const props = {
  vehicleId:"13",vehicleLabel:"Car A",reasonCode:"CUSTODY_STOCK_WITHOUT_EPOCH",
  drivers:[{id:"7",label:"Khaled"}],selectedDriverId:"7",
  actorScope:"1:2",onAccepted:vi.fn(),
};
describe("C03 owner-visible blocked car handoff",()=>{
  it("never grants a confirmation control to unauthorized employee",()=>{
    const fetch=vi.fn();
    render(<VehicleCustodyRecoveryEntry {...props} fetch={fetch}
      authorized={()=>false}/>);
    expect(screen.getByText("Car A")).toBeTruthy();
    expect(screen.getByText(/no custody record/i)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("opens real review contract to authorized manager, without publishing any token in DOM",async()=>{
    const fetch=vi.fn(async(path:string,opts?:RequestInit)=>{
      if(path.endsWith("/readiness"))return ready;
      if(path.endsWith("/stock-review"))return stock;
      if(path.endsWith("/offer"))return {
        action:"FIRST_ACCEPT",offer_token:"PRIVATE-SIGNED-HANDOFF-".repeat(8),
        stock_snapshot:fingerprint,vehicle_location_id:22,
        stock_line_count:1,expires_in_seconds:900,
      };
      throw Error("Unexpected "+path+" "+String(opts?.method));
    });
    render(<VehicleCustodyRecoveryEntry {...props} fetch={fetch} authorized={()=>true}/>);
    fireEvent.click(screen.getByRole("button",{name:"Review vehicle custody"}));
    await waitFor(()=>expect(screen.getByText("Lolo")).toBeTruthy());
    expect(screen.getByText(/B01/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button",{name:"Prepare handoff"}));
    await waitFor(()=>expect(screen.getByRole("button",{name:"Copy private handoff"})).toBeTruthy());
    expect(document.body.textContent).not.toContain("PRIVATE-SIGNED-HANDOFF");
  });

  it("preserves the original request UUID after UNKNOWN on reload and retries it with the same FIELD proof",async()=>{
    const requestId="3e41e9bc-73d0-4691-94b8-7cf99bacb5b3";
    const key=`wanasah:c03:accept:${props.actorScope}:${props.vehicleId}`;
    const proof="p".repeat(130),posted:unknown[]=[];
    sessionStorage.setItem(key,requestId);
    const fetch=vi.fn(async(path:string,init?:RequestInit)=>{
      if(path.endsWith("/accept-operations/"+requestId))return {state:"UNKNOWN"};
      if(path.endsWith("/accept")){
        posted.push(JSON.parse(String(init?.body)));
        return {state:"ACCEPTED",vehicle_id:13,epoch_id:80,
          context_revision:2,replayed:true,stock_movements:0};
      }
      throw new Error("Unexpected request "+path);
    });
    const accepted=vi.fn();
    render(<VehicleCustodyRecoveryEntry {...props} fetch={fetch}
      openOnMount onAccepted={accepted} authorized={()=>true}/>);
    await waitFor(()=>expect(screen.getByText(/No confirmed server response/)).toBeTruthy());
    expect(sessionStorage.getItem(key)).toBe(requestId);
    expect(fetch.mock.calls.some(([path])=>path.endsWith("/offer"))).toBe(false);
    fireEvent.change(screen.getByRole("textbox",{
      name:"Paste the signed receipt returned by the FIELD app",
    }),{target:{value:proof}});
    fireEvent.click(screen.getByRole("button",{name:"Approve verified custody"}));
    await waitFor(()=>expect(accepted).toHaveBeenCalledTimes(1));
    expect(posted).toEqual([{request_id:requestId,receiver_proof:proof}]);
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("rechecks an UNKNOWN original operation without a second POST or receiver proof",async()=>{
    const requestId="7bd3ca72-6dca-40c4-a0aa-9d221d70be41";
    const key=`wanasah:c03:accept:${props.actorScope}:${props.vehicleId}`;
    sessionStorage.setItem(key,requestId);
    let lookups=0;
    const fetch=vi.fn(async(path:string,init?:RequestInit)=>{
      if(path.endsWith("/accept-operations/"+requestId)){
        lookups++;
        return lookups===1?{state:"UNKNOWN"}:
          {state:"COMMITTED",epoch_id:80,context_revision:2};
      }
      throw new Error("Unexpected request "+path+" "+String(init?.method));
    });
    const accepted=vi.fn();
    render(<VehicleCustodyRecoveryEntry {...props} fetch={fetch}
      openOnMount onAccepted={accepted} authorized={()=>true}/>);
    await waitFor(()=>expect(screen.getByRole("button",{
      name:"Verify / retry original request",
    })).toBeTruthy());
    expect(sessionStorage.getItem(key)).toBe(requestId);
    fireEvent.click(screen.getByRole("button",{name:"Verify / retry original request"}));
    await waitFor(()=>expect(accepted).toHaveBeenCalledTimes(1));
    expect(lookups).toBe(2);
    expect(fetch.mock.calls.every(([,init])=>!init?.method||init.method==="GET")).toBe(true);
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("preserves an UNKNOWN UUID when the initial lookup fails offline",async()=>{
    const requestId="e6c974ed-8ed2-433b-bb2d-2ab547a49c3f";
    const key=`wanasah:c03:accept:${props.actorScope}:${props.vehicleId}`;
    sessionStorage.setItem(key,requestId);
    let checks=0;
    const fetch=vi.fn(async(path:string)=>{
      if(path.endsWith("/accept-operations/"+requestId)){
        checks++;
        if(checks===1)throw new Error("Network unavailable");
        return {state:"COMMITTED",epoch_id:83,context_revision:2};
      }
      throw new Error("Unexpected request "+path);
    });
    const accepted=vi.fn();
    render(<VehicleCustodyRecoveryEntry {...props} fetch={fetch}
      openOnMount onAccepted={accepted} authorized={()=>true}/>);
    await waitFor(()=>expect(screen.getByRole("button",{
      name:"Verify / retry original request",
    })).toBeTruthy());
    expect(sessionStorage.getItem(key)).toBe(requestId);
    fireEvent.click(screen.getByRole("button",{name:"Verify / retry original request"}));
    await waitFor(()=>expect(accepted).toHaveBeenCalledTimes(1));
    expect(checks).toBe(2);
    expect(sessionStorage.getItem(key)).toBeNull();
  });
});
