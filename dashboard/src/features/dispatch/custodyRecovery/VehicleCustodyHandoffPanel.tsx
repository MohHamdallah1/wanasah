import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorCode, apiErrorStatus } from "@/lib/apiErrors";
import { loadCustody, type AuthorizedFetch } from "./command";
import { custodyStockStatus } from "./copy";
import { formatCustodyStockQuantity } from "./stockPresentation";
import { visibleCustodyLines } from "./handoffPresentation";
import { approveHandoff, cancelHandoff, getCurrentHandoff, loadCustodyHistory,
  sendHandoff, type HandoffRecord, type HandoffHistoryRow } from "./handoffApi";
import { handoffCopy, handoffError } from "./handoffCopy";
import type { Readiness, Receipt, StockReview } from "./contract";
import type { RecoveryDriver } from "./VehicleCustodyRecoveryPanel";

type Props={
  open:boolean;onClose:()=>void;vehicleId:string;vehicleLabel:string;
  drivers:readonly RecoveryDriver[];selectedDriverId?:string;
  fetch:AuthorizedFetch;actorScope:string|null;authorized:()=>boolean;
  onAccepted:(receipt:Receipt)=>void;
};
type Command={kind:"send"|"cancel"|"approve";id:string;body?:{
  request_id:string;target_driver_id:number;expected_context_revision:number;expected_stock_snapshot:string;
}};
const active=(record:HandoffRecord|null)=>
  record?.state==="PENDING"||record?.state==="CONFIRMED";
const terminal=(state:string)=>state==="CANCELLED"||state==="EXPIRED"||state==="DECLINED";
const dateLabel=(value:string|null|undefined,language:string)=>{
  if(!value)return "";
  const date=new Date(value);
  return Number.isNaN(date.valueOf())?"":new Intl.DateTimeFormat(language.startsWith("ar")?"ar":"en",{
    year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",
  }).format(date);
};
/** Existing C03 vehicle modal: no new custody authority, clipboard or stored token. */
export function VehicleCustodyHandoffPanel({
  open,onClose,vehicleId,vehicleLabel,drivers,selectedDriverId,fetch,actorScope,
  authorized,onAccepted,
}:Props){
  const {i18n}=useTranslation(),t=handoffCopy(i18n.language);
  const fetchRef=useRef(fetch),authRef=useRef(authorized),acceptedRef=useRef(onAccepted);
  fetchRef.current=fetch;authRef.current=authorized;acceptedRef.current=onAccepted;
  const [record,setRecord]=useState<HandoffRecord|null>(null);
  const [ready,setReady]=useState<Readiness|null>(null);
  const [stock,setStock]=useState<StockReview|null>(null);
  const [recipient,setRecipient]=useState(selectedDriverId??"");
  const [history,setHistory]=useState<HandoffHistoryRow[]>([]);
  const [historyError,setHistoryError]=useState(false);
  const [historyLoading,setHistoryLoading]=useState(true);
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
  const [blocked,setBlocked]=useState(false),[notice,setNotice]=useState("");
  const [changeConfirm,setChangeConfirm]=useState(false);
  const [refreshKey,setRefreshKey]=useState(0);
  const request=useRef<Command|null>(null);
  const pending=useRef(false),lifetime=useRef(0);
  const allowed=!!actorScope&&/^[1-9]\d*$/.test(vehicleId)&&authRef.current();

  useEffect(()=>{
    lifetime.current++;const current=lifetime.current;
    setRecord(null);setReady(null);setStock(null);setNotice("");setBlocked(false);
    setLoading(true);setRecipient(selectedDriverId??"");setHistory([]);setHistoryError(false);
    setHistoryLoading(true);
    setChangeConfirm(false);request.current=null;pending.current=false;setBusy(false);
    if(!open||!allowed){setLoading(false);return;}
    const controller=new AbortController();
    const live=()=>lifetime.current===current&&!controller.signal.aborted&&authRef.current();
    void (async()=>{
      // Server current is the first authority; a stale/failed read NEVER opens a new request.
      try{
        const server=await getCurrentHandoff(fetchRef.current,vehicleId,controller.signal);
        if(!live())return;
        setRecord(server);
        if(server)setRecipient(String(server.target_driver_id));
        const value=await loadCustody(fetchRef.current,vehicleId,controller.signal);
        if(!live())return;
        setReady(value.ready);setStock(value.stock);
        setBlocked(value.ready.recovery_action==="CUSTODY_INVESTIGATE");
      }catch(err){
        if(live()){setBlocked(true);setNotice(handoffError(err,i18n.language));}
      }finally{if(live())setLoading(false);}
    })();
    void loadCustodyHistory(fetchRef.current,vehicleId,controller.signal)
      .then(value=>{if(live()){setHistory(value);setHistoryLoading(false);}})
      .catch(()=>{if(live()){setHistoryError(true);setHistoryLoading(false);}});
    return()=>{controller.abort();}; // abort signal also fences all late responses
  },[open,allowed,vehicleId,actorScope,selectedDriverId,refreshKey,i18n.language]);

  // No background worker: only poll when modal is visible and a receipt can change.
  const shouldPoll=active(record);
  useEffect(()=>{
    if(!open||!allowed||!shouldPoll)return;
    let stopped=false;
    const timer=window.setInterval(()=>{
      if(pending.current||stopped)return;
      void getCurrentHandoff(fetchRef.current,vehicleId).then(server=>{
        if(stopped||!authRef.current())return;
        if(server){setRecord(server);setRecipient(String(server.target_driver_id));}
        else setNotice(t.generic); // never silently erase an active signed request
      }).catch(err=>{if(!stopped)setNotice(handoffError(err,i18n.language));});
    },5000);
    return()=>{stopped=true;window.clearInterval(timer);};
  },[open,allowed,vehicleId,actorScope,shouldPoll,i18n.language,t.generic]);

  const refresh=()=>{if(!pending.current)setRefreshKey(n=>n+1);};
  const transact=async(action:()=>Promise<void>)=>{
    if(!allowed||pending.current)return;
    pending.current=true;setBusy(true);setNotice("");const serial=lifetime.current;
    try{await action();}
    catch(err){
      if(serial===lifetime.current){
        setNotice(handoffError(err,i18n.language));
        // Response could have been lost. Read server state before offering another command.
        try{
          const authoritative=await getCurrentHandoff(fetchRef.current,vehicleId);
          if(serial===lifetime.current&&authoritative){
            setRecord(authoritative);setRecipient(String(authoritative.target_driver_id));
          }else if(serial===lifetime.current)setBlocked(true);
        }catch{if(serial===lifetime.current)setBlocked(true);}
      }
    }finally{pending.current=false;if(serial===lifetime.current)setBusy(false);}
  };
  const send=()=>{
    if(!ready||!stock||!recipient||active(record)||blocked||loading)return;
    if(!/^[1-9]\d*$/.test(recipient))return;
    const body={request_id:crypto.randomUUID(),target_driver_id:Number(recipient),
      expected_context_revision:ready.context_revision,expected_stock_snapshot:stock.stock_snapshot};
    // Do not create a different command after a lost response.
    const saved=request.current;
    if(saved&&saved.kind!=="send")request.current=null;
    const exact=request.current?.kind==="send"&&request.current.body?.target_driver_id===body.target_driver_id
      ?request.current.body:body;
    request.current={kind:"send",id:exact.request_id,body:exact};
    void transact(async()=>{
      const result=await sendHandoff(fetchRef.current,vehicleId,exact);
      setRecord(result);setRecipient(String(result.target_driver_id));request.current=null;
    });
  };
  const cancel=()=>{
    if(!record||!active(record))return;
    const command=request.current?.kind==="cancel"?request.current:
      {kind:"cancel" as const,id:crypto.randomUUID()};
    request.current=command;
    void transact(async()=>{
      const result=await cancelHandoff(fetchRef.current,vehicleId,record.handoff_id,command.id);
      setRecord(result);request.current=null;setChangeConfirm(false);
      setRecipient(""); // only AFTER confirmed server cancellation
      setRefreshKey(n=>n+1); // recheck current revision/stock for a new recipient
    });
  };
  const approve=()=>{
    if(record?.state!=="CONFIRMED")return;
    const command=request.current?.kind==="approve"?request.current:
      {kind:"approve" as const,id:crypto.randomUUID()};
    request.current=command;
    void transact(async()=>{
      const receipt=await approveHandoff(fetchRef.current,vehicleId,record.handoff_id,command.id);
      setRecord({...record,state:"COMMITTED"});request.current=null;
      acceptedRef.current(receipt); // caller invalidates vehicle eligibility after authoritative commit
    });
  };
  const label=record?.recipient_label||drivers.find(x=>x.id===recipient)?.label||"";
  const listed=useMemo(()=>stock?visibleCustodyLines(stock.stock_lines):[],[stock]);
  const canSend=!loading&&!blocked&&!busy&&!!ready&&!!stock&&!active(record)&&
    record?.state!=="COMMITTED"&&!!recipient&&drivers.some(d=>d.id===recipient&&d.available!==false);
  return <Modal isOpen={open} onClose={onClose} title={t.title} maxWidth="max-w-2xl">
    <section data-testid="c03-custody-panel" dir={i18n.dir()} className="min-w-0 space-y-3">
      <header className="rounded-lg border p-3">
        <p className="font-semibold break-words">{vehicleLabel}</p>
        <p className="text-xs text-slate-600">{t.noMovement}</p>
      </header>
      {!allowed&&<p role="alert">{t.noAccess}</p>}
      {loading&&<p role="status">{t.loading}</p>}
      {notice&&<p role="alert" className="rounded-lg border p-2 text-sm break-words">{notice}</p>}
      {record&&<div className="rounded-lg border border-sky-200 bg-sky-50 p-3 space-y-1"
        role="status" data-testid="custody-handoff-server-status">
        <p className="font-semibold">{record.state==="PENDING"?t.awaiting:
          record.state==="CONFIRMED"?t.confirmed:
          record.state==="DECLINED"?t.declined:
          record.state==="EXPIRED"?t.expired:
          record.state==="CANCELLED"?t.cancelled:t.committed}</p>
        <p>{t.recipient}: <b>{record.recipient_label}</b></p>
        <p className="text-xs">{dateLabel(record.expires_at,i18n.language)}</p>
        {record.state==="DECLINED"&&<p className="text-sm break-words">{record.reason_text||record.reason_code||t.declined}</p>}
      </div>}
      {stock&&<section className="rounded-lg border">
        <h3 className="border-b px-3 py-2 text-sm font-semibold">{t.stock}</h3>
        {!listed.length&&<p className="p-3 text-sm">{t.empty}</p>}
        <ul className="max-h-56 overflow-y-auto p-2 space-y-2">
          {listed.map((line,i)=><li key={i} className="rounded-lg border p-2 text-sm min-w-0">
            <b className="break-words">{line.product_name}</b>
            <p className="text-slate-600">{line.batch_number? t.lot+": "+line.batch_number:t.noLot}
              {line.expiry_date&&" · "+t.expiry+": "+line.expiry_date}</p>
            <p>{t.quantity}: <bdi>{formatCustodyStockQuantity(line)}</bdi>
              {" · "}{t.status}: {custodyStockStatus(line.stock_status,i18n.language)}
              {Number(line.reserved_base)>0&&<> · {t.reserved}:{" "}
                <bdi>{formatCustodyStockQuantity({...line,on_hand_base:line.reserved_base})}</bdi></>}</p>
          </li>)}
        </ul>
      </section>}
      {allowed&&!loading&&!active(record)&&record?.state!=="COMMITTED"&&!blocked&&
        <div className="grid gap-2">
          <label className="grid gap-1 text-sm font-semibold">{t.recipient}
            <select aria-label={t.recipient} value={recipient}
              onChange={e=>{request.current=null;setRecipient(e.target.value);}}
              className="min-w-0 min-h-11 rounded-lg border p-2">
              <option value="">{t.choose}</option>
              {drivers.filter(d=>d.available!==false).map(d=>
                <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </label>
          <button type="button" disabled={!canSend} onClick={send}
            className="min-h-11 rounded-lg bg-sky-700 p-2 font-semibold text-white disabled:opacity-40">{t.send}</button>
        </div>}
      {allowed&&record?.state==="CONFIRMED"&&!changeConfirm&&
        <button type="button" disabled={busy} onClick={approve}
          className="min-h-11 w-full rounded-lg bg-blue-700 p-2 text-white font-semibold disabled:opacity-40">
          {t.approve}</button>}
      {allowed&&active(record)&&<>
        {!changeConfirm?<div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={()=>setChangeConfirm(true)}
            className="min-h-11 rounded-lg border p-2">{t.change}</button>
          <button type="button" disabled={busy} onClick={()=>setChangeConfirm(true)}
            className="min-h-11 rounded-lg border p-2">{t.cancel}</button>
        </div>:<div className="rounded-lg border border-amber-300 p-3 space-y-2">
          <p role="alert" className="text-sm">{t.cancelWarning}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={cancel}
              className="min-h-11 rounded-lg bg-red-700 px-3 py-2 text-white">{t.confirmCancel}</button>
            <button type="button" disabled={busy} onClick={()=>setChangeConfirm(false)}
              className="min-h-11 rounded-lg border px-3 py-2">{t.abort}</button>
          </div>
        </div>}
      </>}
      {allowed&&(!loading||blocked)&&<button type="button" disabled={busy} onClick={refresh}
        className="min-h-10 rounded-lg border px-3 py-2">{blocked?t.reload:t.refresh}</button>}
      <section aria-label={t.history} className="rounded-lg border p-3 space-y-2">
        <h3 className="font-semibold">{t.history}</h3>
        {historyLoading&&<p role="status" className="text-sm">{t.loading}</p>}
        {historyError&&<p role="status" className="text-sm">{t.unavailableHistory}</p>}
        {!historyLoading&&!historyError&&!history.length&&<p className="text-sm">{t.noneHistory}</p>}
        <ul className="space-y-2">{history.map((entry,i)=>{
          const undocumented=entry.evidence_origin==="M01_BACKFILL"||
            (!entry.recipient_label&&!entry.custodian_label);
          const whom=undocumented?t.unknownHistory:(entry.recipient_label||entry.custodian_label);
          return <li key={i} className="border-t pt-2 text-sm">
            <p className="font-semibold break-words">{whom}</p>
            {(entry.started_at||entry.accepted_at)&&<p>{t.since}: {dateLabel(entry.started_at||entry.accepted_at,i18n.language)}</p>}
            {entry.ended_at&&<p>{t.until}: {dateLabel(entry.ended_at,i18n.language)}</p>}
            {(entry.approved_by_label||entry.manager_label)&&
              <p>{t.approvedBy}: {entry.approved_by_label||entry.manager_label}</p>}
          </li>;
        })}</ul>
      </section>
    </section>
  </Modal>;
}
