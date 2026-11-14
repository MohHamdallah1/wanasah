import {useEffect,useRef,useState} from "react";
import {useTranslation} from "react-i18next";
import {useAuthFetch} from "@/hooks/useAuthFetch";

type Values={batch_number:string;production_date:string|null;expiry_date:string|null};
type Preview={
  batch_id:number;location_id:number;metadata_revision:number;
  current:Values;source_invoice:string|null;eligible:boolean;block_code:string|null;
};
type History={
  revision:number;verified_at:string;actor_username:string;source_invoice:string;
  reason:string;before:Values;after:Values;
};

export const batchCorrectionText=(language:string)=>language.startsWith("ar")?{
  edit:"تصحيح التشغيلة / تاريخ الصلاحية",
  heading:"تصحيح بيانات التشغيلة",invoice:"مرجع فاتورة الاستلام الأصلية",
  lot:"رقم التشغيلة الحقيقي",production:"تاريخ الإنتاج",expiry:"تاريخ الصلاحية",
  reason:"سبب التصحيح",password:"كلمة مرور المدير الحالية",
  confirm:"أؤكد أن البضاعة في المستودع ولم تُنقل أو تُبع أو تُحجز",
  save:"حفظ التصحيح",cancel:"إلغاء",history:"سجل التصحيحات",
  blocked:"التشغيلة غير مؤهلة للتعديل المباشر؛ اعزلها واطلب مراجعة المسؤول",
  fail:"تعذر تأكيد التصحيح. حدّث البيانات أو راجع المسؤول.",
  current:"الحالي",after:"المصحح",done:"تم حفظ التصحيح وتسجيله",
}:{
  edit:"Correct Lot / expiry",heading:"Correct batch metadata",
  invoice:"Original supplier receipt",lot:"Actual printed Lot",
  production:"Production date",expiry:"Expiry date",
  reason:"Correction reason",password:"Current manager account password",
  confirm:"I confirm all stock is untouched in its original warehouse",
  save:"Save correction",cancel:"Cancel",history:"Correction history",
  blocked:"This batch cannot be corrected directly. Quarantine and request manager review.",
  fail:"Correction not verified. Refresh or request manager review.",
  current:"Before",after:"After",done:"Correction saved with a permanent audit trail",
};

export function BatchMetadataCorrectionPanel({batchId,locationId,onChanged}:{
  batchId:number;locationId:number;onChanged:()=>void|Promise<void>;
}){
  const fetch=useAuthFetch();
  const {i18n}=useTranslation();
  const copy=batchCorrectionText(i18n.language);
  const [preview,setPreview]=useState<Preview|null>(null);
  const [history,setHistory]=useState<History[]>([]);
  const [editing,setEditing]=useState(false);
  const [lot,setLot]=useState("");
  const [production,setProduction]=useState("");
  const [expiry,setExpiry]=useState("");
  const [reason,setReason]=useState("");
  const [password,setPassword]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const request=useRef<{request_id:string;expected_revision:number;location_id:number;
    batch_number:string;production_date:string|null;expiry_date:string|null;
    reason:string;password:string}|null>(null);
  const path="/warehouse/batches/"+batchId;
  useEffect(()=>{
    let alive=true; const controller=new AbortController();
    setPreview(null);setHistory([]);setEditing(false);request.current=null;
    void Promise.all([
      fetch(path+"/metadata-correction?location_id="+locationId,{signal:controller.signal}),
      fetch(path+"/metadata-corrections/history?location_id="+locationId,{signal:controller.signal}),
    ]).then(([p,h])=>{
      if(!alive)return;
      const view=p as Preview, log=h as {items:History[]};
      if(view?.batch_id!==batchId||view.location_id!==locationId||
         !Number.isSafeInteger(view.metadata_revision)||!Array.isArray(log?.items))
        throw Error("BATCH_CORRECTION_SCOPE_MISMATCH");
      setPreview(view);setHistory(log.items.slice(0,50));
    }).catch(()=>{if(alive)setError(copy.fail);});
    return ()=>{alive=false;controller.abort();};
  // Inputs are scoped by the authenticated selected batch/location, never cached
  // across identities. Errors do not grant the edit action.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[batchId,locationId,fetch]);
  const begin=()=>{
    if(!preview?.eligible)return;
    setLot(preview.current.batch_number);
    setProduction(preview.current.production_date??"");
    setExpiry(preview.current.expiry_date??"");
    setReason("");setPassword("");setConfirmed(false);setError("");setMessage("");
    request.current=null;setEditing(true);
  };
  const refresh=async()=>{
    const [p,h]=await Promise.all([
      fetch(path+"/metadata-correction?location_id="+locationId,{cache:"no-store"}),
      fetch(path+"/metadata-corrections/history?location_id="+locationId,{cache:"no-store"}),
    ]);
    const view=p as Preview, rows=h as {items:History[]};
    if(view?.batch_id!==batchId||view.location_id!==locationId||!Array.isArray(rows?.items))
      throw Error("BATCH_CORRECTION_SCOPE_MISMATCH");
    setPreview(view);setHistory(rows.items.slice(0,50));
  };
  const save=async()=>{
    if(!preview?.eligible||busy||!confirmed||reason.trim().length<8||
       !password||!lot.trim())return;
    setBusy(true);setError("");setMessage("");
    const next={
      request_id:crypto.randomUUID(),location_id:locationId,
      expected_revision:preview.metadata_revision,batch_number:lot.trim(),
      production_date:production||null,expiry_date:expiry||null,
      reason:reason.trim(),password,
    };
    // Same request ID, same payload on retry after a dropped successful reply.
    // Editing any input resets the retry context; never persist the password.
    const value=request.current??next;
    request.current=value;
    try{
      const result=await fetch(path+"/metadata-correction",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(value),
      }) as {batch_id?:number;metadata_revision?:number;current?:Values;
        disposition?:string;source_invoice?:string};
      // A successful HTTP status is not sufficient. Verify that the server
      // committed precisely the intended current-only metadata revision.
      if(result?.batch_id!==batchId||
         result.metadata_revision!==value.expected_revision+1||
         result.current?.batch_number!==value.batch_number||
         result.current.production_date!==value.production_date||
         result.current.expiry_date!==value.expiry_date||
         result.disposition!==preview.disposition||
         result.source_invoice!==preview.source_invoice)
        throw Error("BATCH_CORRECTION_RECEIPT_UNVERIFIED");
      request.current=null;setPassword("");setEditing(false);
      setMessage(copy.done); // authenticated server receipt is authoritative
      try {await refresh();await onChanged();}
      catch {setError(copy.fail);} // refresh failure never misreports a saved command
    }catch{
      setError(copy.fail);
      // Never show an optimistic success if the server update was not proven.
    }finally{setBusy(false);}
  };
  const changed=()=>{request.current=null;};
  if(!preview&&!history.length&&!error)return null;
  return <section dir={i18n.dir()} className="rounded-lg border p-3 space-y-2"
    data-testid="batch-773-metadata">
    {preview?.eligible&&!editing&&
      <button type="button" onClick={begin} className="rounded-lg border px-3 py-2 text-sm font-bold">
        {copy.edit}
      </button>}
    {preview&&!preview.eligible&&
      <p className="text-xs text-amber-800" role="status">{copy.blocked}: {preview.block_code}</p>}
    {editing&&preview?.eligible&&
      <div className="space-y-3" data-testid="batch-773-form">
        <h3 className="font-bold">{copy.heading}</h3>
        <p className="text-xs">{copy.invoice}: {preview.source_invoice}</p>
        <label className="block text-sm">{copy.lot}
          <input aria-label={copy.lot} className="w-full rounded border p-2" maxLength={100}
            value={lot} onChange={e=>{changed();setLot(e.target.value);}}/>
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-sm">{copy.production}
            <input aria-label={copy.production} type="date" value={production}
              onChange={e=>{changed();setProduction(e.target.value);}}
              className="w-full rounded border p-2"/>
          </label>
          <label className="text-sm">{copy.expiry}
            <input aria-label={copy.expiry} type="date" value={expiry}
              onChange={e=>{changed();setExpiry(e.target.value);}}
              className="w-full rounded border p-2"/>
          </label>
        </div>
        <label className="block text-sm">{copy.reason}
          <textarea aria-label={copy.reason} value={reason} maxLength={500}
            onChange={e=>{changed();setReason(e.target.value);}}
            className="w-full rounded border p-2" rows={2}/>
        </label>
        <label className="block text-sm">{copy.password}
          <input aria-label={copy.password} type="password" autoComplete="current-password"
            value={password} onChange={e=>{changed();setPassword(e.target.value);}}
            className="w-full rounded border p-2"/>
        </label>
        <label className="flex gap-2 text-sm">
          <input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
          <span>{copy.confirm}</span>
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={()=>void save()} disabled={busy||!confirmed||
            reason.trim().length<8||!password||!lot.trim()}
            className="rounded bg-blue-700 px-4 py-2 text-white disabled:opacity-50">{copy.save}</button>
          <button type="button" onClick={()=>{request.current=null;setPassword("");setEditing(false);}}
            className="rounded border px-4 py-2">{copy.cancel}</button>
        </div>
      </div>}
    {error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
    {message&&<p role="status" className="text-sm text-green-800">{message}</p>}
    {history.length>0&&<details className="text-sm">
      <summary className="cursor-pointer font-semibold">{copy.history} ({history.length})</summary>
      <ol className="mt-2 space-y-2">{history.map(h=><li key={h.revision} className="rounded border p-2">
        <p>{h.actor_username} — {h.verified_at}</p>
        <p>{copy.invoice}: {h.source_invoice}</p>
        <p>{copy.reason}: {h.reason}</p>
        <p>{copy.current}: {h.before.batch_number} / {h.before.expiry_date??"—"}</p>
        <p>{copy.after}: {h.after.batch_number} / {h.after.expiry_date??"—"}</p>
      </li>)}</ol>
    </details>}
  </section>;
}
