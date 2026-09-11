import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Eraser, FilePlus, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import { parseVariants, type CatalogVariant } from "./catalog/contracts";
import { buildInboundItems, emptyInboundBatch, inboundProductIds, inboundStorageKeys, parseInboundDrafts, parseInboundResponse, type InboundBatchDraft, type InboundDraftMap } from "./inbound/contracts";

interface Props { companyId: number; actorId: number; locationId: number; isAuditLocked: boolean; authenticatedFetch: (url: string, opts?: RequestInit) => Promise<unknown>; onSuccess: () => void | Promise<void> }
const freshRowId = () => crypto.randomUUID();

export function Tab2Inbound({ companyId, actorId, locationId, isAuditLocked, authenticatedFetch, onSuccess }: Props) {
  const keys = useMemo(() => inboundStorageKeys(companyId, actorId, locationId), [companyId, actorId, locationId]);
  const [drafts, setDrafts] = useState<InboundDraftMap>(() => parseInboundDrafts(localStorage.getItem(keys.drafts)));
  const [catalog, setCatalog] = useState<CatalogVariant[]>([]);
  const [searchInput, setSearchInput] = useState(""); const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null); const [history, setHistory] = useState<Array<string | null>>([]); const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false); const [submitting, setSubmitting] = useState(false); const [clearOpen, setClearOpen] = useState(false);
  const [referenceId, setReferenceId] = useState(() => localStorage.getItem(keys.reference) || ""); const [notes, setNotes] = useState(() => localStorage.getItem(keys.notes) || "");
  const request = useRef(0);

  useEffect(() => { localStorage.setItem(keys.drafts, JSON.stringify(drafts)); }, [drafts, keys]);
  useEffect(() => { localStorage.setItem(keys.reference, referenceId); }, [referenceId, keys]);
  useEffect(() => { localStorage.setItem(keys.notes, notes); }, [notes, keys]);
  useEffect(() => { const timer = window.setTimeout(() => { const clean = searchInput.trim(); setSearch(clean.length >= 2 ? clean : ""); setCursor(null); setHistory([]); }, 300); return () => clearTimeout(timer); }, [searchInput]);
  useEffect(() => {
    const id = ++request.current; const controller = new AbortController(); setLoading(true);
    const params = new URLSearchParams({ limit: "50", lifecycle_status: "ACTIVE" }); if (cursor) params.set("cursor", cursor); if (search) params.set("search", search);
    authenticatedFetch(`/catalog/variants?${params}`, { signal: controller.signal }).then(parseVariants).then((page) => { if (id === request.current) { setCatalog(page.items); setNextCursor(page.next_cursor); } }).catch((error) => { if (id === request.current && !(error instanceof Error && error.name === "AbortError")) toast.error(apiErrorMessage(error, "فشل جلب كتالوج المنتجات.")); }).finally(() => { if (id === request.current) setLoading(false); });
    return () => { request.current += 1; controller.abort(); };
  }, [authenticatedFetch, cursor, search]);

  const update = (variant: CatalogVariant, rowId: string, patch: Partial<Omit<InboundBatchDraft,"row_id">>) => setDrafts((current) => {
    const key = String(variant.id); const rows = current[key]?.length ? [...current[key]] : [emptyInboundBatch(rowId)]; const index = rows.findIndex((row) => row.row_id === rowId);
    if (index < 0) rows.push({ ...emptyInboundBatch(rowId), ...patch }); else rows[index] = { ...rows[index], ...patch };
    return { ...current, [key]: rows };
  });
  const clear = () => { setDrafts({}); setReferenceId(""); setNotes(""); localStorage.removeItem(keys.drafts); localStorage.removeItem(keys.reference); localStorage.removeItem(keys.notes); localStorage.removeItem(keys.requestId); localStorage.removeItem(keys.fingerprint); setClearOpen(false); };
  const submit = async () => {
    if (isAuditLocked) return toast.error("المستودع مقفل بجرد شامل ولا يمكن توثيق التوريد حالياً.");
    const ids = inboundProductIds(drafts); if (!ids.length) return toast.error("أضف كمية لصنف واحد على الأقل.");
    if (!referenceId.trim()) return toast.error("رقم الفاتورة أو المرجع إجباري.");
    setSubmitting(true);
    try {
      const variants = parseVariants(await authenticatedFetch("/catalog/variants/resolve", { method: "POST", body: JSON.stringify({ ids }) })).items;
      if (variants.length !== ids.length) throw new Error("يوجد صنف في المسودة لم يعد فعالاً أو لا يتبع شركتك.");
      const items = buildInboundItems(drafts, new Map(variants.map((item) => [String(item.id), item])));
      const businessPayload = { location_id: locationId, reference_id: referenceId.trim(), notes: notes.trim() || null, items };
      const fingerprint = JSON.stringify(businessPayload); let requestId = localStorage.getItem(keys.requestId);
      if (!requestId || localStorage.getItem(keys.fingerprint) !== fingerprint) { requestId = crypto.randomUUID(); localStorage.setItem(keys.requestId, requestId); localStorage.setItem(keys.fingerprint, fingerprint); }
      const response = await authenticatedFetch("/warehouse/inbound", { method: "POST", body: JSON.stringify({ request_id: requestId, ...businessPayload }) });
      toast.success(parseInboundResponse(response).message); clear(); await onSuccess();
    } catch (error) { toast.error(apiErrorMessage(error, "فشل توثيق التوريد.")); } finally { setSubmitting(false); }
  };

  return <div className="inventory-view inventory-inbound flex flex-col h-full min-h-0 pt-1"><div className="inventory-surface relative bg-white rounded-2xl border flex flex-col flex-1 min-h-0">
    <div className="absolute -top-3.5 right-6 bg-emerald-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex gap-2"><FilePlus className="w-4 h-4"/>توريد بضاعة</div>
    <div className="flex-1 min-h-0 overflow-auto mt-5"><table className="w-full text-sm min-w-[950px]"><thead className="sticky top-0 bg-slate-50 border-b"><tr><th className="p-3 text-right"><div className="flex gap-2 items-center">المنتج<div className="relative"><Search className="absolute right-2 top-2 w-4 h-4 text-slate-400"/><input value={searchInput} onChange={(e) => setSearchInput(e.target.value)} className="rounded-lg border py-1.5 pr-8 px-2" placeholder="بحث..."/></div></div></th><th className="p-3 text-right">الدفعة والتواريخ</th><th className="p-3 text-right">الكمية بوحدة الأساس</th><th className="p-3"><button type="button" onClick={() => setClearOpen(true)} className="text-red-600"><Eraser className="w-4 h-4"/></button></th></tr></thead><tbody className="divide-y">
      {!catalog.length && <tr><td colSpan={4} className="py-12 text-center text-slate-400">{loading ? "جارٍ التحميل..." : "لا توجد أصناف فعالة"}</td></tr>}
      {catalog.flatMap((variant) => (drafts[String(variant.id)]?.length ? drafts[String(variant.id)] : [emptyInboundBatch(`base-${variant.id}`)]).map((row,index) => <tr key={`${variant.id}-${row.row_id}`}><td className="p-3 font-bold">{variant.name}<div className="text-xs text-slate-400">{variant.sku}</div></td><td className="p-3"><div className="grid grid-cols-3 gap-2"><input value={row.batch_number} onChange={(e) => update(variant,row.row_id,{batch_number:e.target.value})} placeholder="رقم الدفعة" className="rounded-lg border p-2"/><input type="date" value={row.production_date} onChange={(e) => update(variant,row.row_id,{production_date:e.target.value})} className="rounded-lg border p-2"/><input type="date" value={row.expiry_date} onChange={(e) => update(variant,row.row_id,{expiry_date:e.target.value})} className="rounded-lg border p-2"/></div></td><td className="p-3"><div className="flex items-center gap-2"><input inputMode="decimal" value={row.quantity} onChange={(e) => update(variant,row.row_id,{quantity:e.target.value.replace(/[^0-9.]/g,"")})} className="w-28 rounded-lg border p-2 text-center"/><span className="font-bold">{variant.base_uom.name}</span><span className="text-xs text-slate-400">خطوة {variant.quantity_step}</span></div></td><td className="p-3"><div className="flex gap-2"><button type="button" onClick={() => setDrafts((current) => ({...current,[String(variant.id)]:[...(current[String(variant.id)] ?? [row]),emptyInboundBatch(freshRowId())]}))}><Plus className="w-4 h-4"/></button>{index>0 && <button type="button" onClick={() => setDrafts((current) => ({...current,[String(variant.id)]:(current[String(variant.id)]??[]).filter((value)=>value.row_id!==row.row_id)}))}><Trash2 className="w-4 h-4 text-red-500"/></button>}</div></td></tr>))}
    </tbody></table></div>
    {(history.length || nextCursor) && <div className="flex justify-end gap-2 p-2 border-t"><button disabled={!history.length} onClick={() => { const prev=history.at(-1)??null; setHistory((v)=>v.slice(0,-1)); setCursor(prev); }}><ChevronRight/></button><button disabled={!nextCursor} onClick={() => { if(nextCursor){setHistory((v)=>[...v,cursor]);setCursor(nextCursor);} }}><ChevronLeft/></button></div>}
    <div className="p-3 bg-slate-50 grid md:grid-cols-[1fr_1fr_auto] gap-3"><input value={referenceId} onChange={(e)=>setReferenceId(e.target.value)} placeholder="رقم الفاتورة / المرجع" className="rounded-xl border p-2"/><input value={notes} onChange={(e)=>setNotes(e.target.value)} placeholder="ملاحظات" className="rounded-xl border p-2"/><button type="button" onClick={() => void submit()} disabled={submitting||isAuditLocked} className="rounded-xl bg-emerald-600 text-white px-6 font-black disabled:opacity-50">{submitting?"جارٍ التوثيق...":"توثيق الاستلام"}</button></div>
    <Modal isOpen={clearOpen} onClose={()=>setClearOpen(false)} title="تأكيد تصفير المسودة" footer={<><button onClick={()=>setClearOpen(false)}>إلغاء</button><button onClick={clear} className="rounded-xl bg-red-600 text-white px-5 py-2">تصفير</button></>}><p>سيتم مسح مسودة التوريد المحلية الحالية فقط.</p></Modal>
  </div></div>;
}
