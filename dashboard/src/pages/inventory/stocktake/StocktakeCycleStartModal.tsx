import { ChevronLeft, Layers3, Search, X } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import type { CycleCountStartController } from "./hooks/useCycleCountStart";

interface StocktakeCycleStartModalProps {
  open: boolean;
  controller: CycleCountStartController;
  onClose: () => void;
  onStart: () => void | Promise<void>;
}

export function StocktakeCycleStartModal({ open, controller, onClose, onStart }: StocktakeCycleStartModalProps) {
  const {
    productSearchInput, setProductSearchInput, products, productsNextCursor,
    productsLoading, productsLoadingMore, selectedProduct, chooseProduct,
    clearProduct, loadMoreProducts, batchSearchInput, setBatchSearchInput,
    batches, batchesNextCursor, batchesLoading, batchesLoadingMore,
    selectedBatch, setSelectedBatch, loadMoreBatches, notes, setNotes, starting,
  } = controller;

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title="بدء جرد دوري"
      maxWidth="max-w-4xl"
      footer={
        <div className="flex gap-3 w-full">
          <button type="button" onClick={onClose} disabled={starting} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50 disabled:opacity-50">إلغاء</button>
          <button type="button" onClick={() => void onStart()} disabled={starting || !selectedProduct} className="flex-[1.7] px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white font-black rounded-xl shadow-md">
            {starting ? "جاري بدء الجرد..." : "بدء العد الأعمى"}
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm font-bold text-blue-800">
          الجرد الدوري يقفل الصنف المحدد فقط، أو دفعة محددة منه. بقية المستودع يبقى عاملاً بصورة طبيعية.
        </div>

        {!selectedProduct ? (
          <div className="space-y-3">
            <div className="relative">
              <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input value={productSearchInput} onChange={(event) => setProductSearchInput(event.target.value)} maxLength={100} placeholder="ابحث باسم الصنف أو SKU..." className="w-full rounded-xl border border-slate-200 bg-white pr-10 pl-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-blue-500/20" />
            </div>
            <div className="max-h-72 overflow-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
              {products.map((product) => (
                <button type="button" key={product.id} onClick={() => chooseProduct(product)} className="w-full px-4 py-3 text-right hover:bg-slate-50 flex items-center justify-between gap-3">
                  <div>
                    <div className="font-black text-slate-800 text-sm">{product.name}</div>
                    <div className="text-[11px] text-slate-500 mt-1">SKU: {product.sku || "—"} · {product.packs_per_carton} حبة/كرتونة</div>
                  </div>
                  <ChevronLeft className="w-4 h-4 text-slate-400" />
                </button>
              ))}
              {productsLoading && products.length === 0 && <div className="p-8 text-center text-sm text-slate-400">جاري جلب الأصناف...</div>}
              {!productsLoading && products.length === 0 && <div className="p-8 text-center text-sm text-slate-400">لا توجد أصناف مطابقة.</div>}
            </div>
            {productsNextCursor && (
              <button type="button" onClick={loadMoreProducts} disabled={productsLoadingMore} className="w-full py-2.5 rounded-xl bg-blue-50 text-blue-700 text-xs font-black disabled:opacity-50">
                {productsLoadingMore ? "جاري تحميل المزيد..." : "تحميل المزيد"}
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-xs text-slate-500 font-bold">الصنف المختار</div>
                <div className="font-black text-slate-800 mt-1">{selectedProduct.name}</div>
                <div className="text-[11px] text-slate-500 mt-1">SKU: {selectedProduct.sku || "—"}</div>
              </div>
              <button type="button" onClick={clearProduct} disabled={starting} className="p-2 rounded-lg bg-white border border-slate-200 text-slate-500 hover:text-red-600 disabled:opacity-50" title="تغيير الصنف"><X className="w-4 h-4" /></button>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2"><Layers3 className="w-4 h-4 text-blue-600" /><span className="text-sm font-black text-slate-800">نطاق الدفعات</span></div>
              <button type="button" onClick={() => setSelectedBatch(null)} className={`w-full rounded-xl border p-3 text-right mb-3 transition-colors ${selectedBatch === null ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                <div className="font-black text-sm text-slate-800">كل دفعات الصنف</div>
                <div className="text-[11px] text-slate-500 mt-1">يقفل الصنف كاملاً في هذا الموقع أثناء الجرد.</div>
              </button>
              <div className="relative mb-2"><Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" /><input value={batchSearchInput} onChange={(event) => setBatchSearchInput(event.target.value)} maxLength={100} placeholder="بحث برقم الدفعة..." className="w-full rounded-xl border border-slate-200 bg-white pr-10 pl-3 py-2.5 text-sm outline-none" /></div>
              <div className="max-h-52 overflow-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
                {batches.map((batch) => (
                  <button type="button" key={batch.id} onClick={() => setSelectedBatch(batch)} className={`w-full px-4 py-3 text-right transition-colors ${selectedBatch?.id === batch.id ? "bg-blue-50" : "bg-white hover:bg-slate-50"}`}>
                    <div className="flex items-center justify-between gap-3"><span className="font-black text-sm text-slate-800">{batch.batch_number}</span>{!batch.is_active && <span className="text-[10px] font-bold bg-slate-200 text-slate-600 px-2 py-0.5 rounded-md">غير فعالة</span>}</div>
                    <div className="text-[11px] text-slate-500 mt-1">الصلاحية: {batch.expiry_date}{batch.production_date ? ` · الإنتاج: ${batch.production_date}` : ""}</div>
                  </button>
                ))}
                {batchesLoading && batches.length === 0 && <div className="p-6 text-center text-xs text-slate-400">جاري جلب الدفعات...</div>}
                {!batchesLoading && batches.length === 0 && <div className="p-6 text-center text-xs text-slate-400">لا توجد دفعات مطابقة. يمكنك جرد الصنف بكل دفعاته.</div>}
              </div>
              {batchesNextCursor && <button type="button" onClick={loadMoreBatches} disabled={batchesLoadingMore} className="mt-2 w-full py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-black disabled:opacity-50">{batchesLoadingMore ? "جاري تحميل المزيد..." : "تحميل المزيد من الدفعات"}</button>}
            </div>
          </div>
        )}

        <div>
          <label className="text-xs font-black text-slate-700">ملاحظات الجرد (اختياري)</label>
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={4000} className="mt-1 w-full min-h-20 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none" />
        </div>
      </div>
    </Modal>
  );
}
