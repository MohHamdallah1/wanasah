import { webcrypto } from "node:crypto";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { ShortageUrgentAction, ShortageUrgentRecovery } from "@/components/dispatch/ShortageUrgentAction";
import { allowedUrgentDriver, eligibleUrgentDrivers, parseUrgentQuote, parseUrgentReceipt, pendingUrgentKey, readUrgent, storeUrgent, urgentBudget,
  type UrgentIntent } from "@/features/dispatch/shortageUrgent/contract";
import { useUrgentPromotion } from "@/features/dispatch/shortageUrgent/useUrgentPromotion";
import type { Shortage, PendingRoute } from "@/types/dispatch";
import { clearLocalStoragePreservingLoginHintsAndPreferences } from "@/lib/authStorage";
const scope="1:2:3";
const session={generation:"g1",identity:'["1","2","3",""]'};
const row:Shortage={id:"7",productId:"40",productName:"Chips",zoneId:"3",zoneName:"Zone",shopId:"2",shopName:"Shop",driverId:"9",driverName:"Field",quantity:10,status:"pending",fulfilledBase:0,outstandingBase:10,activeUrgentBase:0,unassignedBase:10,fulfillmentEvidence:"SIGNED_V1"};
const driver={id:"9",name:"Field",vehicle:"6"};
const other={id:"10",name:"Other",vehicle:"8"};
const quote=(stock="4")=>({status:"VERIFIED",source:"CANONICAL_VEHICLE_CUSTODY",vehicle_id:6,vehicle_location_id:5,custody_epoch_id:8,stock_snapshot:"selected-quote-v1:fixture",items:[{product_id:"40",available_base:stock,base_uom:"PACK"}]});
const receipt=(body:UrgentIntent)=>({state:"URGENT_AUTHORIZED",request_id:body.request_id,shortage_id:7,assignment_id:11,visit_id:12,custody_epoch_id:8,approved_base:body.quantity_base,outstanding_base:10});
const admitted=vi.hoisted(()=>({current:true}));
vi.mock("@/lib/authStorage",async orig=>({...await orig<typeof import("@/lib/authStorage")>(),isDashboardSessionCurrent:()=>admitted.current}));
const locks=new Set<string>();
beforeEach(async()=>{
  admitted.current=true;localStorage.clear();locks.clear();vi.stubGlobal("crypto",webcrypto);
  Object.defineProperty(navigator,"locks",{configurable:true,value:{request:async(name:string,_:unknown,fn:(lock:object|null)=>Promise<unknown>)=>{
    if(locks.has(name))return fn(null);locks.add(name);try{return await fn({name});}finally{locks.delete(name);}
  }}});
  await setAppLanguage("en");
});
afterEach(()=>{vi.unstubAllGlobals();Object.defineProperty(navigator,"locks",{configurable:true,value:undefined});});
const props=(fetch:(path:string,options?:RequestInit)=>Promise<unknown>)=>({
  session,scope,authorized:true,ready:true,fetch,rows:[row],drivers:[driver,other],canSee:()=>true,onRestore:vi.fn(),refresh:vi.fn(async()=>{}),
});
const err=(status:number)=>Object.assign(new Error("private"),{status});
const getBody=(options?:RequestInit)=>JSON.parse(String(options?.body)) as UrgentIntent;
describe("#1078 authoritative pending/assignment/fulfillment separation",()=>{
  it("accepts only signed conserving numeric evidence, not null, string, legacy or impossible amounts",()=>{
    expect(urgentBudget({...row,fulfilledBase:4,outstandingBase:6,activeUrgentBase:2,unassignedBase:4})).toEqual({requested:10,fulfilled:4,outstanding:6,active:2,unassigned:4});
    for(const patch of [{activeUrgentBase:undefined},{activeUrgentBase:null},{unassignedBase:null},{unassignedBase:11},{activeUrgentBase:-1},{fulfilledBase:1},{fulfillmentEvidence:"LEGACY_UNKNOWN"},{status:"fulfilled"},{activeUrgentBase:"0"}]){
      expect(urgentBudget({...row,...patch} as Shortage)).toBeNull();
    }
  });
  it("caps 10/4, zero, fractional and huge exact quantities; rejects incorrect SKU/vehicle/shape",()=>{
    expect(parseUrgentQuote(quote(),row,driver)?.limit).toBe(4);
    expect(parseUrgentQuote(quote("0"),row,driver)?.limit).toBe(0);
    expect(parseUrgentQuote(quote("3.9999999999999999999"),row,driver)?.limit).toBe(3);
    expect(parseUrgentQuote(quote("999999999999999999999"),row,driver)?.limit).toBe(10);
    expect(parseUrgentQuote(quote("4"),{...row,activeUrgentBase:8,unassignedBase:2},driver)?.limit).toBe(2);
    for(const raw of [{...quote(),status:"UNKNOWN"},{...quote(),vehicle_id:9},{...quote(),source:"OTHER"},{...quote(),custody_epoch_id:null},{...quote(),items:[...quote().items,...quote().items]},quote("4e1"),quote("-1")])expect(parseUrgentQuote(raw,row,driver)).toBeNull();
  });
  it("offers only unique executable active-route representatives; cannot reassign a bound demand",()=>{
    const route={driverId:"9",vehicleId:"6",status:"active",can_execute:true} as PendingRoute;
    expect(eligibleUrgentDrivers([route],[driver,other])).toEqual([driver]);
    expect(eligibleUrgentDrivers([route,route],[driver])).toEqual([]);
    expect(eligibleUrgentDrivers([{...route,can_execute:false}],[driver])).toEqual([]);
    expect(allowedUrgentDriver(row,other)).toBe(false);
    expect(allowedUrgentDriver({...row,driverId:""},other)).toBe(true);
  });
  it("persists before send, retains across logout, rejects forged receipt IDs/quantity/shape",()=>{
    const p=storeUrgent(scope,row,driver,4);
    expect(readUrgent("2:2:3")).toBeNull();
    expect(()=>storeUrgent(scope,row,driver,1)).toThrow();
    clearLocalStoragePreservingLoginHintsAndPreferences();
    expect(readUrgent(scope)).toEqual(p);
    expect(parseUrgentReceipt(receipt(p.body),p)).not.toBeNull();
    for(const patch of [{request_id:crypto.randomUUID()},{shortage_id:8},{approved_base:5},{assignment_id:null},{visit_id:"12"},{custody_epoch_id:0},{outstanding_base:3},{outstanding_base:null},{state:"DELIVERED"}])expect(parseUrgentReceipt({...receipt(p.body),...patch},p)).toBeNull();
  });
});
describe("#1078 durable POST",()=>{
  it("doubleclick/lost response/reload retries the same UUID and exact body even when current unassigned is zero",async()=>{
    const posts:string[]=[];
    const fetch=vi.fn(async(path:string,opts?:RequestInit)=>{
      if(path.includes("vehicle-availability"))return quote();
      const body=getBody(opts);posts.push(String(opts?.body));
      expect(readUrgent(scope)?.body).toEqual(body);
      if(posts.length===1)throw Error("lost response");
      return receipt(body);
    });
    const p=props(fetch);
    const h=renderHook(()=>useUrgentPromotion(p));
    await act(async()=>{const a=h.result.current.submit("7","9",4),b=h.result.current.submit("7","9",4);expect(await b).toBe(false);expect(await a).toBe(false);});
    expect(posts).toHaveLength(1);expect(h.result.current.feedback).toBe("unknown");
    const original=readUrgent(scope);
    h.unmount();
    const next={...p,rows:[{...row,activeUrgentBase:10,unassignedBase:0}]};
    const reload=renderHook(()=>useUrgentPromotion(next));
    expect(reload.result.current.pending).toEqual(original);
    await act(async()=>{expect(await reload.result.current.retry()).toBe(true);});
    expect(posts).toEqual([posts[0],posts[0]]);
    expect(fetch.mock.calls.filter(([url])=>url.includes("vehicle-availability"))).toHaveLength(1);
    expect(readUrgent(scope)).toBeNull();expect(p.refresh).toHaveBeenCalledOnce();
  });
  it.each(["0","3.999","NaN"])("fresh %s stock prevents POST and UUID creation",async stock=>{
    const f=vi.fn(async()=>quote(stock));const h=renderHook(()=>useUrgentPromotion(props(f)));
    await act(async()=>{expect(await h.result.current.submit("7","9",4)).toBe(false);});
    expect(f).toHaveBeenCalledOnce();expect(readUrgent(scope)).toBeNull();expect(h.result.current.feedback).toBe("stale");
  });
  it("409 and forged receipt retain the original UUID without list inference",async()=>{
    let tries=0;const f=vi.fn(async(path:string,opts?:RequestInit)=>{
      if(path.includes("vehicle-availability"))return quote();
      if(++tries===1)throw err(409);
      return {...receipt(getBody(opts)),approved_base:5};
    });const p=props(f),h=renderHook(()=>useUrgentPromotion(p));
    await act(async()=>{expect(await h.result.current.submit("7","9",4)).toBe(false);});
    const original=readUrgent(scope);expect(h.result.current.feedback).toBe("conflict");
    await act(async()=>{expect(await h.result.current.retry()).toBe(false);});
    expect(readUrgent(scope)).toEqual(original);expect(p.refresh).not.toHaveBeenCalled();
  });
  it("revoked permission during flight redacts and does not clear original durable command",async()=>{
    let respond!:(r:unknown)=>void;
    const f=vi.fn(async(path:string)=>path.includes("vehicle-availability")?quote():new Promise(resolve=>{respond=resolve;}));
    const p=props(f),h=renderHook(({authorized})=>useUrgentPromotion({...p,authorized}),{initialProps:{authorized:true}});
    let flight!:Promise<boolean>;
    act(()=>{flight=h.result.current.submit("7","9",4);});
    await waitFor(()=>expect(respond).toBeTypeOf("function"));
    const original=readUrgent(scope)!;
    h.rerender({authorized:false});
    await act(async()=>{respond(receipt(original.body));expect(await flight).toBe(false);});
    expect(h.result.current.pending).toBeNull();expect(readUrgent(scope)).toEqual(original);expect(p.refresh).not.toHaveBeenCalled();
  });
  it("403 redacts and preserves durable reference; another actor cannot recover it",async()=>{
    const f=vi.fn(async(path:string)=>{if(path.includes("vehicle-availability"))return quote();throw err(403);});
    const p=props(f),h=renderHook(()=>useUrgentPromotion(p));
    await act(async()=>{expect(await h.result.current.submit("7","9",4)).toBe(false);});
    expect(h.result.current.pending).toBeNull();expect(h.result.current.blocked).toBe(true);expect(readUrgent(scope)).not.toBeNull();
    expect(readUrgent("1:99:3")).toBeNull();
  });
  it("corrupt ledger fails closed before any network call",async()=>{
    localStorage.setItem(pendingUrgentKey(scope),"{bad");const f=vi.fn(async()=>quote());
    const h=renderHook(()=>useUrgentPromotion(props(f)));
    expect(h.result.current.blocked).toBe(true);
    await act(async()=>{expect(await h.result.current.submit("7","9",4)).toBe(false);});
    expect(f).not.toHaveBeenCalled();
  });
  it("verified receipt, failed list refresh: retries read only, not POST",async()=>{
    const f=vi.fn(async(path:string,opts?:RequestInit)=>path.includes("vehicle-availability")?quote():receipt(getBody(opts)));
    const p=props(f);p.refresh.mockRejectedValueOnce(Error("read failed"));
    const h=renderHook(()=>useUrgentPromotion(p));
    await act(async()=>{expect(await h.result.current.submit("7","9",4)).toBe(true);});
    expect(h.result.current.feedback).toBe("refresh");expect(readUrgent(scope)).toBeNull();
    await act(async()=>{await h.result.current.refreshList();});
    expect(h.result.current.feedback).toBe("committed");expect(f).toHaveBeenCalledTimes(2);
  });
});
describe("#1078 bilingual line action",()=>{
  it.each(["en","ar"] as const)("shows approval not delivery and bounds input in %s",async language=>{
    await setAppLanguage(language);
    const f=vi.fn(async(path:string,opts?:RequestInit)=>path.includes("vehicle-availability")?quote():receipt(getBody(opts)));
    const p=props(f);
    function Harness(){const promotion=useUrgentPromotion(p);return <><ShortageUrgentAction row={row} promotion={promotion} language={language} disabled={false}/><ShortageUrgentRecovery promotion={promotion} language={language}/></>;}
    render(<Harness/>);fireEvent.click(screen.getByTestId("shortage-urgent-open-7"));
    await waitFor(()=>expect(screen.getByTestId("shortage-urgent-quote-7")).toHaveTextContent("4 PACK"));
    expect(screen.getByTestId("shortage-urgent-budget-7")).toHaveTextContent("10");
    const input=screen.getByTestId("shortage-urgent-quantity-7"),confirm=screen.getByTestId("shortage-urgent-confirm-7");
    fireEvent.change(input,{target:{value:"5"}});expect(confirm).toBeDisabled();
    fireEvent.change(input,{target:{value:"4"}});expect(confirm).toBeEnabled();fireEvent.click(confirm);
    await waitFor(()=>expect(p.refresh).toHaveBeenCalledOnce());
    expect(screen.getByTestId("shortage-urgent-recovery")).toHaveTextContent(language==="ar"?"لم تُسجّل":"no delivery was recorded");
  });
  it("unknown evidence and unauthorized actor have no approval action",()=>{
    const p=props(async()=>quote());
    function Harness(){const promotion=useUrgentPromotion({...p,authorized:false});return <><ShortageUrgentAction row={row} promotion={promotion} language="en" disabled={false}/><ShortageUrgentAction row={{...row,id:"8",unassignedBase:null}} promotion={promotion} language="en" disabled={false}/></>;}
    render(<Harness/>);expect(screen.queryByTestId("shortage-urgent-open-7")).toBeNull();expect(screen.queryByTestId("shortage-urgent-open-8")).toBeNull();
  });
});
