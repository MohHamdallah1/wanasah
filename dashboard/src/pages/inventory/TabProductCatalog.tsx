import { useCallback, useEffect, useRef, useState } from "react";
import { Barcode, ChevronLeft, ChevronRight, Layers3, PackagePlus, Plus, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  buildBarcodePayload, buildConversionPayload, buildProductPayload, buildVariantPayload, parseBarcodes, parseConversions, parseMutationMessage, parseProducts, parseUoms, parseVariants,
  type CatalogProduct, type CatalogVariant, type ProductBarcode, type ProductDraft, type UomConversion, type UomRef, type VariantDraft,
} from "./catalog/contracts";
import { CatalogLifecyclePanel } from "./catalog/CatalogLifecyclePanel";

interface Props {
  locations: Array<{ id: number; code: string; name: string }>;
  onCatalogChanged: () => void | Promise<void>;
}
const EMPTY_PRODUCT: ProductDraft = { code: "", name: "", description: "", brand: "", category: "" };
const EMPTY_VARIANT: VariantDraft = {
  product_id: "", sku: "", gtin: "", name: "", base_uom_id: "", quantity_scale: "0", quantity_step: "1",
  lot_control_mode: "REQUIRED", expiry_control_mode: "REQUIRED",
};

export function TabProductCatalog({ locations, onCatalogChanged }: Props) {
  const authenticatedFetch = useAuthFetch();
  const canManage = useInventoryAccess().can("catalog.manage");
  const [items, setItems] = useState<CatalogVariant[]>([]);
  const [products, setProducts] = useState<CatalogProduct[]>([]);
  const [uoms, setUoms] = useState<UomRef[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const sequence = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const identitySequence = useRef(0);
  const identityAbortRef = useRef<AbortController | null>(null);
  const [productOpen, setProductOpen] = useState(false);
  const [variantOpen, setVariantOpen] = useState(false);
  const [productDraft, setProductDraft] = useState<ProductDraft>(EMPTY_PRODUCT);
  const [variantDraft, setVariantDraft] = useState<VariantDraft>(EMPTY_VARIANT);
  const [saving, setSaving] = useState(false);
  const [managedVariant, setManagedVariant] = useState<CatalogVariant | null>(null);
  const [conversions, setConversions] = useState<UomConversion[]>([]);
  const [barcodes, setBarcodes] = useState<ProductBarcode[]>([]);
  const [conversionDraft, setConversionDraft] = useState({ from_uom_id:"", to_uom_id:"", numerator:"1", denominator:"1", quantity_scale:"0" });
  const [barcodeDraft, setBarcodeDraft] = useState<{uom_id:string;barcode:string;barcode_type:ProductBarcode["barcode_type"];is_primary:boolean}>({uom_id:"",barcode:"",barcode_type:"INTERNAL",is_primary:false});

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : ""); setCursor(null); setHistory([]); setNextCursor(null);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const load = useCallback(async () => {
    const current = ++sequence.current;
    abortRef.current?.abort();
    const controller = new AbortController(); abortRef.current = controller; setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (cursor) params.set("cursor", cursor); if (search) params.set("search", search);
      const [variantRaw, productRaw, uomRaw] = await Promise.all([
        authenticatedFetch(`/catalog/variants?${params}`, { signal: controller.signal }),
        authenticatedFetch("/catalog/products?limit=200", { signal: controller.signal }),
        authenticatedFetch("/catalog/uoms", { signal: controller.signal }),
      ]);
      if (current !== sequence.current) return;
      const variantPage = parseVariants(variantRaw);
      setItems(variantPage.items); setNextCursor(variantPage.next_cursor);
      setProducts(parseProducts(productRaw).items); setUoms(parseUoms(uomRaw));
    } catch (error) {
      if (current !== sequence.current || (error instanceof Error && error.name === "AbortError")) return;
      setItems([]); setNextCursor(null); toast.error(apiErrorMessage(error, "تعذر جلب كتالوج المنتجات."));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (current === sequence.current) setLoading(false);
    }
  }, [authenticatedFetch, cursor, search]);

  useEffect(() => { void load(); }, [load, refreshKey]);
  useEffect(() => () => { sequence.current += 1; abortRef.current?.abort(); }, []);

  const loadIdentity = useCallback(async (variant: CatalogVariant) => {
    const current = ++identitySequence.current;
    identityAbortRef.current?.abort();
    const controller = new AbortController();
    identityAbortRef.current = controller;

    try {
      const [conversionRaw, barcodeRaw] = await Promise.all([
        authenticatedFetch(
          `/catalog/variants/${variant.id}/conversions`,
          { signal: controller.signal },
        ),
        authenticatedFetch(
          `/catalog/variants/${variant.id}/barcodes`,
          { signal: controller.signal },
        ),
      ]);

      if (
        current !== identitySequence.current ||
        controller.signal.aborted
      ) {
        return;
      }

      const nextConversions = parseConversions(conversionRaw);
      const nextBarcodes = parseBarcodes(barcodeRaw);

      if (
        current !== identitySequence.current ||
        controller.signal.aborted
      ) {
        return;
      }

      setConversions(nextConversions);
      setBarcodes(nextBarcodes);
    } catch (error) {
      if (
        current !== identitySequence.current ||
        controller.signal.aborted ||
        (error instanceof Error && error.name === "AbortError")
      ) {
        return;
      }
      toast.error(apiErrorMessage(error, "تعذر تحميل تحويلات UOM والباركود."));
    } finally {
      if (identityAbortRef.current === controller) {
        identityAbortRef.current = null;
      }
    }
  }, [authenticatedFetch]);

  useEffect(() => {
    if (!managedVariant) {
      identitySequence.current += 1;
      identityAbortRef.current?.abort();
      identityAbortRef.current = null;
      setConversions([]);
      setBarcodes([]);
      return;
    }

    setConversions([]);
    setBarcodes([]);
    void loadIdentity(managedVariant);

    return () => {
      identitySequence.current += 1;
      identityAbortRef.current?.abort();
      identityAbortRef.current = null;
    };
  }, [managedVariant, loadIdentity]);

  const saveProduct = async () => {
    setSaving(true);
    try {
      const message = parseMutationMessage(await authenticatedFetch("/catalog/products", { method: "POST", body: JSON.stringify(buildProductPayload(productDraft)) }));
      toast.success(message); setProductDraft(EMPTY_PRODUCT); setProductOpen(false); setRefreshKey((v) => v + 1); await onCatalogChanged();
    } catch (error) { toast.error(apiErrorMessage(error, "تعذر إنشاء عائلة المنتج.")); } finally { setSaving(false); }
  };
  const saveVariant = async () => {
    setSaving(true);
    try {
      const message = parseMutationMessage(await authenticatedFetch("/catalog/variants", { method: "POST", body: JSON.stringify(buildVariantPayload(variantDraft)) }));
      toast.success(message); setVariantDraft(EMPTY_VARIANT); setVariantOpen(false); setCursor(null); setHistory([]); setRefreshKey((v) => v + 1); await onCatalogChanged();
    } catch (error) { toast.error(apiErrorMessage(error, "تعذر إنشاء SKU.")); } finally { setSaving(false); }
  };
  const productField = (key: keyof ProductDraft, value: string) => setProductDraft((v) => ({ ...v, [key]: value }));
  const variantField = (key: keyof VariantDraft, value: string) => setVariantDraft((v) => ({ ...v, [key]: value }));
  const addConversion = async () => {
    if (!managedVariant) return;
    setSaving(true);
    try {
      toast.success(parseMutationMessage(await authenticatedFetch(`/catalog/variants/${managedVariant.id}/conversions`, { method:"POST", body:JSON.stringify(buildConversionPayload(conversionDraft)) })));
      await loadIdentity(managedVariant);
    } catch (error) { toast.error(apiErrorMessage(error, "تعذر إضافة تحويل UOM.")); } finally { setSaving(false); }
  };
  const addBarcode = async () => {
    if (!managedVariant) return;
    setSaving(true);
    try {
      toast.success(parseMutationMessage(await authenticatedFetch(`/catalog/variants/${managedVariant.id}/barcodes`, { method:"POST", body:JSON.stringify(buildBarcodePayload(barcodeDraft)) })));
      setBarcodeDraft({uom_id:"",barcode:"",barcode_type:"INTERNAL",is_primary:false});
      await loadIdentity(managedVariant);
    } catch (error) { toast.error(apiErrorMessage(error, "تعذر إضافة الباركود.")); } finally { setSaving(false); }
  };

  return <div className="inventory-view inventory-data-panel inventory-surface flex flex-col h-full min-h-0 rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
    <div className="inventory-panel-header p-4 border-b border-slate-100 flex flex-col sm:flex-row gap-3 items-center justify-between bg-slate-50">
      <div><h2 className="font-black text-slate-800">كتالوج منتجات الشركة</h2><p className="text-xs text-slate-500 mt-1">عائلات المنتجات وSKU بوحدة أساس دقيقة، دون تسعير أو ربط مستودع.</p></div>
      <div className="flex items-center gap-2 w-full sm:w-auto">
        <div className="relative flex-1 sm:w-64"><Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"/><input type="search" value={searchInput} maxLength={100} onChange={(e) => setSearchInput(e.target.value)} placeholder="الاسم أو SKU..." className="w-full rounded-xl border border-slate-200 bg-white pr-9 pl-3 py-2 text-xs font-bold outline-none"/></div>
        <button type="button" onClick={() => setRefreshKey((v) => v + 1)} disabled={loading} className="p-2 rounded-xl border bg-white disabled:opacity-40"><RefreshCcw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}/></button>
        {canManage && <><button type="button" onClick={() => setProductOpen(true)} className="rounded-xl border border-blue-200 bg-blue-50 text-blue-700 px-3 py-2 text-xs font-black"><Plus className="inline w-4 h-4 ml-1"/>عائلة</button><button type="button" onClick={() => setVariantOpen(true)} disabled={!products.length || !uoms.length} className="rounded-xl bg-blue-600 text-white px-3 py-2 text-xs font-black disabled:opacity-40"><PackagePlus className="inline w-4 h-4 ml-1"/>SKU</button></>}
      </div>
    </div>
    <div className="flex-1 min-h-0 overflow-auto"><table className="w-full text-sm"><thead className="sticky top-0 bg-slate-50 border-b"><tr><th className="px-5 py-3 text-right text-xs text-slate-500">SKU</th><th className="px-5 py-3 text-right text-xs text-slate-500">وحدة الأساس</th><th className="px-5 py-3 text-right text-xs text-slate-500">الدقة والخطوة</th><th className="px-5 py-3 text-right text-xs text-slate-500">الحالة</th><th className="px-5 py-3"/></tr></thead><tbody className="divide-y">
      {loading && <tr><td colSpan={5} className="py-12 text-center text-slate-400 font-bold">جارٍ التحميل...</td></tr>}
      {!loading && !items.length && <tr><td colSpan={5} className="py-12 text-center text-slate-400">لا توجد أصناف مطابقة</td></tr>}
      {!loading && items.map((item) => <tr key={item.id} className="hover:bg-slate-50"><td className="px-5 py-3"><span className="font-bold text-slate-800 inline-flex gap-2"><Layers3 className="w-4 h-4 text-blue-500"/>{item.name}</span><div className="font-mono text-[11px] text-slate-400 mt-1">{item.sku}</div></td><td className="px-5 py-3 font-bold">{item.base_uom.name} <span className="text-slate-400">({item.base_uom.code})</span></td><td className="px-5 py-3">{item.quantity_scale} / {item.quantity_step}</td><td className="px-5 py-3"><div className="flex flex-wrap gap-1"><span className="rounded-lg bg-slate-100 px-2 py-1 text-xs font-black">{item.lifecycle_status}</span>{item.operational_hold !== "NONE" && <span className="rounded-lg bg-red-50 px-2 py-1 text-xs font-black text-red-700">{item.operational_hold}</span>}</div></td><td className="px-5 py-3"><button type="button" onClick={() => setManagedVariant(item)} className="rounded-lg border px-2 py-1 text-xs font-bold"><Barcode className="inline w-4 h-4 ml-1"/>إدارة الصنف</button></td></tr>)}
    </tbody></table></div>
    {(history.length > 0 || nextCursor) && <div className="flex justify-end gap-2 px-5 py-3 border-t bg-slate-50"><button type="button" disabled={!history.length || loading} onClick={() => { const previous = history.at(-1) ?? null; setHistory((v) => v.slice(0,-1)); setCursor(previous); }} className="p-1.5 rounded-lg border disabled:opacity-30"><ChevronRight className="w-4 h-4"/></button><button type="button" disabled={!nextCursor || loading} onClick={() => { if (nextCursor) { setHistory((v) => [...v, cursor]); setCursor(nextCursor); } }} className="p-1.5 rounded-lg border disabled:opacity-30"><ChevronLeft className="w-4 h-4"/></button></div>}

    <Modal isOpen={productOpen} onClose={() => !saving && setProductOpen(false)} title="إنشاء عائلة منتج" maxWidth="max-w-xl" footer={<><button type="button" disabled={saving} onClick={() => setProductOpen(false)} className="px-4 py-2 font-bold">إلغاء</button><button type="button" disabled={saving} onClick={() => void saveProduct()} className="rounded-xl bg-blue-600 px-5 py-2 text-white font-black">حفظ</button></>}>
      <div className="grid sm:grid-cols-2 gap-3">{([['code','الكود'],['name','الاسم'],['brand','العلامة'],['category','التصنيف']] as const).map(([key,label]) => <label key={key} className="text-xs font-bold text-slate-600">{label}<input value={productDraft[key]} onChange={(e) => productField(key,e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"/></label>)}<label className="sm:col-span-2 text-xs font-bold text-slate-600">الوصف<textarea value={productDraft.description} onChange={(e) => productField('description',e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"/></label></div>
    </Modal>
    <Modal isOpen={variantOpen} onClose={() => !saving && setVariantOpen(false)} title="إنشاء SKU مسودة" maxWidth="max-w-2xl" footer={<><button type="button" disabled={saving} onClick={() => setVariantOpen(false)} className="px-4 py-2 font-bold">إلغاء</button><button type="button" disabled={saving} onClick={() => void saveVariant()} className="rounded-xl bg-blue-600 px-5 py-2 text-white font-black">حفظ المسودة</button></>}>
      <div className="grid sm:grid-cols-2 gap-3"><label className="text-xs font-bold">عائلة المنتج<select value={variantDraft.product_id} onChange={(e) => variantField('product_id',e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"><option value="">اختر...</option>{products.map((p) => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</select></label><label className="text-xs font-bold">وحدة الأساس<select value={variantDraft.base_uom_id} onChange={(e) => variantField('base_uom_id',e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"><option value="">اختر...</option>{uoms.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.code})</option>)}</select></label>{([['name','اسم SKU'],['sku','SKU'],['gtin','GTIN اختياري'],['quantity_scale','دقة الكمية 0–6'],['quantity_step','خطوة الكمية']] as const).map(([key,label]) => <label key={key} className="text-xs font-bold">{label}<input value={variantDraft[key]} onChange={(e) => variantField(key,e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"/></label>)}<label className="text-xs font-bold">تتبع الدفعة<select value={variantDraft.lot_control_mode} onChange={(e) => variantField('lot_control_mode',e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"><option value="REQUIRED">إلزامي</option><option value="OPTIONAL">اختياري</option><option value="NONE">بدون</option></select></label><label className="text-xs font-bold">تتبع الصلاحية<select value={variantDraft.expiry_control_mode} onChange={(e) => variantField('expiry_control_mode',e.target.value)} className="mt-1 w-full rounded-xl border p-2.5"><option value="REQUIRED">إلزامي</option><option value="OPTIONAL">اختياري</option><option value="NONE">بدون</option></select></label></div><p className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-xs font-bold text-blue-700">يحفظ الصنف كمسودة بلا سعر أو مخزون. النشر ودورة الحياة في Stage 3.</p>
    </Modal>
    <Modal isOpen={managedVariant !== null} onClose={() => !saving && setManagedVariant(null)} title={`إدارة الصنف — ${managedVariant?.name ?? ""}`} maxWidth="max-w-5xl">
      {managedVariant && <div className="space-y-5">
      <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-xl border p-3"><h3 className="font-black">تحويلات UOM</h3><div className="my-3 space-y-1 text-xs">{conversions.map((item) => <div key={item.id} className="rounded-lg bg-slate-50 p-2">{item.from_uom.code} × {item.numerator}/{item.denominator} → {item.to_uom.code}</div>)}{!conversions.length && <p className="text-slate-400">لا توجد تحويلات.</p>}</div>{managedVariant?.lifecycle_status === "DRAFT" && <div className="grid grid-cols-2 gap-2"><select value={conversionDraft.from_uom_id} onChange={(e)=>setConversionDraft((v)=>({...v,from_uom_id:e.target.value}))} className="rounded-lg border p-2"><option value="">من وحدة</option>{uoms.map((u)=><option key={u.id} value={u.id}>{u.code}</option>)}</select><select value={conversionDraft.to_uom_id} onChange={(e)=>setConversionDraft((v)=>({...v,to_uom_id:e.target.value}))} className="rounded-lg border p-2"><option value="">إلى وحدة</option>{uoms.map((u)=><option key={u.id} value={u.id}>{u.code}</option>)}</select><input value={conversionDraft.numerator} onChange={(e)=>setConversionDraft((v)=>({...v,numerator:e.target.value}))} placeholder="البسط" className="rounded-lg border p-2"/><input value={conversionDraft.denominator} onChange={(e)=>setConversionDraft((v)=>({...v,denominator:e.target.value}))} placeholder="المقام" className="rounded-lg border p-2"/><button type="button" disabled={saving} onClick={()=>void addConversion()} className="col-span-2 rounded-lg bg-blue-600 p-2 text-white font-bold">إضافة التحويل</button></div>}</section>
        <section className="rounded-xl border p-3"><h3 className="font-black">الباركود</h3><div className="my-3 space-y-1 text-xs">{barcodes.map((item) => <div key={item.id} className="rounded-lg bg-slate-50 p-2 font-mono">{item.barcode} · {item.uom.code}{item.is_primary ? " · أساسي" : ""}{!item.is_active ? " · منتهي" : ""}</div>)}{!barcodes.length && <p className="text-slate-400">لا توجد باركودات.</p>}</div><div className="grid grid-cols-2 gap-2"><select value={barcodeDraft.uom_id} onChange={(e)=>setBarcodeDraft((v)=>({...v,uom_id:e.target.value}))} className="rounded-lg border p-2"><option value="">الوحدة</option>{uoms.map((u)=><option key={u.id} value={u.id}>{u.code}</option>)}</select><select value={barcodeDraft.barcode_type} onChange={(e)=>setBarcodeDraft((v)=>({...v,barcode_type:e.target.value as ProductBarcode["barcode_type"]}))} className="rounded-lg border p-2"><option value="INTERNAL">INTERNAL</option><option value="EAN8">EAN8</option><option value="EAN13">EAN13</option><option value="UPC_A">UPC-A</option><option value="GTIN14">GTIN-14</option><option value="GS1_128">GS1-128</option></select><input value={barcodeDraft.barcode} onChange={(e)=>setBarcodeDraft((v)=>({...v,barcode:e.target.value}))} placeholder="قيمة الباركود" className="col-span-2 rounded-lg border p-2"/><label className="col-span-2 text-xs"><input type="checkbox" checked={barcodeDraft.is_primary} onChange={(e)=>setBarcodeDraft((v)=>({...v,is_primary:e.target.checked}))}/> باركود أساسي لهذه الوحدة</label><button type="button" disabled={saving} onClick={()=>void addBarcode()} className="col-span-2 rounded-lg bg-slate-800 p-2 text-white font-bold">إضافة الباركود</button></div></section>
      </div>
      <CatalogLifecyclePanel
        variant={managedVariant}
        locations={locations}
        onVariantChanged={async (updated) => {
          setManagedVariant(updated);
          setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
          await onCatalogChanged();
        }}
        onVariantDeleted={async (variantId) => {
          setManagedVariant(null);
          setItems((current) => current.filter((item) => item.id !== variantId));
          setRefreshKey((value) => value + 1);
          await onCatalogChanged();
        }}
      />
      </div>}
    </Modal>
  </div>;
}
