import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useShortageVehicleAvailability } from "@/features/dispatch/useShortageVehicleAvailability";

const mock = vi.hoisted(() => ({
  fetch: vi.fn(), current: true,
  session: {generation:"test-g1",identity:"company:1:owner:2"},
}));
vi.mock("@/hooks/useAuthFetch", () => ({useAuthFetch: () => mock.fetch}));
vi.mock("@/hooks/useDashboardSession", () => ({useDashboardSession: () => mock.session}));
vi.mock("@/lib/authStorage", () => ({isDashboardSessionCurrent: () => mock.current}));

const verified = (id:string,quantity:string) => ({
  status:"VERIFIED", source:"CANONICAL_VEHICLE_CUSTODY",
  vehicle_id:7,vehicle_location_id:99,custody_epoch_id:4,
  stock_snapshot:"signed-fingerprint",
  items:[{product_id:id,available_base:quantity,base_uom:"EACH"}],
});

function Quote({initialDriver="11"}:{initialDriver?:string}) {
  const [driverId,setDriver] = useState(initialDriver);
  const q = useShortageVehicleAvailability({
    driverId, scope:"g1:owner2:shortage", productIds:["20"],
  });
  return <div>
    <button type="button" onClick={()=>setDriver("22")}>Other driver</button>
    <span data-testid="status">{q.status}</span>
    <span data-testid="qty">{q.byProduct.get("20")?.available_base ?? "UNKNOWN"}</span>
  </div>;
}

beforeEach(()=>{mock.current=true;mock.fetch.mockReset();});

describe("#1057 Backoffice representative custody evidence",()=>{
  it("uses selected canonical representative, never a client-provided vehicle",async()=>{
    mock.fetch.mockResolvedValueOnce(verified("20","4"));
    render(<Quote/>);
    await waitFor(()=>expect(screen.getByTestId("status")).toHaveTextContent("VERIFIED"));
    expect(screen.getByTestId("qty")).toHaveTextContent("4");
    expect(mock.fetch).toHaveBeenCalledTimes(1);
    const url=String(mock.fetch.mock.calls[0][0]);
    expect(url).toContain("driver_id=11");
    expect(url).toContain("product_ids=20");
    expect(url).not.toContain("vehicle_id");
  });

  it("hides old driver's stock immediately when driver switches",async()=>{
    let resolveSecond:(v:unknown)=>void=()=>{};
    mock.fetch.mockResolvedValueOnce(verified("20","9"));
    mock.fetch.mockImplementationOnce(()=>new Promise(resolve=>{resolveSecond=resolve;}));
    render(<Quote/>);
    await waitFor(()=>expect(screen.getByTestId("qty")).toHaveTextContent("9"));
    fireEvent.click(screen.getByRole("button",{name:"Other driver"}));
    expect(screen.getByTestId("qty")).toHaveTextContent("UNKNOWN");
    resolveSecond({status:"UNKNOWN",reason:"NO_ACCEPTED_VEHICLE_CUSTODY",items:[]});
    await waitFor(()=>expect(mock.fetch).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("status")).toHaveTextContent("UNKNOWN");
  });

  it("never treats a revoked session's successful old reply as verified",async()=>{
    mock.fetch.mockImplementationOnce(async()=>{mock.current=false;return verified("20","50");});
    render(<Quote/>);
    await waitFor(()=>expect(mock.fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("qty")).toHaveTextContent("UNKNOWN");
  });

  it("never requests vehicle data without selecting a driver",()=>{
    render(<Quote initialDriver=""/>);
    expect(screen.getByTestId("status")).toHaveTextContent("UNKNOWN");
    expect(mock.fetch).not.toHaveBeenCalled();
  });
});
