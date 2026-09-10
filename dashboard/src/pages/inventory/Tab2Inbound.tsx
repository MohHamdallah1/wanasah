import { parseCatalogPage, parseCatalogItems } from "./catalogParsers";
import { apiErrorMessage } from "@/lib/apiErrors";
import { useState, useEffect, useRef } from "react";
import { FilePlus, Search, Eraser, Plus, Trash2, ChevronRight, ChevronLeft } from "lucide-react";
import { toast } from "sonner";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { SimpleProductVariant } from "./catalog/contracts";
import { Modal } from "@/components/ui/modal";
import {
  buildInboundItems,
  emptyInboundBatch,
  inboundProductIds,
  inboundStorageKeys,
  parseInboundDraftProducts,
  parseInboundDrafts,
  parseInboundResponse,
} from "./inbound/contracts";
import type { DraftProductMap, InboundBatchDraft, InboundDraftMap } from "./inbound/contracts";

interface Props {
  companyId: number;
  actorId: number;
  locationId: number;
  isAuditLocked: boolean;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<unknown>;
  onSuccess: () => void | Promise<void>;
}

const freshRowId = () => crypto.randomUUID();

export function Tab2Inbound({ companyId, actorId, locationId, isAuditLocked, authenticatedFetch, onSuccess }: Props) {
  const storageKeys = inboundStorageKeys(companyId, actorId, locationId);
  const [drafts, setDrafts] = useState<InboundDraftMap>(() => parseInboundDrafts(localStorage.getItem(storageKeys.drafts)));
  const [draftProducts, setDraftProducts] = useState<DraftProductMap>(() => parseInboundDraftProducts(localStorage.getItem(storageKeys.products)));
  const [catalogItems, setCatalogItems] = useState<SimpleProductVariant[]>([]);
  const [catalogSearchInput, setCatalogSearchInput] = useState("");
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogCursor, setCatalogCursor] = useState<string | null>(null);
  const [catalogHistory, setCatalogHistory] = useState<Array<string | null>>([]);
  const [catalogNextCursor, setCatalogNextCursor] = useState<string | null>(null);
  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const catalogRequestSeq = useRef(0);
  const catalogAbortRef = useRef<AbortController | null>(null);
  const draftResolveAbortRef = useRef<AbortController | null>(null);

  const [referenceId, setReferenceId] = useState(() => localStorage.getItem(storageKeys.reference) || "");
  const [notes, setNotes] = useState(() => localStorage.getItem(storageKeys.notes) || "");
  const [submitting, setSubmitting] = useState(false);
  const [isConfirmClearOpen, setIsConfirmClearOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem(storageKeys.drafts, JSON.stringify(drafts));
  }, [drafts, storageKeys.drafts]);

  useEffect(() => {
    localStorage.setItem(storageKeys.products, JSON.stringify(draftProducts));
  }, [draftProducts, storageKeys.products]);

  useEffect(() => { localStorage.setItem(storageKeys.reference, referenceId); }, [referenceId, storageKeys.reference]);
  useEffect(() => { localStorage.setItem(storageKeys.notes, notes); }, [notes, storageKeys.notes]);

  useEffect(() => {
    const handler = window.setTimeout(() => {
      const clean = catalogSearchInput.trim();
      setCatalogSearch(clean.length >= 2 ? clean : "");
      setCatalogCursor(null);
      setCatalogHistory([]);
    }, 300);
    return () => window.clearTimeout(handler);
  }, [catalogSearchInput]);

  useEffect(() => {
    const requestId = ++catalogRequestSeq.current;
    catalogAbortRef.current?.abort();
    const requestController = new AbortController();
    catalogAbortRef.current = requestController;

    const fetchCatalog = async () => {
      setCatalogLoading(true);
      try {
        const params = new URLSearchParams({
          limit: "50",
        });
        if (catalogCursor) params.set("cursor", catalogCursor);
        if (catalogSearch) params.set("search", catalogSearch);

        const data = parseCatalogPage(await authenticatedFetch(
          `/product_variants/simple/cursor?${params.toString()}`,
          { signal: requestController.signal },
        ));

        if (requestId !== catalogRequestSeq.current) return;

        setCatalogItems(data.items);
        setCatalogNextCursor(data.next_cursor);
        if (typeof data.total === "number") {
          setCatalogTotal(data.total);
        }
      } catch (e: unknown) {
        if (requestId !== catalogRequestSeq.current) return;
        if (e instanceof Error && e.name === "AbortError") return;
        setCatalogItems([]);
        setCatalogNextCursor(null);
        toast.error(apiErrorMessage(e, "فشل جلب كتالوج المنتجات."));
      } finally {
        if (catalogAbortRef.current === requestController) {
          catalogAbortRef.current = null;
        }
        if (requestId === catalogRequestSeq.current) {
          setCatalogLoading(false);
        }
      }
    };

    fetchCatalog();
    return () => {
      catalogRequestSeq.current += 1;
      requestController.abort();
    };
  }, [authenticatedFetch, catalogCursor, catalogSearch]);

  // ترقية مسودات v2 الموجودة قبل Pagination: نحسم هويات المنتجات دفعة واحدة
  // حتى لا تضيع مسودة صنف غير موجود في الصفحة الحالية.
  useEffect(() => {
    const missingIds = Object.keys(drafts)
      .filter((id) => !draftProducts[id])
      .map((id) => Number(id))
      .filter((id) => Number.isInteger(id) && id > 0);

    if (missingIds.length === 0) return;

    draftResolveAbortRef.current?.abort();
    const requestController = new AbortController();
    draftResolveAbortRef.current = requestController;
    authenticatedFetch("/product_variants/simple/resolve", {
      method: "POST",
      signal: requestController.signal,
      body: JSON.stringify({ ids: missingIds }),
    })
      .then((rawItems) => {
        const items = parseCatalogItems(rawItems);
        if (requestController.signal.aborted) return;
        setDraftProducts((prev) => {
          const next = { ...prev };
          for (const item of items) {
            next[String(item.id)] = item;
          }
          return next;
        });

        if (items.length !== missingIds.length) {
          toast.warning(
            "يوجد صنف قديم في مسودة التوريد لم يعد فعالاً. راجع المسودة قبل الإرسال."
          );
        }
      })
      .catch((e: unknown) => {
        if (!(e instanceof Error && e.name === "AbortError") && !requestController.signal.aborted) {
          toast.error(apiErrorMessage(e, "تعذر استعادة بيانات مسودة التوريد القديمة."));
        }
      });

    return () => {
      requestController.abort();
    };
  }, [authenticatedFetch, drafts, draftProducts]);

  const rememberProduct = (product: SimpleProductVariant) => {
    setDraftProducts((prev) => {
      const key = String(product.id);
      const current = prev[key];
      if (
        current
        && current.name === product.name
        && current.sku === product.sku
        && current.packs_per_carton === product.packs_per_carton
      ) {
        return prev;
      }
      return { ...prev, [key]: product };
    });
  };

  const updateBatch = (
    product: SimpleProductVariant,
    rowId: string,
    patch: Partial<Omit<InboundBatchDraft, "row_id">>,
  ) => {
    rememberProduct(product);
    const productId = String(product.id);

    setDrafts((prev) => {
      const rows = prev[productId]?.length
        ? [...prev[productId]]
        : [emptyInboundBatch(rowId)];
      const index = rows.findIndex((row) => row.row_id === rowId);

      if (index === -1) {
        rows.push({ ...emptyInboundBatch(rowId), ...patch });
      } else {
        rows[index] = { ...rows[index], ...patch };
      }

      return { ...prev, [productId]: rows };
    });
  };

  const addBatch = (product: SimpleProductVariant) => {
    rememberProduct(product);
    const productId = String(product.id);

    setDrafts((prev) => {
      const rows = prev[productId]?.length
        ? [...prev[productId]]
        : [emptyInboundBatch(`base-${productId}`)];
      rows.push(emptyInboundBatch(freshRowId()));
      return { ...prev, [productId]: rows };
    });
  };

  const removeBatch = (productId: string, rowId: string) => {
    setDrafts((prev) => {
      const rows = (prev[productId] || []).filter((row) => row.row_id !== rowId);
      const next = { ...prev };
      if (rows.length === 0) delete next[productId];
      else next[productId] = rows;
      return next;
    });
  };

  const clearAll = () => {
    const hasDraft = Object.values(drafts).some((rows) => rows.some((row) => (
      row.cartons > 0 || row.loose_packs > 0 || row.batch_number || row.production_date || row.expiry_date
    )));
    if (hasDraft || referenceId || notes) setIsConfirmClearOpen(true);
  };

  const clearStoredRequestIdentity = () => {
    localStorage.removeItem(storageKeys.requestId);
    localStorage.removeItem(storageKeys.fingerprint);
  };

  const confirmClear = () => {
    setDrafts({});
    setDraftProducts({});
    setReferenceId("");
    setNotes("");
    localStorage.removeItem(storageKeys.drafts);
    localStorage.removeItem(storageKeys.products);
    localStorage.removeItem(storageKeys.reference);
    localStorage.removeItem(storageKeys.notes);
    clearStoredRequestIdentity();
    setIsConfirmClearOpen(false);
    toast.success("تم تصفير التوريدة والمسودة بالكامل بنجاح");
  };

  const handleSubmit = async () => {
    if (isAuditLocked) {
      toast.error("المستودع مقفل بجرد شامل ولا يمكن توثيق التوريد حالياً.");
      return;
    }
    const requestedProductIds = inboundProductIds(drafts);

    if (requestedProductIds.length === 0) {
      toast.error("أضف كمية لصنف واحد على الأقل لتوريده.");
      return;
    }
    const normalizedReference = referenceId.trim();
    const normalizedNotes = notes.trim();
    if (!normalizedReference) {
      toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد.");
      return;
    }
    if (normalizedReference.length > 100 || normalizedNotes.length > 4000) {
      toast.error("رقم المرجع أو الملاحظات يتجاوز الحد المسموح.");
      return;
    }

    setSubmitting(true);
    try {
      // Resolve fresh metadata immediately before converting cartons -> packs.
      // This prevents a long-lived draft from using an old packs_per_carton.
      const resolvedProducts = parseCatalogItems(await authenticatedFetch(
        "/product_variants/simple/resolve",
        {
          method: "POST",
          body: JSON.stringify({ ids: requestedProductIds }),
        }
      ));

      const freshProducts = new Map<string, SimpleProductVariant>(
        resolvedProducts.map((product) => [
          String(product.id),
          product,
        ])
      );

      if (freshProducts.size !== requestedProductIds.length) {
        throw new Error(
          "يوجد صنف في مسودة التوريد لم يعد فعالاً أو لا يتبع شركتك. أزل الصنف ثم أعد المحاولة."
        );
      }

      setDraftProducts((prev) => {
        const next = { ...prev };
        for (const product of resolvedProducts) {
          next[String(product.id)] = product;
        }
        return next;
      });

      const itemsToSubmit = buildInboundItems(drafts, freshProducts);

      const businessPayload = {
        location_id: locationId,
        reference_id: normalizedReference,
        notes: normalizedNotes || null,
        items: itemsToSubmit,
      };

      // Same business payload after timeout => same UUID. Any material edit => new UUID.
      const fingerprint = JSON.stringify(businessPayload);

      let requestId = localStorage.getItem(storageKeys.requestId);
      const previousFingerprint = localStorage.getItem(storageKeys.fingerprint);

      if (!requestId || previousFingerprint !== fingerprint) {
        requestId = crypto.randomUUID();
        localStorage.setItem(storageKeys.requestId, requestId);
        localStorage.setItem(storageKeys.fingerprint, fingerprint);
      }

      const data = await authenticatedFetch("/warehouse/inbound", {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, ...businessPayload }),
      });

      toast.success(parseInboundResponse(data).message);
      setDrafts({});
      setDraftProducts({});
      setReferenceId("");
      setNotes("");
      localStorage.removeItem(storageKeys.drafts);
      localStorage.removeItem(storageKeys.products);
      localStorage.removeItem(storageKeys.reference);
      localStorage.removeItem(storageKeys.notes);
      clearStoredRequestIdentity();
      await onSuccess();
    } catch (e: unknown) {
      toast.error(apiErrorMessage(e, "فشل توثيق التوريد."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="inventory-view inventory-inbound flex flex-col h-full flex-1 min-h-0 pt-1 animate-in fade-in duration-300">
      <div className="inventory-surface inventory-data-panel relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm pb-2 flex-1 min-h-0">
        <div className="inventory-panel-label inventory-panel-label--success absolute -top-3.5 right-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
          <FilePlus className="w-4 h-4" /> توريد بضاعة (الاستلام المخزني)
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-white mt-5 border-b border-slate-100">
          <table className="w-full text-sm min-w-[1100px]">
            <thead className="sticky top-0 z-10 bg-slate-50 shadow-sm border-b border-slate-200">
              <tr className="text-slate-500 text-xs uppercase text-right">
                <th className="py-3 px-4 font-extrabold w-[24%]">
                  <div className="flex items-center gap-3">
                    <span>المنتج</span>
                    <div className="relative font-normal flex-1">
                      <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        type="search"
                        placeholder="ابحث عن صنف أو SKU..."
                        value={catalogSearchInput}
                        maxLength={100}
                        onChange={(e) => setCatalogSearchInput(e.target.value)}
                        className="w-full pl-3 pr-9 py-1.5 text-xs border border-slate-200 rounded-lg outline-none focus:border-emerald-400 bg-white shadow-sm"
                      />
                    </div>
                  </div>
                </th>
                <th className="py-3 px-4 font-extrabold">الدفعة والصلاحية</th>
                <th className="py-3 px-4 font-extrabold text-center">الكمية (كرتونة / حبة)</th>
                <th className="py-3 px-4 w-28 text-center">
                  <button onClick={clearAll} className="text-[10px] font-bold text-red-500 hover:text-red-700 flex items-center gap-1 bg-red-50 hover:bg-red-100 px-2.5 py-1.5 rounded-md border border-red-100 mx-auto">
                    <Eraser className="w-3.5 h-3.5" /> تصفير
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {catalogItems.length === 0 ? (
                <tr><td colSpan={4} className="text-center py-12 text-slate-400">{catalogLoading ? "جارٍ تحميل الكتالوج..." : "لا توجد منتجات مطابقة"}</td></tr>
              ) : catalogItems.map((product) => {
                const productId = String(product.id);
                const rows = drafts[productId]?.length
                  ? drafts[productId]
                  : [emptyInboundBatch(`base-${productId}`)];
                const ppc = product.packs_per_carton || 1;

                return rows.map((row, index) => {
                  const hasQty = row.cartons > 0 || row.loose_packs > 0;
                  const looseError = row.loose_packs >= ppc;
                  return (
                    <tr key={`${productId}:${row.row_id}`} className={hasQty ? "bg-emerald-50/35" : "hover:bg-slate-50"}>
                      <td className="py-2 px-4 align-top">
                        {index === 0 ? (
                          <>
                            <div className="font-bold text-slate-800">{product.name}</div>
                            <div className="text-[10px] text-slate-400 mt-1">SKU: {product.sku || "—"} • التعبئة: {ppc} حبة</div>
                          </>
                        ) : (
                          <div className="text-xs font-bold text-emerald-700">دفعة إضافية لنفس الصنف</div>
                        )}
                      </td>

                      <td className="py-2 px-4 align-top">
                        <div className="grid grid-cols-3 gap-2">
                          <input
                            value={row.batch_number}
                            maxLength={100}
                            onChange={(e) => updateBatch(product, row.row_id, { batch_number: e.target.value })}
                            placeholder="رقم الدفعة *"
                            className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold outline-none focus:border-emerald-400"
                          />
                          <div>
                            <label className="block text-[9px] text-slate-400 mb-0.5">الإنتاج (اختياري)</label>
                            <input
                              type="date"
                              value={row.production_date}
                              onChange={(e) => updateBatch(product, row.row_id, { production_date: e.target.value })}
                              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-emerald-400"
                            />
                          </div>
                          <div>
                            <label className="block text-[9px] text-slate-400 mb-0.5">الصلاحية *</label>
                            <input
                              type="date"
                              value={row.expiry_date}
                              onChange={(e) => updateBatch(product, row.row_id, { expiry_date: e.target.value })}
                              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-emerald-400"
                            />
                          </div>
                        </div>
                      </td>

                      <td className="py-2 px-4 align-top">
                        <div className="flex items-center justify-center gap-6">
                          <div className="flex flex-col items-center gap-1">
                            <span className="text-[10px] font-bold text-slate-500">كراتين</span>
                            <QuantityInput
                              value={row.cartons}
                              onChange={(value) => updateBatch(product, row.row_id, { cartons: value })}
                            />
                          </div>
                          <div className="flex flex-col items-center gap-1">
                            <span className={`text-[10px] font-bold ${looseError ? "text-red-600" : "text-slate-500"}`}>حبات</span>
                            <QuantityInput
                              value={row.loose_packs}
                              onChange={(value) => updateBatch(product, row.row_id, { loose_packs: value })}
                              isError={looseError}
                            />
                          </div>
                        </div>
                      </td>

                      <td className="py-2 px-4 align-top">
                        <div className="flex items-center justify-center gap-1 mt-4">
                          {index === 0 && (
                            <button
                              type="button"
                              onClick={() => addBatch(product)}
                              title="إضافة دفعة أخرى لنفس الصنف"
                              className="p-2 rounded-lg text-emerald-600 bg-emerald-50 hover:bg-emerald-100 border border-emerald-100"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          )}
                          {index > 0 && (
                            <button
                              type="button"
                              onClick={() => removeBatch(productId, row.row_id)}
                              title="حذف هذه الدفعة"
                              className="p-2 rounded-lg text-red-500 bg-red-50 hover:bg-red-100 border border-red-100"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                });
              })}
            </tbody>
          </table>
        </div>

        {(catalogHistory.length > 0 || !!catalogNextCursor) && (
          <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-200 bg-slate-50">
            <span className="text-[11px] font-bold text-slate-500">
              صفحة {catalogHistory.length + 1}
              {catalogTotal !== null ? ` • ${catalogTotal} صنف` : ""}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  if (catalogHistory.length === 0) return;
                  const previous = catalogHistory[catalogHistory.length - 1] ?? null;
                  setCatalogHistory((prev) => prev.slice(0, -1));
                  setCatalogCursor(previous);
                }}
                disabled={catalogHistory.length === 0 || catalogLoading}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
                title="الصفحة السابقة"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!catalogNextCursor) return;
                  setCatalogHistory((prev) => [...prev, catalogCursor]);
                  setCatalogCursor(catalogNextCursor);
                }}
                disabled={!catalogNextCursor || catalogLoading}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
                title="الصفحة التالية"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        <div className="p-3 bg-slate-50 rounded-b-2xl">
          <div className="flex flex-col md:flex-row items-center gap-3">
            <div className="flex-1 w-full grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
              <div className="relative">
                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">رقم الفاتورة / المرجع <span className="text-red-500">*</span></span>
                <input
                  value={referenceId}
                  maxLength={100}
                  onChange={(e) => setReferenceId(e.target.value)}
                  placeholder="مثال: INV-2026-001"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"
                />
              </div>
              <div className="relative">
                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">ملاحظات (اختياري)</span>
                <input
                  value={notes}
                  maxLength={4000}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="أي ملاحظات إضافية..."
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"
                />
              </div>
            </div>
            <div className="w-full md:w-auto mt-2 md:mt-0">
              <button
                onClick={handleSubmit}
                disabled={submitting || isAuditLocked}
                className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-90 text-white px-6 py-2.5 rounded-xl text-sm font-black shadow-md active:scale-[0.98] w-full disabled:opacity-50"
              >
                {submitting ? "جارٍ التوثيق..." : isAuditLocked ? "المستودع مقفل بالجرد" : "✓ توثيق الاستلام"}
              </button>
            </div>
          </div>
        </div>

        {isConfirmClearOpen && (
          <Modal
            isOpen={isConfirmClearOpen}
            onClose={() => setIsConfirmClearOpen(false)}
            title="⚠️ تأكيد التصفير"
            footer={
              <div className="flex gap-2 w-full">
                <button onClick={() => setIsConfirmClearOpen(false)} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl">إلغاء</button>
                <button autoFocus onClick={confirmClear} className="flex-1 px-6 py-2 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl">نعم، تصفير التوريدة</button>
              </div>
            }
          >
            <p className="text-sm text-slate-600 leading-relaxed">سيتم حذف جميع الكميات وبيانات الدفعات والمرجع والملاحظات المحفوظة محليًا.</p>
          </Modal>
        )}
      </div>
    </div>
  );
}
