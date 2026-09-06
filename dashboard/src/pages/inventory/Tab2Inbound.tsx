import { useState, useEffect, useRef } from "react";
import { FilePlus, Search, Eraser, Plus, Trash2, ChevronRight, ChevronLeft } from "lucide-react";
import { toast } from "sonner";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { SimpleProductVariant } from "./inventoryUtils";
import { toTotalPacks } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal";

interface Props {
  locationId: number;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onSuccess: () => void | Promise<void>;
}

interface InboundBatchDraft {
  row_id: string;
  cartons: number;
  loose_packs: number;
  batch_number: string;
  production_date: string;
  expiry_date: string;
}

type InboundDraftMap = Record<string, InboundBatchDraft[]>;

type DraftProductMap = Record<string, SimpleProductVariant>;

function loadDraftProducts(): DraftProductMap {
  const saved = localStorage.getItem("inbound_draft_products_v3");
  if (!saved) return {};
  try {
    const parsed = JSON.parse(saved);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as DraftProductMap;
    }
  } catch {
    localStorage.removeItem("inbound_draft_products_v3");
  }
  return {};
}

const emptyBatch = (rowId: string): InboundBatchDraft => ({
  row_id: rowId,
  cartons: 0,
  loose_packs: 0,
  batch_number: "",
  production_date: "",
  expiry_date: "",
});

const freshRowId = () => crypto.randomUUID();

function loadDrafts(): InboundDraftMap {
  const saved = localStorage.getItem("inbound_batch_drafts_v2");
  if (saved) {
    try {
      const parsed = JSON.parse(saved);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as InboundDraftMap;
      }
    } catch {
      localStorage.removeItem("inbound_batch_drafts_v2");
    }
  }

  // One-time migration of the old quantity-only draft. Batch metadata remains blank
  // and must be completed explicitly before submission.
  const legacy = localStorage.getItem("inbound_draft_quantities");
  if (!legacy) return {};

  try {
    const parsed = JSON.parse(legacy) as Record<string, { cartons?: number; loose_packs?: number }>;
    const migrated: InboundDraftMap = {};
    for (const [productId, qty] of Object.entries(parsed || {})) {
      migrated[productId] = [{
        ...emptyBatch(`base-${productId}`),
        cartons: Math.max(0, Number(qty?.cartons) || 0),
        loose_packs: Math.max(0, Number(qty?.loose_packs) || 0),
      }];
    }
    return migrated;
  } catch {
    return {};
  }
}

export function Tab2Inbound({ locationId, authenticatedFetch, onSuccess }: Props) {
  const [drafts, setDrafts] = useState<InboundDraftMap>(() => loadDrafts());
  const [draftProducts, setDraftProducts] = useState<DraftProductMap>(() => loadDraftProducts());
  const [catalogItems, setCatalogItems] = useState<SimpleProductVariant[]>([]);
  const [catalogSearchInput, setCatalogSearchInput] = useState("");
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogCursor, setCatalogCursor] = useState<string | null>(null);
  const [catalogHistory, setCatalogHistory] = useState<Array<string | null>>([]);
  const [catalogNextCursor, setCatalogNextCursor] = useState<string | null>(null);
  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const catalogRequestSeq = useRef(0);

  const [referenceId, setReferenceId] = useState(() => localStorage.getItem("inbound_draft_ref") || "");
  const [notes, setNotes] = useState(() => localStorage.getItem("inbound_draft_notes") || "");
  const [submitting, setSubmitting] = useState(false);
  const [isConfirmClearOpen, setIsConfirmClearOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem("inbound_batch_drafts_v2", JSON.stringify(drafts));
  }, [drafts]);

  useEffect(() => {
    localStorage.setItem("inbound_draft_products_v3", JSON.stringify(draftProducts));
  }, [draftProducts]);

  useEffect(() => { localStorage.setItem("inbound_draft_ref", referenceId); }, [referenceId]);
  useEffect(() => { localStorage.setItem("inbound_draft_notes", notes); }, [notes]);

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
    let alive = true;
    const requestId = ++catalogRequestSeq.current;

    const fetchCatalog = async () => {
      setCatalogLoading(true);
      try {
        const params = new URLSearchParams({
          limit: "50",
        });
        if (catalogCursor) params.set("cursor", catalogCursor);
        if (catalogSearch) params.set("search", catalogSearch);

        const data = await authenticatedFetch(
          `/product_variants/simple/cursor?${params.toString()}`
        );

        if (!alive || requestId !== catalogRequestSeq.current) return;
        if (!data || !Array.isArray(data.items)) {
          throw new Error("تنسيق كتالوج المنتجات غير صالح.");
        }

        setCatalogItems(data.items);
        setCatalogNextCursor(data.next_cursor || null);
        if (typeof data.total === "number") {
          setCatalogTotal(data.total);
        }
      } catch (e: any) {
        if (!alive || requestId !== catalogRequestSeq.current) return;
        setCatalogItems([]);
        setCatalogNextCursor(null);
        toast.error(e?.message || "فشل جلب كتالوج المنتجات.");
      } finally {
        if (alive && requestId === catalogRequestSeq.current) {
          setCatalogLoading(false);
        }
      }
    };

    fetchCatalog();
    return () => {
      alive = false;
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

    let cancelled = false;
    authenticatedFetch("/product_variants/simple/resolve", {
      method: "POST",
      body: JSON.stringify({ ids: missingIds }),
    })
      .then((items) => {
        if (cancelled || !Array.isArray(items)) return;
        setDraftProducts((prev) => {
          const next = { ...prev };
          for (const item of items as SimpleProductVariant[]) {
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
      .catch((e: any) => {
        if (!cancelled) {
          toast.error(e?.message || "تعذر استعادة بيانات مسودة التوريد القديمة.");
        }
      });

    return () => {
      cancelled = true;
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
        : [emptyBatch(rowId)];
      const index = rows.findIndex((row) => row.row_id === rowId);

      if (index === -1) {
        rows.push({ ...emptyBatch(rowId), ...patch });
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
        : [emptyBatch(`base-${productId}`)];
      rows.push(emptyBatch(freshRowId()));
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
    localStorage.removeItem(`wanasah_inbound_request_id_${locationId}`);
    localStorage.removeItem(`wanasah_inbound_request_fp_${locationId}`);
  };

  const confirmClear = () => {
    setDrafts({});
    setDraftProducts({});
    setReferenceId("");
    setNotes("");
    localStorage.removeItem("inbound_batch_drafts_v2");
    localStorage.removeItem("inbound_draft_products_v3");
    localStorage.removeItem("inbound_draft_quantities");
    localStorage.removeItem("inbound_draft_ref");
    localStorage.removeItem("inbound_draft_notes");
    clearStoredRequestIdentity();
    setIsConfirmClearOpen(false);
    toast.success("تم تصفير التوريدة والمسودة بالكامل بنجاح");
  };

  const handleSubmit = async () => {
    const meaningfulEntries = Object.entries(drafts).filter(([, rows]) =>
      rows.some((row) => row.cartons > 0 || row.loose_packs > 0)
    );

    if (meaningfulEntries.length === 0) {
      toast.error("أضف كمية لصنف واحد على الأقل لتوريده.");
      return;
    }
    if (!referenceId.trim()) {
      toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد.");
      return;
    }

    setSubmitting(true);
    try {
      // Resolve fresh metadata immediately before converting cartons -> packs.
      // This prevents a long-lived draft from using an old packs_per_carton.
      const requestedProductIds = meaningfulEntries.map(([productId]) => Number(productId));
      const resolvedProducts = await authenticatedFetch(
        "/product_variants/simple/resolve",
        {
          method: "POST",
          body: JSON.stringify({ ids: requestedProductIds }),
        }
      );

      if (!Array.isArray(resolvedProducts)) {
        throw new Error("تعذر التحقق من بيانات أصناف التوريد.");
      }

      const freshProducts = new Map<string, SimpleProductVariant>(
        (resolvedProducts as SimpleProductVariant[]).map((product) => [
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
        for (const product of resolvedProducts as SimpleProductVariant[]) {
          next[String(product.id)] = product;
        }
        return next;
      });

      const itemsToSubmit: Array<{
        product_variant_id: number;
        quantity_packs: number;
        batch_number: string;
        production_date: string | null;
        expiry_date: string;
      }> = [];

      const seenBatchKeys = new Set<string>();

      for (const [productId, rows] of meaningfulEntries) {
        const product = freshProducts.get(productId);
        if (!product) {
          throw new Error(`تعذر التحقق من الصنف رقم ${productId}.`);
        }

        const ppc = product.packs_per_carton || 1;

        for (const row of rows) {
          if (row.cartons === 0 && row.loose_packs === 0) continue;

          if (row.loose_packs >= ppc) {
            throw new Error(
              `خطأ في (${product.name}): الحبات يجب أن تكون أقل من ${ppc}.`
            );
          }

          const batchNumber = row.batch_number.trim();
          if (!batchNumber) {
            throw new Error(`أدخل رقم الدفعة للصنف (${product.name}).`);
          }
          if (!row.expiry_date) {
            throw new Error(
              `أدخل تاريخ الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`
            );
          }
          if (row.production_date && row.production_date > row.expiry_date) {
            throw new Error(
              `تاريخ الإنتاج بعد الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`
            );
          }

          const duplicateKey = `${product.id}|${batchNumber}`;
          if (seenBatchKeys.has(duplicateKey)) {
            throw new Error(
              `الدفعة (${batchNumber}) مكررة للصنف (${product.name}). اجمع الكمية في سطر واحد.`
            );
          }
          seenBatchKeys.add(duplicateKey);

          itemsToSubmit.push({
            product_variant_id: product.id,
            quantity_packs: toTotalPacks(row.cartons, row.loose_packs, ppc),
            batch_number: batchNumber,
            production_date: row.production_date || null,
            expiry_date: row.expiry_date,
          });
        }
      }

      itemsToSubmit.sort((a, b) => (
        a.product_variant_id - b.product_variant_id
        || a.batch_number.localeCompare(b.batch_number)
      ));

      const businessPayload = {
        location_id: locationId,
        reference_id: referenceId.trim(),
        notes,
        items: itemsToSubmit,
      };

      // Same business payload after timeout => same UUID. Any material edit => new UUID.
      const requestIdKey = `wanasah_inbound_request_id_${locationId}`;
      const fingerprintKey = `wanasah_inbound_request_fp_${locationId}`;
      const fingerprint = JSON.stringify(businessPayload);

      let requestId = localStorage.getItem(requestIdKey);
      const previousFingerprint = localStorage.getItem(fingerprintKey);

      if (!requestId || previousFingerprint !== fingerprint) {
        requestId = crypto.randomUUID();
        localStorage.setItem(requestIdKey, requestId);
        localStorage.setItem(fingerprintKey, fingerprint);
      }

      const data = await authenticatedFetch("/warehouse/inbound", {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, ...businessPayload }),
      });

      toast.success(data?.message || "تم استلام البضاعة وتوثيقها بنجاح ✅");
      setDrafts({});
      setDraftProducts({});
      setReferenceId("");
      setNotes("");
      localStorage.removeItem("inbound_batch_drafts_v2");
      localStorage.removeItem("inbound_draft_products_v3");
      localStorage.removeItem("inbound_draft_quantities");
      localStorage.removeItem("inbound_draft_ref");
      localStorage.removeItem("inbound_draft_notes");
      clearStoredRequestIdentity();
      await onSuccess();
    } catch (e: any) {
      toast.error(e?.message || "فشل توثيق التوريد.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col h-full flex-1 min-h-0 pt-1 animate-in fade-in duration-300">
      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm pb-2 flex-1 min-h-0">
        <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
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
                  : [emptyBatch(`base-${productId}`)];
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
                  onChange={(e) => setReferenceId(e.target.value)}
                  placeholder="مثال: INV-2026-001"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"
                />
              </div>
              <div className="relative">
                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">ملاحظات (اختياري)</span>
                <input
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="أي ملاحظات إضافية..."
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"
                />
              </div>
            </div>
            <div className="w-full md:w-auto mt-2 md:mt-0">
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-90 text-white px-6 py-2.5 rounded-xl text-sm font-black shadow-md active:scale-[0.98] w-full disabled:opacity-50"
              >
                {submitting ? "جارٍ التوثيق..." : "✓ توثيق الاستلام"}
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
