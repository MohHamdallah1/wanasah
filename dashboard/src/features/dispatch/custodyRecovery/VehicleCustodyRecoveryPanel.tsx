import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorCode, apiErrorStatus } from "@/lib/apiErrors";
import {
  acceptOnce, loadCustody, prepareHandoff, pendingClear, pendingKey,
  pendingRead, pendingSave, statusByRequest, validVehicleId, type AuthorizedFetch,
} from "./command";
import { custodyCopy, custodyReason } from "./copy";
import type { Offer, Readiness, Receipt, StockReview } from "./contract";

type Step="checking"|"ready"|"offered"|"posting"|"unknown"|"done"|"blocked"|"denied";
type Command={id:string;proof:string};
export type RecoveryDriver={id:string;label:string;available?:boolean};

/** The LEAD binds this component to the Dispatch blocked vehicle selector
 * after #973 is merged. All C03 implementation lives outside DispatchBoard.
 */
export function VehicleCustodyRecoveryPanel({
  open,onClose,vehicleId,vehicleLabel,drivers,selectedDriverId,
  fetch,actorScope,authorized,onAccepted,
}:{
  open:boolean;onClose:()=>void;vehicleId:string;vehicleLabel:string;
  drivers:readonly RecoveryDriver[];selectedDriverId?:string;
  fetch:AuthorizedFetch;actorScope:string|null;authorized:()=>boolean;
  onAccepted:(receipt:Receipt)=>void;
}){
  const {i18n}=useTranslation(), t=custodyCopy(i18n.language);
  const [step,setStep]=useState<Step>("checking");
  const [ready,setReady]=useState<Readiness|null>(null);
  const [stock,setStock]=useState<StockReview|null>(null);
  const [recipient,setRecipient]=useState(selectedDriverId||"");
  const [offer,setOffer]=useState<Offer|null>(null);
  const [proof,setProof]=useState("");
  const [notice,setNotice]=useState("");
  const inFlight=useRef(false),epoch=useRef(0),original=useRef<Command|null>(null);
  // Identity/permission callbacks may be re-created during an ordinary render.
  // Never discard an in-progress signed handoff merely because their refs move.
  const authRef=useRef(authorized),onAcceptedRef=useRef(onAccepted);
  authRef.current=authorized;onAcceptedRef.current=onAccepted;
  const allowed=!!actorScope&&validVehicleId(vehicleId)&&authRef.current();
  const key=actorScope&&validVehicleId(vehicleId)?pendingKey(actorScope,vehicleId):null;

  const clear=useCallback(()=>{
    epoch.current++;original.current=null;inFlight.current=false;
    setReady(null);setStock(null);setOffer(null);setProof("");
    setNotice("");setStep("checking");
  },[]);

  useEffect(()=>{
    clear();setRecipient(selectedDriverId||"");
    if(!open||!allowed||!key){setStep("denied");return;}
    const controller=new AbortController(),serial=epoch.current;
    const current=()=>!controller.signal.aborted&&epoch.current===serial&&authRef.current();
    void (async()=>{
      try{
        // The pending request UUID is NOT a secret; no offer/receipt is stored.
        const prior=pendingRead(key);
        if(prior&&/^[0-9a-f-]{36}$/i.test(prior)){
          const result=await statusByRequest(fetch,vehicleId,prior);
          if(!current())return;
          if(result.state==="COMMITTED"){
            pendingClear(key);setStep("done");setNotice(t.complete);
            onAcceptedRef.current({state:"ACCEPTED",vehicle_id:Number(vehicleId),
              context_revision:result.context_revision,epoch_id:result.epoch_id,
              replayed:true,stock_movements:0});
            return;
          }
          // UNKNOWN is not proof of failure: the original POST may still commit.
          // Keep its exact UUID across reload; never silently create a second command.
          original.current={id:prior,proof:""};
          setStep("unknown");setNotice(t.unknown);
          return;
        }
        pendingClear(key);
        const value=await loadCustody(fetch,vehicleId,controller.signal);
        if(!current())return;
        setReady(value.ready);setStock(value.stock);
        setStep(value.ready.recovery_action==="CUSTODY_INVESTIGATE"?"blocked":"ready");
      }catch(err){
        if(!current())return;
        const denied=[401,403].includes(apiErrorStatus(err)??-1);
        const uncertain=key?pendingRead(key):null;
        if(!denied&&uncertain&&/^[0-9a-f-]{36}$/i.test(uncertain)){
          // The status read itself may be offline. Never let a generic
          // stock reload silently discard the earlier acceptance UUID.
          original.current={id:uncertain,proof:""};
          setNotice(t.unknown);setStep("unknown");
          return;
        }
        setNotice(custodyReason(apiErrorCode(err)||"",i18n.language));
        setStep(denied?"denied":"blocked");
      }
    })();
    return()=>{controller.abort();epoch.current++;original.current=null;};
  },[open,vehicleId,actorScope,selectedDriverId,allowed,fetch,key,clear,
    i18n.language,t.complete,t.unknown]);

  const reload=async()=>{
    if(!allowed||inFlight.current)return;
    inFlight.current=true;const serial=epoch.current;
    setStep("checking");setNotice("");setOffer(null);setProof("");original.current=null;
    if(key)pendingClear(key);
    const controller=new AbortController();
    try{
      const value=await loadCustody(fetch,vehicleId,controller.signal);
      if(serial!==epoch.current||!authRef.current())return;
      setReady(value.ready);setStock(value.stock);
      setStep(value.ready.recovery_action==="CUSTODY_INVESTIGATE"?"blocked":"ready");
    }catch(err){
      if(serial===epoch.current){
        setNotice(custodyReason(apiErrorCode(err)||"",i18n.language));
        setStep([401,403].includes(apiErrorStatus(err)??-1)?"denied":"blocked");
      }
    }finally{inFlight.current=false;}
  };

  const prepare=async()=>{
    if(!allowed||!ready||!stock||!recipient||inFlight.current)return;
    inFlight.current=true;setNotice("");const serial=epoch.current;
    try{
      const value=await prepareHandoff(fetch,vehicleId,recipient,ready,stock);
      if(serial!==epoch.current||!authRef.current())return;
      setOffer(value);setProof("");setStep("offered");
    }catch(err){
      if(serial!==epoch.current)return;
      setNotice(custodyReason(apiErrorCode(err)||"",i18n.language));
      setStep("blocked");
    }finally{inFlight.current=false;}
  };

  const approve=async()=>{
    if(!allowed||!key||!proof.trim()||inFlight.current||
      (!offer&&!(step==="unknown"&&original.current)))return;
    if(proof.trim().length<50||proof.trim().length>2048){setNotice(t.invalid);return;}
    // A reloaded tab retains only the UUID, never the sensitive FIELD proof.
    // Re-pasting the ORIGINAL receipt retries that same server operation.
    if(original.current?.proof&&original.current.proof!==proof.trim()){
      setNotice(t.unknown);return;
    }
    const command=original.current
      ?{id:original.current.id,proof:proof.trim()}
      :{id:crypto.randomUUID(),proof:proof.trim()};
    original.current=command;
    pendingSave(key,command.id); // Never persist receiver_proof.
    inFlight.current=true;setStep("posting");setNotice("");
    const serial=epoch.current;
    try{
      const result=await acceptOnce(fetch,vehicleId,command.id,command.proof);
      if(serial!==epoch.current||!authRef.current())return;
      if(result.kind==="committed"){
        pendingClear(key);original.current=null;setOffer(null);setProof("");
        setStep("done");setNotice(t.complete);onAcceptedRef.current(result.receipt);return;
      }
      if(result.kind==="unknown"){
        try{
          const status=await statusByRequest(fetch,vehicleId,command.id);
          if(serial!==epoch.current||!authRef.current())return;
          if(status.state==="COMMITTED"){
            pendingClear(key);original.current=null;setOffer(null);setProof("");
            setStep("done");setNotice(t.complete);
            onAcceptedRef.current({state:"ACCEPTED",vehicle_id:Number(vehicleId),
              epoch_id:status.epoch_id,context_revision:status.context_revision,
              replayed:true,stock_movements:0});
            return;
          }
        }catch{/* Unknown can only be retried with immutable original UUID/proof. */}
        setStep("unknown");setNotice(t.unknown);return;
      }
      pendingClear(key);original.current=null;setProof("");setOffer(null);
      setStep(result.kind==="denied"?"denied":"blocked");
      setNotice(custodyReason(result.code||"",i18n.language));
    }finally{inFlight.current=false;}
  };

  const verifyPending=async()=>{
    if(!allowed||!key||!original.current||inFlight.current)return;
    inFlight.current=true;const serial=epoch.current;
    try{
      const status=await statusByRequest(fetch,vehicleId,original.current.id);
      if(serial!==epoch.current||!authRef.current())return;
      if(status.state==="COMMITTED"){
        pendingClear(key);original.current=null;setProof("");setOffer(null);
        setStep("done");setNotice(t.complete);
        onAcceptedRef.current({state:"ACCEPTED",vehicle_id:Number(vehicleId),
          context_revision:status.context_revision,epoch_id:status.epoch_id,
          replayed:true,stock_movements:0});
      }else{setStep("unknown");setNotice(t.unknown);}
    }catch{
      if(serial===epoch.current&&authRef.current()){
        setStep("unknown");setNotice(t.unknown);
      }
    }finally{inFlight.current=false;}
  };

  const close=()=>{if(inFlight.current)return;clear();onClose();};
  const showStock=!!stock&&["ready","offered","posting","unknown"].includes(step);
  return <Modal isOpen={open} onClose={close} title={t.title} maxWidth="max-w-2xl">
    <section data-testid="c03-custody-panel" dir={i18n.dir()} className="min-w-0 space-y-3">
      <header className="rounded-xl bg-sky-50 p-3">
        <p className="break-words font-bold">{vehicleLabel}</p>
        <p className="mt-1 text-sm text-slate-700">{t.info}</p>
      </header>
      {step==="checking"&&<p role="status">{t.loading}</p>}
      {step==="denied"&&<p role="alert">{t.noAccess}</p>}
      {ready&&<p role="status" className="text-sm text-amber-800">
        {ready.recovery_action==="CUSTODY_FIRST_ACCEPT"
          ?ready.state==="NO_EPOCH"?t.none:t.first
          :ready.recovery_action==="CUSTODY_REASSIGN"?t.other:t.invalid}
      </p>}
      {notice&&<p role={step==="done"?"status":"alert"}
        className="rounded-lg border p-3 text-sm break-words">{notice}</p>}
      {showStock&&<div className="rounded-lg border">
        <h4 className="border-b bg-slate-50 p-2 text-sm font-bold">{t.stock}</h4>
        {!stock.stock_lines.length&&<p className="p-3 text-sm">{t.noStock}</p>}
        <ul className="max-h-56 space-y-2 overflow-y-auto p-2">
          {stock.stock_lines.map((line,index)=><li key={index}
            className="min-w-0 rounded-lg border p-2 text-sm">
            <p className="break-words font-semibold">{line.product_name}</p>
            <p className="break-words text-slate-600">{t.batch}: {line.batch_number}
              {line.expiry_date&&<> · {t.exp}: {line.expiry_date}</>}
            </p>
            <p className="break-words">{t.base}: <bdi>{line.on_hand_base}</bdi> {line.base_uom}
              {" · "}{t.status}: {line.stock_status}
              {Number(line.reserved_base)>0&&<> · {t.reserved}: {line.reserved_base}</>}
            </p>
          </li>)}
        </ul>
      </div>}
      {step==="ready"&&<div className="grid gap-3">
        <label className="grid gap-1 text-sm font-semibold">{t.rep}
          <select aria-label={t.rep} value={recipient}
            onChange={e=>setRecipient(e.target.value)}
            className="min-h-11 min-w-0 rounded-lg border p-2">
            <option value="">{t.select}</option>
            {drivers.filter(x=>x.available!==false).map(x=>
              <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
        </label>
        <button type="button" disabled={!recipient||inFlight.current}
          onClick={()=>void prepare()}
          className="rounded-lg bg-sky-700 p-3 font-semibold text-white disabled:opacity-40">{t.prepare}</button>
      </div>}
      {["offered","posting","unknown"].includes(step)&&offer&&<>
        <p className="text-sm">{t.handoff}</p>
        <button type="button" disabled={step==="posting"} className="rounded-lg border px-4 py-2"
          onClick={()=>{void navigator.clipboard.writeText(offer.offer_token)
            .then(()=>setNotice(t.copied)).catch(()=>setNotice(t.missing));}}>{t.copyHandoff}</button>
        <label className="grid gap-1 text-sm font-semibold">{t.proof}
          <textarea aria-label={t.proof} value={proof}
            onChange={e=>setProof(e.target.value)}
            disabled={step==="posting"||step==="unknown"&&!!original.current}
            rows={3} maxLength={2048} autoComplete="off" spellCheck={false}
            className="min-w-0 w-full rounded-lg border p-3 font-mono text-xs"/>
        </label>
        <button type="button" disabled={step==="posting"||!proof.trim()}
          onClick={()=>void approve()}
          className="rounded-lg bg-blue-700 p-3 font-semibold text-white disabled:opacity-40">
          {step==="unknown"?t.verify:t.approve}</button>
      </>}
      {step==="unknown"&&!offer&&original.current&&<div className="grid gap-2">
        <button type="button" onClick={()=>void verifyPending()}
          className="min-h-10 rounded-lg border px-4 py-2">{t.verify}</button>
        <label className="grid gap-1 text-sm font-semibold">{t.proof}
          <textarea aria-label={t.proof} value={proof} onChange={e=>setProof(e.target.value)}
            rows={3} maxLength={2048} autoComplete="off" spellCheck={false}
            className="min-w-0 w-full rounded-lg border p-3 font-mono text-xs"/>
        </label>
        <button type="button" disabled={!proof.trim()||inFlight.current}
          onClick={()=>void approve()}
          className="min-h-10 rounded-lg bg-blue-700 p-3 font-semibold text-white disabled:opacity-40">
          {t.approve}
        </button>
      </div>}
      {step==="blocked"&&<button type="button" onClick={()=>void reload()}
        className="rounded-lg border px-4 py-2">{t.refresh}</button>}
      <p className="text-xs text-slate-600">{t.safe}</p>
    </section>
  </Modal>;
}
