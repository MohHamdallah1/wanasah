import { webcrypto } from "node:crypto";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAppLanguage } from "@/i18n";
import { useShortageCommandCommit } from "@/features/dispatch/shortageCommand/useShortageCommandCommit";
import {
  buildShortageIntent, clearConfirmedShortage, isShortagePending,
  parseShortageReceipt, pendingShortageKey, prepareShortageCommand,
  readPendingShortage,
} from "@/features/dispatch/shortageCommand/contract";
import { saveShortageDraft, restoreShortageDraft } from "@/features/dispatch/dispatchDrafts";
import { ShortageModal } from "@/components/dispatch/ShortageModal";
import { clearLocalStoragePreservingLoginHintsAndPreferences, type DashboardSession } from "@/lib/authStorage";
import type { Shop, Zone } from "@/types/dispatch";

const actor = "1:2:3";
const differentActor = "1:99:3";
const id = "bcfaf14e-0178-4aa2-a36d-89bb4fa87992";
const row = {productId:"40",productName:"Chips",quantity:10,baseUomCode:"PACK"};
const rows = [row, {productId:"5",productName:"Biscuits",quantity:4,baseUomCode:"PACK"}];
const zones = [{id:"3",name:"Zone"}] as Zone[];
const shops = [{id:"7",name:"Shop",zoneId:"3",archived:false}] as Shop[];
const drivers = [{id:"9",name:"FIELD"}];
const session = {generation:"g1",identity:"company:1:principal:2"} as DashboardSession;
const admitted = vi.hoisted(() => ({value:true}));
vi.mock("@/lib/authStorage", async orig => ({
  ...await orig<typeof import("@/lib/authStorage")>(),
  isDashboardSessionCurrent: () => admitted.value,
}));
vi.mock("@/components/dispatch/ShortageProductPicker", () => ({
  ShortageProductPicker: () => <div data-testid="all-company-catalog"/>,
}));
vi.mock("@/features/dispatch/useShortageVehicleAvailability", () => ({
  useShortageVehicleAvailability: () => ({
    status:"UNKNOWN",reason:"NO_ACCEPTED_VEHICLE_CUSTODY",
    byProduct:new Map(),loading:false,refresh:vi.fn(),
  }),
}));
const busyLocks = new Set<string>();
const fakeLocks = { request: async <T,>(
  name:string,_opts:unknown,action:(lock:object|null)=>Promise<T>,
):Promise<T> => {
  if(busyLocks.has(name))return action(null);
  busyLocks.add(name);
  try{return await action({name});}finally{busyLocks.delete(name);}
}};
const err = (status:number) => Object.assign(new Error("private error"),{status});
const receipt = (body:ReturnType<typeof buildShortageIntent>) => ({
  version: 2, status: "PENDING_REPLENISHMENT",
  request_id:body.request_id, request_hash:"a".repeat(64),
  shop_id:body.shop_id, zone_id:body.zone_id,
  requested_driver_id:body.requested_driver_id,
  lines:body.lines.map((l,i)=>({
    product_id:l.product_id,shortage_id:300+i,requested_base:l.quantity_base,
    fulfilled_base:0,outstanding_base:l.quantity_base,
  })),
});
const props = (fetch: (url:string,options?:RequestInit)=>Promise<unknown>) => ({
  session,actorScope:actor,authorized:true,fetch,
  canRestore:vi.fn(()=>true),onRestored:vi.fn(),onCommitted:vi.fn(),
});
beforeEach(async()=>{
  localStorage.clear();
  admitted.value=true;
  busyLocks.clear();
  vi.stubGlobal("crypto",webcrypto);
  Object.defineProperty(navigator,"locks",{configurable:true,value:fakeLocks});
  await setAppLanguage("en");
});
afterEach(()=>{
  vi.unstubAllGlobals();
  Object.defineProperty(navigator,"locks",{configurable:true,value:undefined});
});
describe("#1068 immutable command contract",()=>{
  it("sorts 2 products, uses BASE not CARTON and keeps existing D10 separate",()=>{
    saveShortageDraft(actor,{zoneId:"3",shopId:"7",driverId:"9",rows});
    const original = buildShortageIntent("3","7","9",rows,id);
    expect(original).toEqual({
      version:2,request_id:id,shop_id:7,zone_id:3,requested_driver_id:9,
      lines:[{product_id:5,quantity_base:4},{product_id:40,quantity_base:10}],
    });
    const saved=prepareShortageCommand(actor,"3","7","9",rows,()=>id);
    expect(saved.existing).toBe(false);
    expect(isShortagePending(saved.pending,actor)).toBe(true);
    expect(saved.pending.command).toEqual(original);
    expect(prepareShortageCommand(actor,"88","99","",[{...row,quantity:99}],()=>crypto.randomUUID()))
      .toEqual({pending:saved.pending,existing:true});
    expect(restoreShortageDraft(actor,zones,shops,drivers)?.rows).toEqual(rows);
    expect(readPendingShortage(differentActor)).toBeNull();
    expect(readPendingShortage(actor)?.command.request_id).toBe(id);
    expect(parseShortageReceipt(receipt(original),original)?.lines).toEqual([
      {productId:5,requestedBase:4,fulfilledBase:0,outstandingBase:4},
      {productId:40,requestedBase:10,fulfilledBase:0,outstandingBase:10},
    ]);
    clearConfirmedShortage(actor,crypto.randomUUID());
    expect(readPendingShortage(actor)).not.toBeNull();
    clearConfirmedShortage(actor,id);
    expect(readPendingShortage(actor)).toBeNull();
  });
  it("preserves original UUID through normal logout without exposing it to another actor",()=>{
    prepareShortageCommand(actor,"3","7","9",[row],()=>id);
    expect(clearLocalStoragePreservingLoginHintsAndPreferences()).toBe(true);
    expect(readPendingShortage(actor)?.command.request_id).toBe(id);
    expect(readPendingShortage(differentActor)).toBeNull();
  });
  it("rejects phantom/mismatched receipt, wrong actor, corrupt UUID and 81 lines",()=>{
    const intent=buildShortageIntent("3","7","9",[row],id);
    expect(parseShortageReceipt({message:"ok"},intent)).toBeNull();
    expect(parseShortageReceipt({...receipt(intent),request_id:crypto.randomUUID()},intent)).toBeNull();
    expect(parseShortageReceipt({...receipt(intent),zone_id:999},intent)).toBeNull();
    expect(parseShortageReceipt({...receipt(intent),status:"URGENT_AUTHORIZED"},intent)).toBeNull();
    expect(parseShortageReceipt({request_id:id,lines:[]},intent)).toBeNull();
    expect(parseShortageReceipt({request_id:id,lines:[{...receipt(intent).lines[0],outstanding_base:2}]},intent)).toBeNull();
    expect(()=>buildShortageIntent("3","7","9",Array(81).fill(row),id)).toThrow();
    expect(()=>buildShortageIntent("3","7","9",[row,row],id)).toThrow();
    expect(()=>buildShortageIntent("3","7","9",[{...row,quantity:0}],id)).toThrow();
    const pending=prepareShortageCommand(actor,"3","7","9",[row],()=>id).pending;
    localStorage.setItem(pendingShortageKey(actor),JSON.stringify({...pending,scope:differentActor}));
    expect(()=>readPendingShortage(actor)).toThrow();
  });
  it("postcommit lost-201, reload, retry same UUID/body; never fresh GET proves completion",async()=>{
    let lost=true,commits=0;
    const seen:string[]=[];
    const stored=new Map<string,unknown>();
    const fetch=vi.fn(async(path:string,opts?:RequestInit)=>{
      expect(path).toBe("/dispatch/shortage-commands");
      expect(opts?.method).toBe("POST");
      const body=JSON.parse(String(opts?.body)) as ReturnType<typeof buildShortageIntent>;
      seen.push(String(opts?.body));
      if (!stored.has(body.request_id)){commits++;stored.set(body.request_id,receipt(body));}
      if(lost){lost=false;throw new Error("response lost AFTER commit");}
      return stored.get(body.request_id);
    });
    const firstProps=props(fetch);
    const first=renderHook(()=>useShortageCommandCommit(firstProps));
    await waitFor(()=>expect(first.result.current.busy).toBe(false));
    await act(async()=>expect(await first.result.current.save("3","7","9",[row])).toBe(false));
    const uuid=readPendingShortage(actor)!.command.request_id;
    expect(first.result.current.feedback).toBe("unknown");
    expect(first.result.current.hasUnresolved).toBe(true);
    expect(firstProps.onCommitted).not.toHaveBeenCalled();
    expect(commits).toBe(1);
    first.unmount();
    const againProps=props(fetch);
    const second=renderHook(()=>useShortageCommandCommit(againProps));
    await waitFor(()=>expect(second.result.current.pending?.command.request_id).toBe(uuid));
    expect(againProps.onRestored).toHaveBeenCalledOnce();
    await act(async()=>expect(await second.result.current.retry()).toBe(true));
    expect(commits).toBe(1);
    expect(seen).toHaveLength(2);
    expect(seen[0]).toBe(seen[1]);
    expect(readPendingShortage(actor)).toBeNull();
    expect(againProps.onCommitted).toHaveBeenCalledOnce();
    expect(second.result.current.pending).toBeNull();
  });
  it("looks up signed receipt after lost 201 without resending POST or trusting a shortage list", async()=>{
    const calls: Array<{path:string;method:string|undefined}> = [];
    let committed: ReturnType<typeof receipt> | null = null;
    const fetch = vi.fn(async(path:string,opts?:RequestInit):Promise<unknown>=>{
      calls.push({path,method:opts?.method});
      if (opts?.method === "POST") {
        const command = JSON.parse(String(opts.body)) as ReturnType<typeof buildShortageIntent>;
        committed = receipt(command);
        throw new Error("lost response after database commit");
      }
      expect(path).toMatch(/^\/dispatch\/shortage-commands\/[0-9a-f-]{36}$/);
      expect(opts?.method).toBe("GET");
      expect(opts?.cache).toBe("no-store");
      return committed;
    });
    const p = props(fetch);
    const h = renderHook(()=>useShortageCommandCommit(p));
    await act(async()=>expect(await h.result.current.save("3","7","9",[row])).toBe(false));
    const originalUuid = readPendingShortage(actor)!.command.request_id;
    expect(h.result.current.hasUnresolved).toBe(true);
    await act(async()=>expect(await h.result.current.verify()).toBe(true));
    expect(calls).toEqual([
      {path:"/dispatch/shortage-commands",method:"POST"},
      {path:`/dispatch/shortage-commands/${originalUuid}`,method:"GET"},
    ]);
    expect(readPendingShortage(actor)).toBeNull();
    expect(p.onCommitted).toHaveBeenCalledOnce();
  });

  it.each([409,401,403,500])("HTTP %d never clears ambiguous UUID",async status=>{
    const fetch=vi.fn().mockRejectedValue(err(status));
    const hooked=renderHook(()=>useShortageCommandCommit(props(fetch)));
    await act(async()=>expect(await hooked.result.current.save("3","7","9",[row])).toBe(false));
    expect(readPendingShortage(actor)).not.toBeNull();
    expect(hooked.result.current.blocked).toBe([409,401,403].includes(status));
    if(status===401||status===403) expect(hooked.result.current.pending).toBeNull();
    else expect(hooked.result.current.pending).not.toBeNull();
    if ([409,401,403].includes(status)) expect(await hooked.result.current.retry()).toBe(false);
  });
  it("revoked/changed actor and removed shop never show or retry a private pending command",async()=>{
    prepareShortageCommand(actor,"3","7","9",[row],()=>id);
    const server=vi.fn().mockResolvedValue({request_id:id,lines:[]});
    const first=renderHook(({authorized,actorScope,allow})=>useShortageCommandCommit({
      ...props(server),authorized,actorScope,canRestore:()=>allow,
    }),{initialProps:{authorized:true,actorScope:actor,allow:true}});
    await waitFor(()=>expect(first.result.current.pending?.command.request_id).toBe(id));
    first.rerender({authorized:false,actorScope:actor,allow:true});
    expect(first.result.current.pending).toBeNull();
    await act(async()=>expect(await first.result.current.retry()).toBe(false));
    first.rerender({authorized:true,actorScope:differentActor,allow:true});
    await waitFor(()=>expect(first.result.current.pending).toBeNull());
    expect(readPendingShortage(actor)?.command.request_id).toBe(id);
    first.rerender({authorized:true,actorScope:actor,allow:false});
    await waitFor(()=>expect(first.result.current.blocked).toBe(true));
    expect(first.result.current.pending).toBeNull();
    expect(server).not.toHaveBeenCalled();
  });
  it("fails closed without browser write-ahead or cross-tab lock",async()=>{
    Object.defineProperty(navigator,"locks",{configurable:true,value:undefined});
    const server=vi.fn();
    const h=renderHook(()=>useShortageCommandCommit(props(server)));
    await act(async()=>expect(await h.result.current.save("3","7","9",[row])).toBe(false));
    expect(server).not.toHaveBeenCalled();
    expect(readPendingShortage(actor)).toBeNull();
  });
});
describe.each(["en","ar"] as const)("#1068 bilingual recovered UNKNOWN UI %s",language=>{
  it.each([390,1440])("shows explicit same-key retry but no automatic urgent for %ipx",async width=>{
    await setAppLanguage(language);
    Object.defineProperty(window,"innerWidth",{configurable:true,value:width});
    const original=prepareShortageCommand(actor,"3","7","9",[row],()=>id).pending;
    const retry=vi.fn();
    const verify=vi.fn();
    render(<ShortageModal
      isOpen canCreate canCancel canEdit onClose={vi.fn()}
      zones={zones} activeShops={shops}
      shortageZoneId="3" shortageShopId="7" onZoneChange={vi.fn()} onShopChange={vi.fn()}
      productScope={actor}
      shortageDraft={[row]} onAddProductToDraft={vi.fn()} onRemoveProductFromDraft={vi.fn()}
      onUpdateDraftQty={vi.fn()} onClearDraft={vi.fn()} onConfirmShortages={vi.fn()}
      shortages={[]} onDeleteShortage={vi.fn()} onDeleteShortageGroup={vi.fn()}
      onEditShortageGroup={vi.fn()} editingShortageIds={[]} onCancelEdit={vi.fn()}
      drivers={drivers} shortageDriverId="9" onDriverChange={vi.fn()}
      commandRecovery={{pending:original,blocked:false,busy:false,feedback:"unknown",onRetry:retry,onVerify:verify}}
      groupRecovery={{pending:null,blocked:false,restoring:false,busy:false,
        feedback:null,httpReference:null,onRetry:vi.fn()}}
    />);
    expect(screen.getByTestId("shortage-post-recovery")).toBeInTheDocument();
    expect(screen.getByTestId("shortage-command-uuid")).toHaveTextContent(id);
    expect(screen.getByTestId("shortage-quick-composer")).toBeDisabled();
    expect(screen.queryByText(language==="ar"?"عاجل":"Urgent")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("shortage-command-lookup"));
    expect(verify).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId("shortage-command-retry"));
    expect(retry).toHaveBeenCalledOnce();
  });
});
