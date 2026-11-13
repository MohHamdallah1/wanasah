import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VehicleCustodyRecoveryEntry } from "../features/dispatch/custodyRecovery/VehicleCustodyRecoveryEntry";

vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-i18next")>(),
  useTranslation: () => ({i18n:{language:"en",dir:()=> "ltr"}, t:(key:string)=>key}),
}));
vi.mock("@/components/ui/modal", () => ({
  Modal: ({isOpen,children,title}: any) => isOpen
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
    base_uom:"EACH",stock_status:"AVAILABLE",on_hand_base:"15",reserved_base:"0"}],
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
});
