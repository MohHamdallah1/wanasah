import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { PendingRoutesTable } from "@/components/dispatch/PendingRoutesTable";
import { PostponedRoutesModal } from "@/components/dispatch/PostponedRoutesModal";
import type { PendingRoute } from "@/types/dispatch";

const route=(id:string,status:PendingRoute["status"],extra:Partial<PendingRoute>={}):PendingRoute=>({
  id,zoneId:id,zoneName:"Region "+id,driverId:"51",driverName:"Omar",
  vehicleId:"12",sourceWarehouseId:"9",shopsRemaining:3,status,
  sessionEnded:false,sessionBound:true,assignmentContextRevision:4,
  currentPeriodId:901,currentDriverId:51,currentDriverName:"Omar",
  currentVehicleId:12,currentVehicleLocationId:41,
  can_execute:true,commercial_context:null,...extra,
});
const callbacks=()=>({
  onOpenRouteModal:vi.fn(),onPostponeRoute:vi.fn(),onCloseZone:vi.fn(),
  onForceWithdraw:vi.fn(),onContinuePaused:vi.fn(),onAdjustInventory:vi.fn(),
  onOpenRadar:vi.fn(),driverShortagesMap:{},
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
beforeEach(async()=>{await setAppLanguage("en");});

describe("ARV1-F #1044 active route controls and availability",()=>{
  it("renders distinct actionable English ACTIVE and WAITING states; waiting keeps signed representative/vehicle",()=>{
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("A","active"),route("B","waiting")]} {...acts}/>);
    const active=screen.getByTestId("active-route-A");
    const waiting=screen.getByTestId("active-route-B");
    expect(within(active).getByText("Active")).toBeVisible();
    expect(within(waiting).getByText("Paused · representative and vehicle reserved")).toBeVisible();
    expect(within(active).getByRole("button",{name:"Pause route"})).toBeEnabled();
    expect(within(waiting).getByRole("button",{name:"Continue route"})).toBeEnabled();
    expect(within(waiting).getByRole("button",{name:"Postpone route"})).toBeEnabled();
    fireEvent.click(within(active).getByRole("button",{name:"Pause route"}));
    fireEvent.click(within(waiting).getByRole("button",{name:"Continue route"}));
    expect(acts.onForceWithdraw).toHaveBeenCalledWith(expect.objectContaining({id:"A"}));
    expect(acts.onContinuePaused).toHaveBeenCalledWith(expect.objectContaining({id:"B"}));
  });

  it("retains a zero-remaining WAITING route's signed Continue action, not automatic closure",()=>{
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("W","waiting",{shopsRemaining:0})]} {...acts}/>);
    expect(screen.getByRole("button",{name:"Continue route"})).toBeEnabled();
    expect(screen.getByRole("button",{name:"Close route"})).toBeEnabled();
    expect(screen.queryByRole("button",{name:"Close finished route"})).not.toBeInTheDocument();
  });

  it("never offers Continue on ended WorkSession; preserves the route without fake signed rebind",()=>{
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("E","waiting",{sessionEnded:true})]} {...acts}/>);
    expect(screen.getByText("Work session ended")).toBeVisible();
    expect(screen.queryByRole("button",{name:"Continue route"})).not.toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Postpone route"})).toBeEnabled();
  });

  it("preserves active card/actions but disables every command during signed reentry without falsifying an empty list",()=>{
    const acts=callbacks();
    const view=render(<PendingRoutesTable routes={[route("A","active")]}
      pending={false} actionsPending {...acts}/>);
    const row=screen.getByTestId("active-route-A");
    expect(within(row).getByText("Active")).toBeInTheDocument();
    const pause=within(row).getByRole("button",{name:"Pause route"});
    const adjust=within(row).getByRole("button",{name:"Adjust vehicle load"});
    expect(pause).toBeDisabled();
    expect(adjust).toBeDisabled();
    expect(within(row).getByRole("button",{name:"View route radar"})).toBeDisabled();
    fireEvent.click(pause);
    expect(acts.onForceWithdraw).not.toHaveBeenCalled();
    expect(screen.queryByText("Verifying routes...")).not.toBeInTheDocument();
    view.rerender(<PendingRoutesTable routes={[route("A","active")]}
      actionsPending={false} {...acts}/>);
    expect(screen.getByRole("button",{name:"Pause route"})).toBeEnabled();
  });

  it("restricts controls to radar for read-only rows and denies UI mutations",()=>{
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("R","active",{can_execute:false})]} {...acts}/>);
    expect(screen.getByRole("button",{name:"View route radar"})).toBeEnabled();
    expect(screen.queryByRole("button",{name:"Pause route"})).not.toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Adjust vehicle load"})).not.toBeInTheDocument();
  });

  it("does not show POSTPONED and CLOSED rows as active cards with pause/load actions",()=>{
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("P","postponed"),route("C","closed" as PendingRoute["status"]),route("A","active")]} {...acts}/>);
    expect(screen.getByText("Region A")).toBeVisible();
    expect(screen.queryByText("Region P")).not.toBeInTheDocument();
    expect(screen.queryByText("Region C")).not.toBeInTheDocument();
  });

  it("distinguishes refreshing/pending from a confirmed empty active route list in English",()=>{
    const acts=callbacks();
    const view=render(<PendingRoutesTable routes={[]} pending {...acts}/>);
    expect(screen.getByRole("status")).toHaveTextContent("Verifying routes");
    expect(screen.queryByText("No active routes")).not.toBeInTheDocument();
    view.rerender(<PendingRoutesTable routes={[]} pending={false} {...acts}/>);
    expect(screen.getByText("No active routes")).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows genuine AR localized status/controls and handles touch keyboard through native buttons",async()=>{
    await setAppLanguage("ar");
    const acts=callbacks();
    render(<PendingRoutesTable routes={[route("A","active"),route("B","waiting")]} {...acts}/>);
    const active=screen.getByTestId("active-route-A");
    const waiting=screen.getByTestId("active-route-B");
    expect(within(active).getByText("نشط")).toBeVisible();
    expect(within(waiting).getByText("متوقف مؤقتًا · المندوب والسيارة محجوزان")).toBeVisible();
    const button=within(waiting).getByRole("button",{name:"استئناف الخط"});
    button.focus();
    expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(acts.onContinuePaused).toHaveBeenCalledOnce();
  });

  it("postponed route stays reserved in its own modal and requires selection, not old assignment",()=>{
    const onRestore=vi.fn(),onCloseRoute=vi.fn();
    render(<PostponedRoutesModal isOpen onClose={vi.fn()} routes={[
      route("P","postponed",{currentPeriodId:null,currentDriverId:null,currentVehicleId:null})
    ]} onRestore={onRestore} onCloseRoute={onCloseRoute}/>);
    expect(screen.getByText("Postponed · zone reserved; representative and vehicle released")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:/Select and resume/,hidden:true}));
    expect(onRestore).toHaveBeenCalledOnce();
    expect(onCloseRoute).not.toHaveBeenCalled();
  });
});
