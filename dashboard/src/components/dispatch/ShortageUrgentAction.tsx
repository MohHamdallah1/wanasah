import { useEffect, useId, useRef, useState } from "react";
import type { Shortage } from "@/types/dispatch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { allowedUrgentDriver, parseUrgentQuote, urgentBudget, type UrgentQuote } from "@/features/dispatch/shortageUrgent/contract";
import type { UrgentPromotion } from "@/features/dispatch/shortageUrgent/useUrgentPromotion";

export function ShortageUrgentAction({row, promotion, language, disabled}:{
  row:Shortage; promotion?:UrgentPromotion; language:string; disabled:boolean;
}) {
  const text=(key:Parameters<typeof dispatchUiText>[1],values?:Record<string,string|number>)=>dispatchUiText(language,key,values);
  const budget=urgentBudget(row);
  const drivers=promotion?.drivers.filter(d=>allowedUrgentDriver(row,d))??[];
  const [open,setOpen]=useState(false);
  const [choice,setChoice]=useState("");
  const [quantity,setQuantity]=useState("");
  const [quoteState,setQuoteState]=useState<{key:string;quote:UrgentQuote|null;loading:boolean}>({key:"",quote:null,loading:false});
  const driver=drivers.find(d=>d.id===(row.driverId||choice));
  const permitted=Boolean(promotion?.authorized && promotion.canSee(row) && budget && budget.unassigned>0 && drivers.length && !disabled && !promotion.unresolved);
  const key=JSON.stringify([row.id,row.productId,row.driverId,budget?.unassigned,driver?.id,driver?.vehicle]);
  const quote=quoteState.key===key ? quoteState.quote : null;
  const loading=!!driver && (quoteState.key!==key||quoteState.loading);
  const triggerRef=useRef<HTMLButtonElement>(null);
  const inputRef=useRef<HTMLInputElement>(null);
  const selectionRef=useRef<HTMLSelectElement>(null);
  const id=useId();
  const fetch=promotion?.fetch;
  useEffect(()=>{
    if(!open||!permitted||!driver||!fetch)return;
    const controller=new AbortController();
    setQuoteState({key,quote:null,loading:true});
    setQuantity("");
    const params=new URLSearchParams({driver_id:driver.id,product_ids:row.productId});
    void fetch("/dispatch/shortages/vehicle-availability?"+params,{signal:controller.signal,cache:"no-store"})
      .then(raw=>{if(!controller.signal.aborted)setQuoteState({key,quote:parseUrgentQuote(raw,row,driver),loading:false});})
      .catch(()=>{if(!controller.signal.aborted)setQuoteState({key,quote:null,loading:false});});
    return ()=>controller.abort();
    // The key includes all identity and budget fields used by the parser.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[open,permitted,key,fetch]);
  useEffect(()=>{if(!permitted){setOpen(false);setQuoteState({key:"",quote:null,loading:false});setChoice("");setQuantity("");}},[permitted]);
  useEffect(()=>{if(open){if(row.driverId)inputRef.current?.focus();else selectionRef.current?.focus();}},[open,row.driverId]);
  const close=()=>{setOpen(false);setQuoteState({key:"",quote:null,loading:false});setChoice("");setQuantity("");requestAnimationFrame(()=>triggerRef.current?.focus());};
  const qty=/^[1-9]\d*$/.test(quantity)?Number(quantity):0;
  const valid=permitted&&!!quote&&!loading&&Number.isSafeInteger(qty)&&qty>0&&qty<=quote.limit&&!!driver;
  return <div className="mt-1 min-w-0 space-y-1">
    <p data-testid={"shortage-urgent-budget-"+row.id} className="break-words text-[11px] font-normal leading-5 text-slate-600">
      {budget?text("shortageUrgentBudget",{active:budget.active,unassigned:budget.unassigned}):text("shortageUrgentBudgetUnknown")}
    </p>
    {permitted&&!open&&<button type="button" ref={triggerRef} onClick={()=>setOpen(true)}
      data-testid={"shortage-urgent-open-"+row.id}
      className="min-h-9 rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs font-bold text-sky-800 hover:bg-sky-100 focus-visible:ring-2 focus-visible:ring-sky-400">
      {text("shortageUrgentOpen")}
    </button>}
    {open&&permitted&&<div role="group" aria-label={text("shortageUrgentOpen")} className="min-w-0 space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-2 text-xs font-normal"
      onKeyDown={event=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();close();}}}>
      {!row.driverId?<label className="block">{text("shortageUrgentDriver")}
        <select ref={selectionRef} value={choice} onChange={e=>setChoice(e.target.value)} className="mt-1 block min-h-10 w-full min-w-0 rounded border bg-white px-2" data-testid={"shortage-urgent-driver-"+row.id}>
          <option value="">{text("shortageUrgentChooseDriver")}</option>
          {drivers.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </label>:<p className="break-words">{text("shortageUrgentDriver")}: {driver?.name}</p>}
      {driver&&<p role="status" className="break-words" data-testid={"shortage-urgent-quote-"+row.id}>
        {loading?text("shortageUrgentChecking"):quote?text("shortageUrgentQuote",{stock:quote.stock,unit:quote.unit,max:quote.limit}):text("shortageUrgentQuoteUnknown")}
      </p>}
      <label htmlFor={id} className="block">{text("shortageUrgentQuantity",{unit:quote?.unit??""})}</label>
      <input id={id} ref={inputRef} type="text" inputMode="numeric" autoComplete="off" maxLength={16}
        value={quantity} onChange={e=>setQuantity(e.target.value)} disabled={!quote||loading||quote.limit===0}
        data-testid={"shortage-urgent-quantity-"+row.id} className="block min-h-10 w-full min-w-0 rounded border bg-white px-2 disabled:bg-slate-100"/>
      <p className="break-words text-slate-600">{text("shortageUrgentNotDelivery")}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!valid} data-testid={"shortage-urgent-confirm-"+row.id}
          onClick={()=>{if(valid&&driver){void promotion?.submit(row.id,driver.id,qty).then(ok=>{if(ok)close();});}}}
          className="min-h-11 rounded-lg bg-sky-800 px-3 text-xs font-bold text-white disabled:bg-slate-300 disabled:text-slate-600 focus-visible:ring-2 focus-visible:ring-sky-400">
          {text("shortageUrgentConfirm")}
        </button>
        <button type="button" onClick={close} className="min-h-11 rounded-lg border bg-white px-3 text-xs font-bold">{text("cancel")}</button>
      </div>
    </div>}
  </div>;
}
export function ShortageUrgentRecovery({promotion,language}:{promotion:UrgentPromotion;language:string}) {
  const text=(key:Parameters<typeof dispatchUiText>[1])=>dispatchUiText(language,key);
  if(!promotion.authorized||(!promotion.pending&&!promotion.feedback&&!promotion.busy))return null;
  const key=promotion.feedback==="conflict"?"shortageUrgentConflict":promotion.feedback==="denied"?"shortageUrgentDenied":
    promotion.feedback==="storage"?"shortageUrgentStorage":promotion.feedback==="another-tab"?"shortageUrgentAnotherTab":
    promotion.feedback==="stale"?"shortageUrgentStale":promotion.feedback==="committed"?"shortageUrgentCommitted":
    promotion.feedback==="refresh"?"shortageUrgentRefresh":"shortageUrgentUnknown";
  return <section role="status" data-testid="shortage-urgent-recovery" className="min-w-0 space-y-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-slate-800">
    <p className="font-semibold">{text(key)}</p>
    {promotion.pending&&<>
      <p dir="ltr" className="break-all font-mono" data-testid="shortage-urgent-uuid">{promotion.pending.body.request_id}</p>
      <p>{dispatchUiText(language,"shortageUrgentOriginal",{quantity:promotion.pending.body.quantity_base,driver:promotion.pending.body.driver_id})}</p>
      <button type="button" disabled={promotion.busy||promotion.blocked} onClick={()=>{void promotion.retry();}}
        data-testid="shortage-urgent-retry" className="min-h-11 rounded-lg bg-sky-800 px-3 font-bold text-white disabled:opacity-50">{text("shortageUrgentRetry")}</button>
    </>}
  </section>;
}
