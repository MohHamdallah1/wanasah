import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { RouteLifecyclePanel } from "@/features/dispatch/routeLifecycle/RouteLifecyclePanel";
import type { PendingRoute } from "@/types/dispatch";

const route:PendingRoute={
  id:"177",zoneId:"9",zoneName:"Region North",driverId:"19",driverName:"Historical rep",
  vehicleId:"20",shopsRemaining:2,status:"postponed",sessionEnded:true,sessionBound:true,
  assignmentContextRevision:3,currentPeriodId:null,currentDriverId:null,currentVehicleId:null,
  can_execute:true,commercial_context:null,
};
const assignment={routeId:177,assignmentRevision:3,currentPeriodId:null,
  currentDriverId:null,currentVehicleId:null};
const signed={driverId:7,vehicleId:6,custodyRevision:12,assignmentContextRevision:3,
  accepted:true,authorized:true};
const props=(fetch:(path:string,init?:RequestInit)=>Promise<unknown>,scope:string)=>({
  isOpen:true,onClose:vi.fn(),route,assignment,
  drivers:[{id:"7",label:"Rep A"}],vehicles:[{id:"6",label:"Van 6"}],
  selectedDriver:"7",selectedVehicle:"6",onDriverChange:vi.fn(),onVehicleChange:vi.fn(),
  actorScope:scope,fetch,authorized:()=>true,onCommitted:vi.fn(),
  initialAction:"RESUME" as const,
});
beforeEach(async()=>{localStorage.clear();await setAppLanguage("en");});
afterEach(()=>{cleanup();vi.restoreAllMocks();});

describe("ARV1-F signed lifecycle invalidation",()=>{
  it("a new principal cannot reuse the previous principal's accepted custody proof on same route/driver/vehicle",async()=>{
    let principal="1:2:3";
    const fetch=vi.fn(async(path:string)=>{
      if(path.includes("/readiness")){
        if(principal==="1:2:3") return signed;
        throw Object.assign(new Error("permission revoked"),{status:403});
      }
      throw new Error("A write must never be sent");
    });
    const view=render(<RouteLifecyclePanel {...props(fetch,principal)}/>);
    const resume=screen.getByRole("button",{name:"Resume route"});
    await waitFor(()=>expect(resume).toBeEnabled());
    principal="2:9:3";
    view.rerender(<RouteLifecyclePanel {...props(fetch,principal)}/>);
    await waitFor(()=>expect(resume).toBeDisabled());
    expect(fetch).not.toHaveBeenCalledWith("/dispatch/route/177/lifecycle",expect.anything());
  });

  it("new assignment revision invalidates previous custody proof without a resubmit",async()=>{
    const revision=3;
    const fetch=vi.fn(async(path:string)=>{
      if(path.includes("/readiness")) return {...signed,assignmentContextRevision:revision-1};
      throw new Error("Route write forbidden");
    });
    const view=render(<RouteLifecyclePanel {...props(fetch,"1:2:3")}
      assignment={{...assignment,assignmentRevision:2}}/>);
    // No proof matching the current revision may enable RESUME.
    await waitFor(()=>expect(screen.getByRole("button",{name:"Resume route"})).toBeDisabled());
    view.rerender(<RouteLifecyclePanel {...props(fetch,"1:2:3")} />);
    await waitFor(()=>expect(screen.getByRole("button",{name:"Resume route"})).toBeDisabled());
  });

  it("route changed from postponed to active while resume modal open: no new mismatched commands",async()=>{
    const fetch=vi.fn(async(path:string)=>path.includes("/readiness")?signed:{});
    const view=render(<RouteLifecyclePanel {...props(fetch,"1:2:3")}/>);
    await waitFor(()=>expect(screen.getByRole("button",{name:"Resume route"})).toBeEnabled());
    view.rerender(<RouteLifecyclePanel {...props(fetch,"1:2:3")} route={{...route,status:"active"}}/>);
    expect(screen.getByText(/Route assignment changed/)).toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Postpone route"})).not.toBeEnabled();
    expect(screen.queryByRole("button",{name:"Close route"})).not.toBeEnabled();
    expect(fetch).not.toHaveBeenCalledWith("/dispatch/route/177/lifecycle",expect.anything());
  });
});
