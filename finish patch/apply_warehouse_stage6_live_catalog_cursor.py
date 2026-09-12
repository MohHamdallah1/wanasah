from __future__ import annotations

import ast
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
DASHBOARD = ROOT / "dashboard"
INV_DIR = DASHBOARD / "src" / "pages" / "inventory"

FILES = {
    "models": BACKEND / "models.py",
    "schemas": BACKEND / "schemas.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
    "main": INV_DIR / "MainInventory.tsx",
    "live": INV_DIR / "Tab1LiveStock.tsx",
    "inbound": INV_DIR / "Tab2Inbound.tsx",
    "stocktake": INV_DIR / "Tab3Stocktake.tsx",
    "utils": INV_DIR / "inventoryUtils.ts",
}

TAB1_FINAL = 'import { useState, useEffect } from "react";\nimport { AlertTriangle, RefreshCcw, Search, Info, FilterX, ChevronRight, ChevronLeft } from "lucide-react";\nimport type { WarehouseProduct } from "./inventoryUtils";\nimport { formatQty } from "./inventoryUtils";\n\ninterface Props {\n  locationId: number;\n  products: WarehouseProduct[];\n  loading: boolean;\n  alertCount: number;\n  alertSamples: string[];\n  matchingTotal: number | null;\n  pageNumber: number;\n  hasMore: boolean;\n  hasPrevious: boolean;\n  onlyAlerts: boolean;\n  onSearchChange: (search: string) => void;\n  onOnlyAlertsChange: (onlyAlerts: boolean) => void;\n  onNext: () => void;\n  onPrevious: () => void;\n  onRefresh: () => void;\n}\n\nexport function Tab1LiveStock({\n  locationId,\n  products,\n  loading,\n  alertCount,\n  alertSamples,\n  matchingTotal,\n  pageNumber,\n  hasMore,\n  hasPrevious,\n  onlyAlerts,\n  onSearchChange,\n  onOnlyAlertsChange,\n  onNext,\n  onPrevious,\n  onRefresh,\n}: Props) {\n  const [searchInput, setSearchInput] = useState("");\n  const [lastSync, setLastSync] = useState<Date>(new Date());\n\n  useEffect(() => {\n    setSearchInput("");\n  }, [locationId]);\n\n  useEffect(() => {\n    const handler = window.setTimeout(() => {\n      const clean = searchInput.trim();\n      onSearchChange(clean.length >= 2 ? clean : "");\n    }, 300);\n    return () => window.clearTimeout(handler);\n  }, [searchInput, onSearchChange]);\n\n  useEffect(() => {\n    if (!loading) setLastSync(new Date());\n  }, [products, loading]);\n\n  useEffect(() => {\n    if (alertCount === 0 && onlyAlerts) {\n      onOnlyAlertsChange(false);\n    }\n  }, [alertCount, onlyAlerts, onOnlyAlertsChange]);\n\n  return (\n    <div className="flex flex-col gap-3 h-full flex-1 min-h-0">\n      {alertCount > 0 && (\n        <div\n          onClick={() => onOnlyAlertsChange(!onlyAlerts)}\n          className={`flex flex-col sm:flex-row items-start gap-3 border rounded-2xl px-4 py-3 w-full cursor-pointer transition-all shadow-sm ${\n            onlyAlerts\n              ? "bg-red-100 border-red-400"\n              : "bg-red-50 border-red-200 hover:bg-red-100 pulse-border-red"\n          }`}\n          title="اضغط هنا لفلترة الجدول وعرض النواقص فقط"\n        >\n          <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${onlyAlerts ? "text-red-600" : "text-red-500"}`} />\n          <div className="flex-1 min-w-0 flex justify-between items-center">\n            <div>\n              <p className="text-sm font-bold text-red-700">\n                تحذير: {alertCount} صنف وصل للحد الأدنى\n              </p>\n              <p className="text-xs text-red-500 mt-0.5">\n                {onlyAlerts\n                  ? "تمت تصفية الجدول لعرض هذه الأصناف بالأسفل ↓"\n                  : `(اضغط هنا لعرضها بالجدول) منها: ${alertSamples.join(" • ")}${alertCount > alertSamples.length ? "..." : ""}`}\n              </p>\n            </div>\n            {onlyAlerts && <FilterX className="w-5 h-5 text-red-500 opacity-70" />}\n          </div>\n        </div>\n      )}\n\n      <div className="glass-card overflow-hidden pt-0 flex flex-col flex-1 min-h-0">\n        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100 bg-white/70">\n          <div className="text-[11px] font-bold text-slate-400">\n            {matchingTotal !== null ? `النتائج: ${matchingTotal}` : `صفحة ${pageNumber}`}\n            <span className="mx-2">•</span>\n            آخر تحديث: {lastSync.toLocaleTimeString("ar-EG")}\n          </div>\n          <button\n            type="button"\n            onClick={onRefresh}\n            disabled={loading}\n            className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500 hover:text-[#1e87bb] disabled:opacity-40"\n          >\n            <RefreshCcw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />\n            تحديث\n          </button>\n        </div>\n\n        <div className={`flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar transition-all duration-300 ${\n          loading ? "opacity-50 pointer-events-none select-none grayscale-[20%]" : "opacity-100"\n        }`}>\n          <table className="w-full text-sm">\n            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur shadow-sm border-b border-slate-200 text-right">\n              <tr>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 w-1/3 min-w-[250px] align-middle">\n                  <div className="flex items-center gap-3">\n                    <span>المنتج</span>\n                    <div className="relative font-normal flex-1">\n                      <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />\n                      <input\n                        type="search"\n                        placeholder="ابحث عن صنف أو SKU..."\n                        value={searchInput}\n                        onChange={(e) => setSearchInput(e.target.value)}\n                        className="w-full pl-4 pr-9 py-2 text-xs border border-slate-200 rounded-lg outline-none focus:border-[#1e87bb] bg-white transition-all shadow-sm"\n                      />\n                    </div>\n                  </div>\n                </th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">رمز الصنف (SKU)</th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">في المستودع</th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    قيد التحويل <Info className="w-3 h-3" />\n                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">\n                      البضاعة المحجوزة داخل الرصيد الفيزيائي وغير المتاحة حالياً للصرف\n                    </div>\n                  </div>\n                </th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    إجمالي البضاعة <Info className="w-3 h-3" />\n                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">\n                      الرصيد الفيزيائي في المستودع والسيارات المرتبطة بهذا المستودع\n                    </div>\n                  </div>\n                </th>\n                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">\n                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">\n                    التوالف بالفرع <Info className="w-3 h-3" />\n                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">\n                      التوالف والمرتجعات المعزولة في المستودع بانتظار الإتلاف\n                    </div>\n                  </div>\n                </th>\n              </tr>\n            </thead>\n            <tbody>\n              {products.length === 0 && (\n                <tr>\n                  <td colSpan={6} className="text-center py-12 text-slate-400 text-sm">\n                    {loading ? "جارٍ التحميل..." : "لا توجد بيانات مطابقة"}\n                  </td>\n                </tr>\n              )}\n\n              {products.map((p) => {\n                const isAlert = p.min_threshold > 0 && p.available_packs <= p.min_threshold;\n                return (\n                  <tr\n                    key={p.id}\n                    className={`border-b border-slate-100/80 transition-all duration-200 ${\n                      isAlert ? "bg-red-50/50 hover:bg-red-50/80" : "bg-white hover:bg-slate-50/60"\n                    }`}\n                  >\n                    <td className="px-4 py-3 font-semibold text-slate-800 flex items-center gap-2">\n                      {isAlert && (\n                        <span title="وصل للحد الأدنى">\n                          <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0" />\n                        </span>\n                      )}\n                      {p.name}\n                    </td>\n                    <td className="px-4 py-3 text-slate-500 font-mono text-xs">{p.sku || "—"}</td>\n                    <td className="px-4 py-3 text-emerald-700 font-semibold">\n                      {formatQty(p.available_packs, p.packs_per_carton)}\n                      {p.blocked_packs > 0 && (\n                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">\n                          محجوب عن الصرف: {formatQty(p.blocked_packs, p.packs_per_carton)}\n                        </div>\n                      )}\n                    </td>\n                    <td className="px-4 py-3 text-violet-600 font-semibold">\n                      {formatQty(p.reserved_packs, p.packs_per_carton)}\n                    </td>\n                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">\n                      {formatQty(p.total_packs, p.packs_per_carton)}\n                    </td>\n                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">\n                      {formatQty(p.damaged_packs || 0, p.packs_per_carton)}\n                    </td>\n                  </tr>\n                );\n              })}\n            </tbody>\n          </table>\n        </div>\n\n        {(hasPrevious || hasMore) && (\n          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50">\n            <span className="text-xs font-bold text-slate-500">صفحة {pageNumber}</span>\n            <div className="flex gap-2">\n              <button\n                type="button"\n                onClick={onPrevious}\n                disabled={!hasPrevious || loading}\n                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"\n                title="الصفحة السابقة"\n              >\n                <ChevronRight className="w-4 h-4" />\n              </button>\n              <button\n                type="button"\n                onClick={onNext}\n                disabled={!hasMore || loading}\n                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"\n                title="الصفحة التالية"\n              >\n                <ChevronLeft className="w-4 h-4" />\n              </button>\n            </div>\n          </div>\n        )}\n      </div>\n    </div>\n  );\n}\n'
TAB2_FINAL = 'import { useState, useEffect, useRef } from "react";\nimport { FilePlus, Search, Eraser, Plus, Trash2, ChevronRight, ChevronLeft } from "lucide-react";\nimport { toast } from "sonner";\nimport { QuantityInput } from "@/components/ui/quantity-input";\nimport type { SimpleProductVariant } from "./inventoryUtils";\nimport { toTotalPacks } from "./inventoryUtils";\nimport { Modal } from "@/components/ui/modal";\n\ninterface Props {\n  locationId: number;\n  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;\n  onSuccess: () => void | Promise<void>;\n}\n\ninterface InboundBatchDraft {\n  row_id: string;\n  cartons: number;\n  loose_packs: number;\n  batch_number: string;\n  production_date: string;\n  expiry_date: string;\n}\n\ntype InboundDraftMap = Record<string, InboundBatchDraft[]>;\n\ntype DraftProductMap = Record<string, SimpleProductVariant>;\n\nfunction loadDraftProducts(): DraftProductMap {\n  const saved = localStorage.getItem("inbound_draft_products_v3");\n  if (!saved) return {};\n  try {\n    const parsed = JSON.parse(saved);\n    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {\n      return parsed as DraftProductMap;\n    }\n  } catch {\n    localStorage.removeItem("inbound_draft_products_v3");\n  }\n  return {};\n}\n\nconst emptyBatch = (rowId: string): InboundBatchDraft => ({\n  row_id: rowId,\n  cartons: 0,\n  loose_packs: 0,\n  batch_number: "",\n  production_date: "",\n  expiry_date: "",\n});\n\nconst freshRowId = () => crypto.randomUUID();\n\nfunction loadDrafts(): InboundDraftMap {\n  const saved = localStorage.getItem("inbound_batch_drafts_v2");\n  if (saved) {\n    try {\n      const parsed = JSON.parse(saved);\n      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {\n        return parsed as InboundDraftMap;\n      }\n    } catch {\n      localStorage.removeItem("inbound_batch_drafts_v2");\n    }\n  }\n\n  // One-time migration of the old quantity-only draft. Batch metadata remains blank\n  // and must be completed explicitly before submission.\n  const legacy = localStorage.getItem("inbound_draft_quantities");\n  if (!legacy) return {};\n\n  try {\n    const parsed = JSON.parse(legacy) as Record<string, { cartons?: number; loose_packs?: number }>;\n    const migrated: InboundDraftMap = {};\n    for (const [productId, qty] of Object.entries(parsed || {})) {\n      migrated[productId] = [{\n        ...emptyBatch(`base-${productId}`),\n        cartons: Math.max(0, Number(qty?.cartons) || 0),\n        loose_packs: Math.max(0, Number(qty?.loose_packs) || 0),\n      }];\n    }\n    return migrated;\n  } catch {\n    return {};\n  }\n}\n\nexport function Tab2Inbound({ locationId, authenticatedFetch, onSuccess }: Props) {\n  const [drafts, setDrafts] = useState<InboundDraftMap>(() => loadDrafts());\n  const [draftProducts, setDraftProducts] = useState<DraftProductMap>(() => loadDraftProducts());\n  const [catalogItems, setCatalogItems] = useState<SimpleProductVariant[]>([]);\n  const [catalogSearchInput, setCatalogSearchInput] = useState("");\n  const [catalogSearch, setCatalogSearch] = useState("");\n  const [catalogCursor, setCatalogCursor] = useState<string | null>(null);\n  const [catalogHistory, setCatalogHistory] = useState<Array<string | null>>([]);\n  const [catalogNextCursor, setCatalogNextCursor] = useState<string | null>(null);\n  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);\n  const [catalogLoading, setCatalogLoading] = useState(false);\n  const catalogRequestSeq = useRef(0);\n\n  const [referenceId, setReferenceId] = useState(() => localStorage.getItem("inbound_draft_ref") || "");\n  const [notes, setNotes] = useState(() => localStorage.getItem("inbound_draft_notes") || "");\n  const [submitting, setSubmitting] = useState(false);\n  const [isConfirmClearOpen, setIsConfirmClearOpen] = useState(false);\n\n  useEffect(() => {\n    localStorage.setItem("inbound_batch_drafts_v2", JSON.stringify(drafts));\n  }, [drafts]);\n\n  useEffect(() => {\n    localStorage.setItem("inbound_draft_products_v3", JSON.stringify(draftProducts));\n  }, [draftProducts]);\n\n  useEffect(() => { localStorage.setItem("inbound_draft_ref", referenceId); }, [referenceId]);\n  useEffect(() => { localStorage.setItem("inbound_draft_notes", notes); }, [notes]);\n\n  useEffect(() => {\n    const handler = window.setTimeout(() => {\n      const clean = catalogSearchInput.trim();\n      setCatalogSearch(clean.length >= 2 ? clean : "");\n      setCatalogCursor(null);\n      setCatalogHistory([]);\n    }, 300);\n    return () => window.clearTimeout(handler);\n  }, [catalogSearchInput]);\n\n  useEffect(() => {\n    let alive = true;\n    const requestId = ++catalogRequestSeq.current;\n\n    const fetchCatalog = async () => {\n      setCatalogLoading(true);\n      try {\n        const params = new URLSearchParams({\n          limit: "50",\n        });\n        if (catalogCursor) params.set("cursor", catalogCursor);\n        if (catalogSearch) params.set("search", catalogSearch);\n\n        const data = await authenticatedFetch(\n          `/product_variants/simple/cursor?${params.toString()}`\n        );\n\n        if (!alive || requestId !== catalogRequestSeq.current) return;\n        if (!data || !Array.isArray(data.items)) {\n          throw new Error("تنسيق كتالوج المنتجات غير صالح.");\n        }\n\n        setCatalogItems(data.items);\n        setCatalogNextCursor(data.next_cursor || null);\n        if (typeof data.total === "number") {\n          setCatalogTotal(data.total);\n        }\n      } catch (e: any) {\n        if (!alive || requestId !== catalogRequestSeq.current) return;\n        setCatalogItems([]);\n        setCatalogNextCursor(null);\n        toast.error(e?.message || "فشل جلب كتالوج المنتجات.");\n      } finally {\n        if (alive && requestId === catalogRequestSeq.current) {\n          setCatalogLoading(false);\n        }\n      }\n    };\n\n    fetchCatalog();\n    return () => {\n      alive = false;\n    };\n  }, [authenticatedFetch, catalogCursor, catalogSearch]);\n\n  // ترقية مسودات v2 الموجودة قبل Pagination: نحسم هويات المنتجات دفعة واحدة\n  // حتى لا تضيع مسودة صنف غير موجود في الصفحة الحالية.\n  useEffect(() => {\n    const missingIds = Object.keys(drafts)\n      .filter((id) => !draftProducts[id])\n      .map((id) => Number(id))\n      .filter((id) => Number.isInteger(id) && id > 0);\n\n    if (missingIds.length === 0) return;\n\n    let cancelled = false;\n    authenticatedFetch("/product_variants/simple/resolve", {\n      method: "POST",\n      body: JSON.stringify({ ids: missingIds }),\n    })\n      .then((items) => {\n        if (cancelled || !Array.isArray(items)) return;\n        setDraftProducts((prev) => {\n          const next = { ...prev };\n          for (const item of items as SimpleProductVariant[]) {\n            next[String(item.id)] = item;\n          }\n          return next;\n        });\n\n        if (items.length !== missingIds.length) {\n          toast.warning(\n            "يوجد صنف قديم في مسودة التوريد لم يعد فعالاً. راجع المسودة قبل الإرسال."\n          );\n        }\n      })\n      .catch((e: any) => {\n        if (!cancelled) {\n          toast.error(e?.message || "تعذر استعادة بيانات مسودة التوريد القديمة.");\n        }\n      });\n\n    return () => {\n      cancelled = true;\n    };\n  }, [authenticatedFetch, drafts, draftProducts]);\n\n  const rememberProduct = (product: SimpleProductVariant) => {\n    setDraftProducts((prev) => {\n      const key = String(product.id);\n      const current = prev[key];\n      if (\n        current\n        && current.name === product.name\n        && current.sku === product.sku\n        && current.packs_per_carton === product.packs_per_carton\n      ) {\n        return prev;\n      }\n      return { ...prev, [key]: product };\n    });\n  };\n\n  const updateBatch = (\n    product: SimpleProductVariant,\n    rowId: string,\n    patch: Partial<Omit<InboundBatchDraft, "row_id">>,\n  ) => {\n    rememberProduct(product);\n    const productId = String(product.id);\n\n    setDrafts((prev) => {\n      const rows = prev[productId]?.length\n        ? [...prev[productId]]\n        : [emptyBatch(rowId)];\n      const index = rows.findIndex((row) => row.row_id === rowId);\n\n      if (index === -1) {\n        rows.push({ ...emptyBatch(rowId), ...patch });\n      } else {\n        rows[index] = { ...rows[index], ...patch };\n      }\n\n      return { ...prev, [productId]: rows };\n    });\n  };\n\n  const addBatch = (product: SimpleProductVariant) => {\n    rememberProduct(product);\n    const productId = String(product.id);\n\n    setDrafts((prev) => {\n      const rows = prev[productId]?.length\n        ? [...prev[productId]]\n        : [emptyBatch(`base-${productId}`)];\n      rows.push(emptyBatch(freshRowId()));\n      return { ...prev, [productId]: rows };\n    });\n  };\n\n  const removeBatch = (productId: string, rowId: string) => {\n    setDrafts((prev) => {\n      const rows = (prev[productId] || []).filter((row) => row.row_id !== rowId);\n      const next = { ...prev };\n      if (rows.length === 0) delete next[productId];\n      else next[productId] = rows;\n      return next;\n    });\n  };\n\n  const clearAll = () => {\n    const hasDraft = Object.values(drafts).some((rows) => rows.some((row) => (\n      row.cartons > 0 || row.loose_packs > 0 || row.batch_number || row.production_date || row.expiry_date\n    )));\n    if (hasDraft || referenceId || notes) setIsConfirmClearOpen(true);\n  };\n\n  const clearStoredRequestIdentity = () => {\n    localStorage.removeItem(`wanasah_inbound_request_id_${locationId}`);\n    localStorage.removeItem(`wanasah_inbound_request_fp_${locationId}`);\n  };\n\n  const confirmClear = () => {\n    setDrafts({});\n    setDraftProducts({});\n    setReferenceId("");\n    setNotes("");\n    localStorage.removeItem("inbound_batch_drafts_v2");\n    localStorage.removeItem("inbound_draft_products_v3");\n    localStorage.removeItem("inbound_draft_quantities");\n    localStorage.removeItem("inbound_draft_ref");\n    localStorage.removeItem("inbound_draft_notes");\n    clearStoredRequestIdentity();\n    setIsConfirmClearOpen(false);\n    toast.success("تم تصفير التوريدة والمسودة بالكامل بنجاح");\n  };\n\n  const handleSubmit = async () => {\n    const meaningfulEntries = Object.entries(drafts).filter(([, rows]) =>\n      rows.some((row) => row.cartons > 0 || row.loose_packs > 0)\n    );\n\n    if (meaningfulEntries.length === 0) {\n      toast.error("أضف كمية لصنف واحد على الأقل لتوريده.");\n      return;\n    }\n    if (!referenceId.trim()) {\n      toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد.");\n      return;\n    }\n\n    setSubmitting(true);\n    try {\n      // Resolve fresh metadata immediately before converting cartons -> packs.\n      // This prevents a long-lived draft from using an old packs_per_carton.\n      const requestedProductIds = meaningfulEntries.map(([productId]) => Number(productId));\n      const resolvedProducts = await authenticatedFetch(\n        "/product_variants/simple/resolve",\n        {\n          method: "POST",\n          body: JSON.stringify({ ids: requestedProductIds }),\n        }\n      );\n\n      if (!Array.isArray(resolvedProducts)) {\n        throw new Error("تعذر التحقق من بيانات أصناف التوريد.");\n      }\n\n      const freshProducts = new Map<string, SimpleProductVariant>(\n        (resolvedProducts as SimpleProductVariant[]).map((product) => [\n          String(product.id),\n          product,\n        ])\n      );\n\n      if (freshProducts.size !== requestedProductIds.length) {\n        throw new Error(\n          "يوجد صنف في مسودة التوريد لم يعد فعالاً أو لا يتبع شركتك. أزل الصنف ثم أعد المحاولة."\n        );\n      }\n\n      setDraftProducts((prev) => {\n        const next = { ...prev };\n        for (const product of resolvedProducts as SimpleProductVariant[]) {\n          next[String(product.id)] = product;\n        }\n        return next;\n      });\n\n      const itemsToSubmit: Array<{\n        product_variant_id: number;\n        quantity_packs: number;\n        batch_number: string;\n        production_date: string | null;\n        expiry_date: string;\n      }> = [];\n\n      const seenBatchKeys = new Set<string>();\n\n      for (const [productId, rows] of meaningfulEntries) {\n        const product = freshProducts.get(productId);\n        if (!product) {\n          throw new Error(`تعذر التحقق من الصنف رقم ${productId}.`);\n        }\n\n        const ppc = product.packs_per_carton || 1;\n\n        for (const row of rows) {\n          if (row.cartons === 0 && row.loose_packs === 0) continue;\n\n          if (row.loose_packs >= ppc) {\n            throw new Error(\n              `خطأ في (${product.name}): الحبات يجب أن تكون أقل من ${ppc}.`\n            );\n          }\n\n          const batchNumber = row.batch_number.trim();\n          if (!batchNumber) {\n            throw new Error(`أدخل رقم الدفعة للصنف (${product.name}).`);\n          }\n          if (!row.expiry_date) {\n            throw new Error(\n              `أدخل تاريخ الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`\n            );\n          }\n          if (row.production_date && row.production_date > row.expiry_date) {\n            throw new Error(\n              `تاريخ الإنتاج بعد الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`\n            );\n          }\n\n          const duplicateKey = `${product.id}|${batchNumber}`;\n          if (seenBatchKeys.has(duplicateKey)) {\n            throw new Error(\n              `الدفعة (${batchNumber}) مكررة للصنف (${product.name}). اجمع الكمية في سطر واحد.`\n            );\n          }\n          seenBatchKeys.add(duplicateKey);\n\n          itemsToSubmit.push({\n            product_variant_id: product.id,\n            quantity_packs: toTotalPacks(row.cartons, row.loose_packs, ppc),\n            batch_number: batchNumber,\n            production_date: row.production_date || null,\n            expiry_date: row.expiry_date,\n          });\n        }\n      }\n\n      itemsToSubmit.sort((a, b) => (\n        a.product_variant_id - b.product_variant_id\n        || a.batch_number.localeCompare(b.batch_number)\n      ));\n\n      const businessPayload = {\n        location_id: locationId,\n        reference_id: referenceId.trim(),\n        notes,\n        items: itemsToSubmit,\n      };\n\n      // Same business payload after timeout => same UUID. Any material edit => new UUID.\n      const requestIdKey = `wanasah_inbound_request_id_${locationId}`;\n      const fingerprintKey = `wanasah_inbound_request_fp_${locationId}`;\n      const fingerprint = JSON.stringify(businessPayload);\n\n      let requestId = localStorage.getItem(requestIdKey);\n      const previousFingerprint = localStorage.getItem(fingerprintKey);\n\n      if (!requestId || previousFingerprint !== fingerprint) {\n        requestId = crypto.randomUUID();\n        localStorage.setItem(requestIdKey, requestId);\n        localStorage.setItem(fingerprintKey, fingerprint);\n      }\n\n      const data = await authenticatedFetch("/warehouse/inbound", {\n        method: "POST",\n        body: JSON.stringify({ request_id: requestId, ...businessPayload }),\n      });\n\n      toast.success(data?.message || "تم استلام البضاعة وتوثيقها بنجاح ✅");\n      setDrafts({});\n      setDraftProducts({});\n      setReferenceId("");\n      setNotes("");\n      localStorage.removeItem("inbound_batch_drafts_v2");\n      localStorage.removeItem("inbound_draft_products_v3");\n      localStorage.removeItem("inbound_draft_quantities");\n      localStorage.removeItem("inbound_draft_ref");\n      localStorage.removeItem("inbound_draft_notes");\n      clearStoredRequestIdentity();\n      await onSuccess();\n    } catch (e: any) {\n      toast.error(e?.message || "فشل توثيق التوريد.");\n    } finally {\n      setSubmitting(false);\n    }\n  };\n\n  return (\n    <div className="flex flex-col h-full flex-1 min-h-0 pt-1 animate-in fade-in duration-300">\n      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm pb-2 flex-1 min-h-0">\n        <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">\n          <FilePlus className="w-4 h-4" /> توريد بضاعة (الاستلام المخزني)\n        </div>\n\n        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-white mt-5 border-b border-slate-100">\n          <table className="w-full text-sm min-w-[1100px]">\n            <thead className="sticky top-0 z-10 bg-slate-50 shadow-sm border-b border-slate-200">\n              <tr className="text-slate-500 text-xs uppercase text-right">\n                <th className="py-3 px-4 font-extrabold w-[24%]">\n                  <div className="flex items-center gap-3">\n                    <span>المنتج</span>\n                    <div className="relative font-normal flex-1">\n                      <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />\n                      <input\n                        type="search"\n                        placeholder="ابحث عن صنف أو SKU..."\n                        value={catalogSearchInput}\n                        onChange={(e) => setCatalogSearchInput(e.target.value)}\n                        className="w-full pl-3 pr-9 py-1.5 text-xs border border-slate-200 rounded-lg outline-none focus:border-emerald-400 bg-white shadow-sm"\n                      />\n                    </div>\n                  </div>\n                </th>\n                <th className="py-3 px-4 font-extrabold">الدفعة والصلاحية</th>\n                <th className="py-3 px-4 font-extrabold text-center">الكمية (كرتونة / حبة)</th>\n                <th className="py-3 px-4 w-28 text-center">\n                  <button onClick={clearAll} className="text-[10px] font-bold text-red-500 hover:text-red-700 flex items-center gap-1 bg-red-50 hover:bg-red-100 px-2.5 py-1.5 rounded-md border border-red-100 mx-auto">\n                    <Eraser className="w-3.5 h-3.5" /> تصفير\n                  </button>\n                </th>\n              </tr>\n            </thead>\n            <tbody className="divide-y divide-slate-100">\n              {catalogItems.length === 0 ? (\n                <tr><td colSpan={4} className="text-center py-12 text-slate-400">{catalogLoading ? "جارٍ تحميل الكتالوج..." : "لا توجد منتجات مطابقة"}</td></tr>\n              ) : catalogItems.map((product) => {\n                const productId = String(product.id);\n                const rows = drafts[productId]?.length\n                  ? drafts[productId]\n                  : [emptyBatch(`base-${productId}`)];\n                const ppc = product.packs_per_carton || 1;\n\n                return rows.map((row, index) => {\n                  const hasQty = row.cartons > 0 || row.loose_packs > 0;\n                  const looseError = row.loose_packs >= ppc;\n                  return (\n                    <tr key={`${productId}:${row.row_id}`} className={hasQty ? "bg-emerald-50/35" : "hover:bg-slate-50"}>\n                      <td className="py-2 px-4 align-top">\n                        {index === 0 ? (\n                          <>\n                            <div className="font-bold text-slate-800">{product.name}</div>\n                            <div className="text-[10px] text-slate-400 mt-1">SKU: {product.sku || "—"} • التعبئة: {ppc} حبة</div>\n                          </>\n                        ) : (\n                          <div className="text-xs font-bold text-emerald-700">دفعة إضافية لنفس الصنف</div>\n                        )}\n                      </td>\n\n                      <td className="py-2 px-4 align-top">\n                        <div className="grid grid-cols-3 gap-2">\n                          <input\n                            value={row.batch_number}\n                            onChange={(e) => updateBatch(product, row.row_id, { batch_number: e.target.value })}\n                            placeholder="رقم الدفعة *"\n                            className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold outline-none focus:border-emerald-400"\n                          />\n                          <div>\n                            <label className="block text-[9px] text-slate-400 mb-0.5">الإنتاج (اختياري)</label>\n                            <input\n                              type="date"\n                              value={row.production_date}\n                              onChange={(e) => updateBatch(product, row.row_id, { production_date: e.target.value })}\n                              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-emerald-400"\n                            />\n                          </div>\n                          <div>\n                            <label className="block text-[9px] text-slate-400 mb-0.5">الصلاحية *</label>\n                            <input\n                              type="date"\n                              value={row.expiry_date}\n                              onChange={(e) => updateBatch(product, row.row_id, { expiry_date: e.target.value })}\n                              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-emerald-400"\n                            />\n                          </div>\n                        </div>\n                      </td>\n\n                      <td className="py-2 px-4 align-top">\n                        <div className="flex items-center justify-center gap-6">\n                          <div className="flex flex-col items-center gap-1">\n                            <span className="text-[10px] font-bold text-slate-500">كراتين</span>\n                            <QuantityInput\n                              value={row.cartons}\n                              onChange={(value) => updateBatch(product, row.row_id, { cartons: value })}\n                            />\n                          </div>\n                          <div className="flex flex-col items-center gap-1">\n                            <span className={`text-[10px] font-bold ${looseError ? "text-red-600" : "text-slate-500"}`}>حبات</span>\n                            <QuantityInput\n                              value={row.loose_packs}\n                              onChange={(value) => updateBatch(product, row.row_id, { loose_packs: value })}\n                              isError={looseError}\n                            />\n                          </div>\n                        </div>\n                      </td>\n\n                      <td className="py-2 px-4 align-top">\n                        <div className="flex items-center justify-center gap-1 mt-4">\n                          {index === 0 && (\n                            <button\n                              type="button"\n                              onClick={() => addBatch(product)}\n                              title="إضافة دفعة أخرى لنفس الصنف"\n                              className="p-2 rounded-lg text-emerald-600 bg-emerald-50 hover:bg-emerald-100 border border-emerald-100"\n                            >\n                              <Plus className="w-4 h-4" />\n                            </button>\n                          )}\n                          {index > 0 && (\n                            <button\n                              type="button"\n                              onClick={() => removeBatch(productId, row.row_id)}\n                              title="حذف هذه الدفعة"\n                              className="p-2 rounded-lg text-red-500 bg-red-50 hover:bg-red-100 border border-red-100"\n                            >\n                              <Trash2 className="w-4 h-4" />\n                            </button>\n                          )}\n                        </div>\n                      </td>\n                    </tr>\n                  );\n                });\n              })}\n            </tbody>\n          </table>\n        </div>\n\n        {(catalogHistory.length > 0 || !!catalogNextCursor) && (\n          <div className="flex items-center justify-between px-5 py-2.5 border-b border-slate-200 bg-slate-50">\n            <span className="text-[11px] font-bold text-slate-500">\n              صفحة {catalogHistory.length + 1}\n              {catalogTotal !== null ? ` • ${catalogTotal} صنف` : ""}\n            </span>\n            <div className="flex gap-2">\n              <button\n                type="button"\n                onClick={() => {\n                  if (catalogHistory.length === 0) return;\n                  const previous = catalogHistory[catalogHistory.length - 1] ?? null;\n                  setCatalogHistory((prev) => prev.slice(0, -1));\n                  setCatalogCursor(previous);\n                }}\n                disabled={catalogHistory.length === 0 || catalogLoading}\n                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"\n                title="الصفحة السابقة"\n              >\n                <ChevronRight className="w-4 h-4" />\n              </button>\n              <button\n                type="button"\n                onClick={() => {\n                  if (!catalogNextCursor) return;\n                  setCatalogHistory((prev) => [...prev, catalogCursor]);\n                  setCatalogCursor(catalogNextCursor);\n                }}\n                disabled={!catalogNextCursor || catalogLoading}\n                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"\n                title="الصفحة التالية"\n              >\n                <ChevronLeft className="w-4 h-4" />\n              </button>\n            </div>\n          </div>\n        )}\n\n        <div className="p-3 bg-slate-50 rounded-b-2xl">\n          <div className="flex flex-col md:flex-row items-center gap-3">\n            <div className="flex-1 w-full grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">\n              <div className="relative">\n                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">رقم الفاتورة / المرجع <span className="text-red-500">*</span></span>\n                <input\n                  value={referenceId}\n                  onChange={(e) => setReferenceId(e.target.value)}\n                  placeholder="مثال: INV-2026-001"\n                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"\n                />\n              </div>\n              <div className="relative">\n                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">ملاحظات (اختياري)</span>\n                <input\n                  value={notes}\n                  onChange={(e) => setNotes(e.target.value)}\n                  placeholder="أي ملاحظات إضافية..."\n                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 outline-none"\n                />\n              </div>\n            </div>\n            <div className="w-full md:w-auto mt-2 md:mt-0">\n              <button\n                onClick={handleSubmit}\n                disabled={submitting}\n                className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-90 text-white px-6 py-2.5 rounded-xl text-sm font-black shadow-md active:scale-[0.98] w-full disabled:opacity-50"\n              >\n                {submitting ? "جارٍ التوثيق..." : "✓ توثيق الاستلام"}\n              </button>\n            </div>\n          </div>\n        </div>\n\n        {isConfirmClearOpen && (\n          <Modal\n            isOpen={isConfirmClearOpen}\n            onClose={() => setIsConfirmClearOpen(false)}\n            title="⚠️ تأكيد التصفير"\n            footer={\n              <div className="flex gap-2 w-full">\n                <button onClick={() => setIsConfirmClearOpen(false)} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl">إلغاء</button>\n                <button autoFocus onClick={confirmClear} className="flex-1 px-6 py-2 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl">نعم، تصفير التوريدة</button>\n              </div>\n            }\n          >\n            <p className="text-sm text-slate-600 leading-relaxed">سيتم حذف جميع الكميات وبيانات الدفعات والمرجع والملاحظات المحفوظة محليًا.</p>\n          </Modal>\n        )}\n      </div>\n    </div>\n  );\n}\n'


def normalize(data: bytes) -> str:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def _function_span(text: str, func_name: str) -> tuple[int, int]:
    tree = ast.parse(text)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == func_name:
            target = node
            break
    if target is None:
        raise RuntimeError(f"function not found: {func_name}")

    starts = [target.lineno] + [d.lineno for d in target.decorator_list]
    return min(starts), target.end_lineno


def replace_function(text: str, func_name: str, new_code: str) -> str:
    start, end = _function_span(text, func_name)
    lines = text.splitlines(keepends=True)
    replacement = new_code.rstrip() + "\n"
    return "".join(lines[:start - 1]) + replacement + "".join(lines[end:])


def remove_function(text: str, func_name: str, comment: str) -> str:
    start, end = _function_span(text, func_name)
    lines = text.splitlines(keepends=True)
    return "".join(lines[:start - 1]) + comment.rstrip() + "\n" + "".join(lines[end:])


VARIANT_CURSOR_HELPERS = 'def _variant_cursor_scope_hash(scope: str) -> str:\n    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]\n\n\ndef _encode_variant_cursor(\n    *,\n    kind: str,\n    variant_name: str,\n    variant_id: int,\n    scope: str,\n) -> str:\n    raw = json.dumps(\n        {\n            "v": 1,\n            "kind": kind,\n            "scope": _variant_cursor_scope_hash(scope),\n            "name": variant_name,\n            "id": int(variant_id),\n        },\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n    ).encode("utf-8")\n    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")\n\n\ndef _decode_variant_cursor(\n    cursor: str,\n    *,\n    expected_kind: str,\n    expected_scope: str,\n) -> tuple[str, int]:\n    try:\n        padding = "=" * (-len(cursor) % 4)\n        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))\n        payload = json.loads(raw.decode("utf-8"))\n\n        if (\n            not isinstance(payload, dict)\n            or payload.get("v") != 1\n            or payload.get("kind") != expected_kind\n            or payload.get("scope")\n            != _variant_cursor_scope_hash(expected_scope)\n        ):\n            raise ValueError\n\n        variant_name = payload.get("name")\n        variant_id = payload.get("id")\n\n        if (\n            not isinstance(variant_name, str)\n            or not variant_name\n            or len(variant_name) > 200\n            or type(variant_id) is not int\n            or variant_id <= 0\n        ):\n            raise ValueError\n\n        return variant_name, variant_id\n    except Exception as exc:\n        raise HTTPException(\n            status_code=400,\n            detail="Cursor الصفحة غير صالح أو لا يطابق معايير الاستعلام الحالي.",\n        ) from exc\n\n\n'
INVENTORY_FUNC = '@router.get(\n    "/warehouse/inventory/cursor",\n    response_model=WarehouseInventoryCursorPage,\n    status_code=200,\n)\nasync def get_warehouse_inventory(\n    location_id: int,\n    cursor: Optional[str] = Query(default=None, max_length=1024),\n    limit: int = Query(default=50, ge=1, le=200),\n    search: Optional[str] = Query(default=None, min_length=2, max_length=100),\n    only_alerts: bool = False,\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n\n    try:\n        stmt_location = select(InventoryLocation.id).filter_by(\n            id=location_id,\n            company_id=company_id,\n            location_type=\'WAREHOUSE\',\n            is_active=True,\n        )\n        if (await db.execute(stmt_location)).scalar_one_or_none() is None:\n            raise HTTPException(\n                status_code=404,\n                detail="المستودع غير موجود أو لا يتبع شركتك.",\n            )\n\n        as_of_date = await get_company_local_date(db, company_id)\n\n        clean_search = (search or "").strip().lower()\n        if clean_search and len(clean_search) < 2:\n            raise HTTPException(\n                status_code=400,\n                detail="البحث في المخزون يتطلب حرفين على الأقل.",\n            )\n\n        search_condition = None\n        if clean_search:\n            like_pattern = f"%{_escape_like(clean_search)}%"\n            search_condition = or_(\n                func.lower(ProductVariant.variant_name).like(\n                    like_pattern,\n                    escape="\\\\",\n                ),\n                func.lower(\n                    func.coalesce(ProductVariant.sku, "")\n                ).like(\n                    like_pattern,\n                    escape="\\\\",\n                ),\n            )\n\n        # الرصيد الفيزيائي في المستودع يجعل الصنف مرئياً حتى لو تم تعطيله،\n        # لأن إخفاء صنف متوقف وله بضاعة فعلية يخرق معنى الجرد الحي.\n        warehouse_stock_exists = (\n            select(InventoryBalance.id)\n            .filter(\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.location_id == location_id,\n                InventoryBalance.product_variant_id == ProductVariant.id,\n                InventoryBalance.on_hand_quantity > 0,\n            )\n            .correlate(ProductVariant)\n            .exists()\n        )\n\n        latest_source_for_candidate_vehicle = (\n            select(DispatchRoute.source_location_id)\n            .filter(\n                DispatchRoute.company_id == company_id,\n                DispatchRoute.vehicle_id == InventoryLocation.vehicle_id,\n            )\n            .order_by(DispatchRoute.id.desc())\n            .limit(1)\n            .correlate(InventoryLocation)\n            .scalar_subquery()\n        )\n\n        vehicle_stock_exists = (\n            select(InventoryBalance.id)\n            .join(\n                InventoryLocation,\n                and_(\n                    InventoryLocation.company_id\n                    == InventoryBalance.company_id,\n                    InventoryLocation.id\n                    == InventoryBalance.location_id,\n                ),\n            )\n            .filter(\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.product_variant_id == ProductVariant.id,\n                InventoryBalance.stock_status == \'AVAILABLE\',\n                InventoryBalance.on_hand_quantity > 0,\n                InventoryLocation.company_id == company_id,\n                InventoryLocation.location_type == \'VEHICLE\',\n                InventoryLocation.is_active.is_(True),\n                InventoryLocation.vehicle_id.isnot(None),\n                latest_source_for_candidate_vehicle == location_id,\n            )\n            .correlate(ProductVariant)\n            .exists()\n        )\n\n        visible_condition = or_(\n            ProductVariant.is_active.is_(True),\n            warehouse_stock_exists,\n            vehicle_stock_exists,\n        )\n\n        batch_is_sellable = and_(\n            ProductBatch.is_active.is_(True),\n            or_(\n                ProductBatch.production_date.is_(None),\n                ProductBatch.production_date <= as_of_date,\n            ),\n            ProductBatch.expiry_date >= as_of_date,\n        )\n\n        alert_inventory_subq = None\n        if only_alerts or cursor is None:\n            alert_inventory_subq = (\n                select(\n                    InventoryBalance.product_variant_id,\n                    func.sum(\n                        InventoryBalance.on_hand_quantity\n                    ).label("alert_on_hand"),\n                    func.sum(\n                        InventoryBalance.reserved_quantity\n                    ).label("alert_reserved"),\n                )\n                .join(\n                    ProductBatch,\n                    and_(\n                        ProductBatch.company_id\n                        == InventoryBalance.company_id,\n                        ProductBatch.product_variant_id\n                        == InventoryBalance.product_variant_id,\n                        ProductBatch.id == InventoryBalance.batch_id,\n                    ),\n                )\n                .filter(\n                    InventoryBalance.company_id == company_id,\n                    InventoryBalance.location_id == location_id,\n                    InventoryBalance.stock_status == \'AVAILABLE\',\n                    batch_is_sellable,\n                )\n                .group_by(InventoryBalance.product_variant_id)\n                .subquery()\n            )\n\n        def _build_alert_variants_stmt():\n            if alert_inventory_subq is None:\n                raise RuntimeError(\n                    "Alert inventory subquery was not initialized."\n                )\n\n            free_expression = (\n                func.coalesce(alert_inventory_subq.c.alert_on_hand, 0)\n                - func.coalesce(alert_inventory_subq.c.alert_reserved, 0)\n            )\n\n            return (\n                select(\n                    ProductVariant.id,\n                    ProductVariant.variant_name,\n                )\n                .join(\n                    InventoryStockPolicy,\n                    and_(\n                        InventoryStockPolicy.company_id\n                        == ProductVariant.company_id,\n                        InventoryStockPolicy.product_variant_id\n                        == ProductVariant.id,\n                        InventoryStockPolicy.location_id == location_id,\n                        InventoryStockPolicy.is_active.is_(True),\n                    ),\n                )\n                .outerjoin(\n                    alert_inventory_subq,\n                    alert_inventory_subq.c.product_variant_id\n                    == ProductVariant.id,\n                )\n                .filter(\n                    ProductVariant.company_id == company_id,\n                    ProductVariant.is_active.is_(True),\n                    InventoryStockPolicy.minimum_quantity > 0,\n                    free_expression\n                    <= InventoryStockPolicy.minimum_quantity,\n                )\n            )\n\n        if only_alerts:\n            candidate_stmt = _build_alert_variants_stmt()\n        else:\n            candidate_stmt = select(\n                ProductVariant.id,\n                ProductVariant.variant_name,\n            ).filter(\n                ProductVariant.company_id == company_id,\n                visible_condition,\n            )\n\n        if search_condition is not None:\n            candidate_stmt = candidate_stmt.filter(search_condition)\n\n        total = None\n        if cursor is None:\n            count_source = (\n                candidate_stmt\n                .order_by(None)\n                .subquery()\n            )\n            total = int(\n                (\n                    await db.execute(\n                        select(func.count()).select_from(count_source)\n                    )\n                ).scalar_one()\n            )\n\n        scope = (\n            f"inventory|{company_id}|{location_id}|"\n            f"{clean_search}|{int(only_alerts)}"\n        )\n        if cursor is not None:\n            cursor_name, cursor_id = _decode_variant_cursor(\n                cursor,\n                expected_kind="warehouse-inventory",\n                expected_scope=scope,\n            )\n            candidate_stmt = candidate_stmt.filter(\n                or_(\n                    ProductVariant.variant_name > cursor_name,\n                    and_(\n                        ProductVariant.variant_name == cursor_name,\n                        ProductVariant.id > cursor_id,\n                    ),\n                )\n            )\n\n        candidate_rows = (\n            await db.execute(\n                candidate_stmt\n                .order_by(\n                    ProductVariant.variant_name.asc(),\n                    ProductVariant.id.asc(),\n                )\n                .limit(limit + 1)\n            )\n        ).all()\n\n        has_more = len(candidate_rows) > limit\n        page_candidates = candidate_rows[:limit]\n        page_variant_ids = [int(row.id) for row in page_candidates]\n\n        alert_count = None\n        alert_samples: list[str] = []\n        if cursor is None and not clean_search and not only_alerts:\n            alert_stmt = _build_alert_variants_stmt().order_by(\n                ProductVariant.variant_name.asc(),\n                ProductVariant.id.asc(),\n            )\n\n            alert_count = int(\n                (\n                    await db.execute(\n                        select(func.count()).select_from(\n                            alert_stmt.order_by(None).subquery()\n                        )\n                    )\n                ).scalar_one()\n            )\n\n            if alert_count > 0:\n                alert_samples = list(\n                    (\n                        await db.execute(\n                            alert_stmt.with_only_columns(\n                                ProductVariant.variant_name\n                            ).limit(3)\n                        )\n                    ).scalars().all()\n                )\n\n        if not page_variant_ids:\n            return {\n                "items": [],\n                "next_cursor": None,\n                "has_more": False,\n                "total": total,\n                "alert_count": alert_count,\n                "alert_samples": alert_samples,\n            }\n\n        warehouse_available_subq = (\n            select(\n                InventoryBalance.product_variant_id,\n                func.sum(\n                    InventoryBalance.on_hand_quantity\n                ).label(\'warehouse_on_hand\'),\n                func.sum(\n                    InventoryBalance.reserved_quantity\n                ).label(\'warehouse_reserved\'),\n                func.sum(\n                    case(\n                        (\n                            batch_is_sellable,\n                            InventoryBalance.on_hand_quantity,\n                        ),\n                        else_=0,\n                    )\n                ).label(\'warehouse_sellable_on_hand\'),\n                func.sum(\n                    case(\n                        (\n                            batch_is_sellable,\n                            InventoryBalance.reserved_quantity,\n                        ),\n                        else_=0,\n                    )\n                ).label(\'warehouse_sellable_reserved\'),\n            )\n            .join(\n                ProductBatch,\n                and_(\n                    ProductBatch.company_id\n                    == InventoryBalance.company_id,\n                    ProductBatch.product_variant_id\n                    == InventoryBalance.product_variant_id,\n                    ProductBatch.id == InventoryBalance.batch_id,\n                ),\n            )\n            .filter(\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.location_id == location_id,\n                InventoryBalance.stock_status == \'AVAILABLE\',\n                InventoryBalance.product_variant_id.in_(\n                    page_variant_ids\n                ),\n            )\n            .group_by(InventoryBalance.product_variant_id)\n            .subquery()\n        )\n\n        warehouse_damaged_subq = (\n            select(\n                InventoryBalance.product_variant_id,\n                func.sum(\n                    InventoryBalance.on_hand_quantity\n                ).label(\'damaged_packs\'),\n            )\n            .filter(\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.location_id == location_id,\n                InventoryBalance.stock_status == \'DAMAGED\',\n                InventoryBalance.product_variant_id.in_(\n                    page_variant_ids\n                ),\n            )\n            .group_by(InventoryBalance.product_variant_id)\n            .subquery()\n        )\n\n        latest_source_for_vehicle = (\n            select(DispatchRoute.source_location_id)\n            .filter(\n                DispatchRoute.company_id == company_id,\n                DispatchRoute.vehicle_id == InventoryLocation.vehicle_id,\n            )\n            .order_by(DispatchRoute.id.desc())\n            .limit(1)\n            .correlate(InventoryLocation)\n            .scalar_subquery()\n        )\n\n        vehicle_inventory_subq = (\n            select(\n                InventoryBalance.product_variant_id,\n                func.sum(\n                    InventoryBalance.on_hand_quantity\n                ).label(\'vehicle_packs\'),\n            )\n            .join(\n                InventoryLocation,\n                and_(\n                    InventoryLocation.company_id\n                    == InventoryBalance.company_id,\n                    InventoryLocation.id\n                    == InventoryBalance.location_id,\n                ),\n            )\n            .filter(\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.stock_status == \'AVAILABLE\',\n                InventoryBalance.product_variant_id.in_(\n                    page_variant_ids\n                ),\n                InventoryLocation.company_id == company_id,\n                InventoryLocation.location_type == \'VEHICLE\',\n                InventoryLocation.is_active.is_(True),\n                InventoryLocation.vehicle_id.isnot(None),\n                latest_source_for_vehicle == location_id,\n            )\n            .group_by(InventoryBalance.product_variant_id)\n            .subquery()\n        )\n\n        policy_subq = (\n            select(\n                InventoryStockPolicy.product_variant_id,\n                InventoryStockPolicy.minimum_quantity,\n            )\n            .filter(\n                InventoryStockPolicy.company_id == company_id,\n                InventoryStockPolicy.location_id == location_id,\n                InventoryStockPolicy.is_active.is_(True),\n                InventoryStockPolicy.product_variant_id.in_(\n                    page_variant_ids\n                ),\n            )\n            .subquery()\n        )\n\n        stmt = (\n            select(\n                ProductVariant,\n                warehouse_available_subq.c.warehouse_on_hand,\n                warehouse_available_subq.c.warehouse_reserved,\n                warehouse_available_subq.c.warehouse_sellable_on_hand,\n                warehouse_available_subq.c.warehouse_sellable_reserved,\n                warehouse_damaged_subq.c.damaged_packs,\n                vehicle_inventory_subq.c.vehicle_packs,\n                policy_subq.c.minimum_quantity,\n            )\n            .outerjoin(\n                warehouse_available_subq,\n                warehouse_available_subq.c.product_variant_id\n                == ProductVariant.id,\n            )\n            .outerjoin(\n                warehouse_damaged_subq,\n                warehouse_damaged_subq.c.product_variant_id\n                == ProductVariant.id,\n            )\n            .outerjoin(\n                vehicle_inventory_subq,\n                vehicle_inventory_subq.c.product_variant_id\n                == ProductVariant.id,\n            )\n            .outerjoin(\n                policy_subq,\n                policy_subq.c.product_variant_id\n                == ProductVariant.id,\n            )\n            .filter(\n                ProductVariant.company_id == company_id,\n                ProductVariant.id.in_(page_variant_ids),\n            )\n            .order_by(\n                ProductVariant.variant_name.asc(),\n                ProductVariant.id.asc(),\n            )\n        )\n\n        rows = (await db.execute(stmt)).all()\n\n        result = []\n        for (\n            variant,\n            warehouse_on_hand,\n            warehouse_reserved,\n            warehouse_sellable_on_hand,\n            warehouse_sellable_reserved,\n            damaged_packs,\n            vehicle_packs,\n            minimum_quantity,\n        ) in rows:\n            on_hand = int(warehouse_on_hand or 0)\n            reserved = int(warehouse_reserved or 0)\n\n            sellable_on_hand = (\n                int(warehouse_sellable_on_hand or 0)\n                if variant.is_active\n                else 0\n            )\n            sellable_reserved = (\n                int(warehouse_sellable_reserved or 0)\n                if variant.is_active\n                else 0\n            )\n\n            free_packs = sellable_on_hand - sellable_reserved\n            blocked_packs = on_hand - sellable_on_hand\n            vehicle_total = int(vehicle_packs or 0)\n            damaged = int(damaged_packs or 0)\n\n            if free_packs < 0:\n                raise RuntimeError(\n                    f"Inventory invariant violated for "\n                    f"product_variant_id={variant.id}: "\n                    "sellable reserved quantity exceeds sellable on-hand."\n                )\n            if blocked_packs < 0:\n                raise RuntimeError(\n                    f"Inventory invariant violated for "\n                    f"product_variant_id={variant.id}: "\n                    "sellable stock exceeds physical AVAILABLE stock."\n                )\n\n            ppc = int(variant.packs_per_carton or 1)\n            total_physical_available = on_hand + vehicle_total\n\n            result.append({\n                "id": variant.id,\n                "name": variant.variant_name,\n                "sku": variant.sku,\n                "packs_per_carton": ppc,\n                "available_packs": free_packs,\n                "reserved_packs": reserved,\n                "blocked_packs": blocked_packs,\n                "total_packs": total_physical_available,\n                "damaged_packs": damaged,\n                "available_cartons": free_packs // ppc,\n                "available_loose_packs": free_packs % ppc,\n                "min_threshold": int(minimum_quantity or 0),\n            })\n\n        if len(result) != len(page_variant_ids):\n            raise RuntimeError(\n                "Inventory page identity invariant violated."\n            )\n\n        next_cursor = None\n        if has_more:\n            last_candidate = page_candidates[-1]\n            next_cursor = _encode_variant_cursor(\n                kind="warehouse-inventory",\n                variant_name=str(last_candidate.variant_name),\n                variant_id=int(last_candidate.id),\n                scope=scope,\n            )\n\n        return {\n            "items": result,\n            "next_cursor": next_cursor,\n            "has_more": has_more,\n            "total": total,\n            "alert_count": alert_count,\n            "alert_samples": alert_samples,\n        }\n\n    except HTTPException:\n        raise\n    except Exception as e:\n        logger.error(\n            f"خطأ في Cursor المخزون الحي: {str(e)}",\n            exc_info=True,\n        )\n        raise HTTPException(\n            status_code=500,\n            detail="حدث خطأ داخلي أثناء جلب صفحة المخزون.",\n        )\n'
CATALOG_FUNC = '@router.get(\n    "/product_variants/simple/cursor",\n    response_model=SimpleProductVariantCursorPage,\n    status_code=200,\n)\nasync def get_simple_product_variants(\n    cursor: Optional[str] = Query(default=None, max_length=1024),\n    limit: int = Query(default=50, ge=1, le=200),\n    search: Optional[str] = Query(default=None, min_length=2, max_length=100),\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n    clean_search = (search or "").strip().lower()\n\n    if clean_search and len(clean_search) < 2:\n        raise HTTPException(\n            status_code=400,\n            detail="البحث في كتالوج المنتجات يتطلب حرفين على الأقل.",\n        )\n\n    stmt = select(\n        ProductVariant.id,\n        ProductVariant.variant_name,\n        ProductVariant.sku,\n        ProductVariant.packs_per_carton,\n    ).filter(\n        ProductVariant.company_id == company_id,\n        ProductVariant.is_active.is_(True),\n    )\n\n    if clean_search:\n        like_pattern = f"%{_escape_like(clean_search)}%"\n        stmt = stmt.filter(\n            or_(\n                func.lower(ProductVariant.variant_name).like(\n                    like_pattern,\n                    escape="\\\\",\n                ),\n                func.lower(\n                    func.coalesce(ProductVariant.sku, "")\n                ).like(\n                    like_pattern,\n                    escape="\\\\",\n                ),\n            )\n        )\n\n    total = None\n    if cursor is None:\n        total = int(\n            (\n                await db.execute(\n                    select(func.count()).select_from(\n                        stmt.with_only_columns(\n                            ProductVariant.id,\n                            maintain_column_froms=True,\n                        ).order_by(None).subquery()\n                    )\n                )\n            ).scalar_one()\n        )\n\n    scope = f"catalog|{company_id}|{clean_search}"\n    if cursor is not None:\n        cursor_name, cursor_id = _decode_variant_cursor(\n            cursor,\n            expected_kind="product-catalog",\n            expected_scope=scope,\n        )\n        stmt = stmt.filter(\n            or_(\n                ProductVariant.variant_name > cursor_name,\n                and_(\n                    ProductVariant.variant_name == cursor_name,\n                    ProductVariant.id > cursor_id,\n                ),\n            )\n        )\n\n    rows = (\n        await db.execute(\n            stmt.order_by(\n                ProductVariant.variant_name.asc(),\n                ProductVariant.id.asc(),\n            ).limit(limit + 1)\n        )\n    ).all()\n\n    has_more = len(rows) > limit\n    page_rows = rows[:limit]\n\n    next_cursor = None\n    if has_more and page_rows:\n        last_row = page_rows[-1]\n        next_cursor = _encode_variant_cursor(\n            kind="product-catalog",\n            variant_name=str(last_row.variant_name),\n            variant_id=int(last_row.id),\n            scope=scope,\n        )\n\n    return {\n        "items": [\n            {\n                "id": int(row.id),\n                "name": row.variant_name,\n                "sku": row.sku,\n                "packs_per_carton": int(\n                    row.packs_per_carton or 1\n                ),\n            }\n            for row in page_rows\n        ],\n        "next_cursor": next_cursor,\n        "has_more": has_more,\n        "total": total,\n    }\n'
RESOLVE_FUNC = '@router.post(\n    "/product_variants/simple/resolve",\n    response_model=List[SimpleProductVariantItem],\n    status_code=200,\n)\nasync def resolve_simple_product_variants(\n    payload: ProductVariantResolveRequest,\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n    requested_ids = sorted(set(int(value) for value in payload.ids))\n\n    rows = (\n        await db.execute(\n            select(\n                ProductVariant.id,\n                ProductVariant.variant_name,\n                ProductVariant.sku,\n                ProductVariant.packs_per_carton,\n            )\n            .filter(\n                ProductVariant.company_id == company_id,\n                ProductVariant.is_active.is_(True),\n                ProductVariant.id.in_(requested_ids),\n            )\n            .order_by(\n                ProductVariant.variant_name.asc(),\n                ProductVariant.id.asc(),\n            )\n        )\n    ).all()\n\n    return [\n        {\n            "id": int(row.id),\n            "name": row.variant_name,\n            "sku": row.sku,\n            "packs_per_carton": int(row.packs_per_carton or 1),\n        }\n        for row in rows\n    ]\n'


def patch_models(text: str) -> str:
    if "ix_product_variant_company_name_id" in text:
        raise RuntimeError(
            "models.py: ProductVariant cursor index موجود مسبقاً؛ لا تعِد تشغيل هذا الباتش."
        )

    marker = """        UniqueConstraint('company_id', 'sku', name='uq_company_sku'),
        UniqueConstraint('company_id', 'id', name='uq_product_variants_company_id'),
"""
    replacement = marker + (
        "        Index('ix_product_variant_company_name_id', "
        "'company_id', 'variant_name', 'id'),\n"
    )
    text = replace_once(text, marker, replacement, "models ProductVariant cursor index")

    parsed = ast.parse(text)
    if text.count("ix_product_variant_company_name_id") != 1:
        raise RuntimeError("models.py: ProductVariant cursor index must exist exactly once.")

    # Guard against the corruption we already repaired.
    for token in (
        "name='chk_inv_movement_shape'",
        "name='chk_inv_movement_physical_preserves_status'",
        "name='chk_inv_movement_attempt_requires_stocktake'",
        "ix_inv_movement_company_created_id",
        "chk_work_session_settlement_requires_end",
        "uq_vehicle_recon_work_session",
        "class OperationIdempotency(Base):",
    ):
        if token not in text:
            raise RuntimeError(f"models.py: required hardened marker missing: {token}")

    return text


def patch_schemas(text: str) -> str:
    if "class WarehouseInventoryCursorPage(BaseModel):" in text:
        raise RuntimeError("schemas.py: inventory cursor schemas موجودة مسبقاً.")

    if "    blocked_packs: int\n" not in text:
        text = replace_once(
            text,
            "    available_packs: int\n    reserved_packs: int\n    total_packs: int\n",
            "    available_packs: int\n    reserved_packs: int\n    blocked_packs: int\n    total_packs: int\n",
            "schemas blocked_packs",
        )

    text = replace_once(
        text,
        "class WarehouseLedgerItem(BaseModel):\n",
        """class WarehouseInventoryCursorPage(BaseModel):
    items: List[WarehouseInventoryItem]
    next_cursor: Optional[str] = None
    has_more: bool
    total: Optional[int] = None
    alert_count: Optional[int] = None
    alert_samples: List[str] = Field(default_factory=list)


class WarehouseLedgerItem(BaseModel):
""",
        "schemas inventory cursor page",
    )

    old_simple = """class SimpleProductVariantItem(BaseModel):
    id: int
    name: str
    packs_per_carton: int

"""
    new_simple = """class SimpleProductVariantItem(BaseModel):
    id: int
    name: str
    sku: Optional[str] = None
    packs_per_carton: int


class SimpleProductVariantCursorPage(BaseModel):
    items: List[SimpleProductVariantItem]
    next_cursor: Optional[str] = None
    has_more: bool
    total: Optional[int] = None


class ProductVariantResolveRequest(RequestModel):
    ids: List[PositiveDbInt] = Field(..., min_length=1, max_length=5000)

    @field_validator("ids")
    @classmethod
    def deduplicate_ids(cls, values: List[int]) -> List[int]:
        if len(set(values)) != len(values):
            raise ValueError("قائمة معرفات المنتجات لا يجوز أن تحتوي تكراراً.")
        return values


"""
    text = replace_once(text, old_simple, new_simple, "schemas product catalog cursor")
    ast.parse(text)
    return text


def patch_warehouse(text: str) -> str:
    required_before = (
        '"/warehouse/ledger/cursor"',
        '@router.post("/warehouse/ledger/{entry_id}/adjust"',
        "WarehouseLedgerCursorPage",
        "blocked_packs",
    )
    for token in required_before:
        if token not in text:
            raise RuntimeError(f"warehouse.py: Stage 6B marker missing: {token}")

    if '"/warehouse/inventory/cursor"' in text:
        raise RuntimeError("warehouse.py: inventory cursor موجود مسبقاً.")

    old_import = """from schemas import (UnifiedStocktakeStartRequest, WarehouseAlertItem,
WarehouseInventoryItem, WarehouseLedgerItem, WarehouseLedgerCursorPage, WarehouseStatusResponse, SimpleProductVariantItem,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )
"""
    new_import = """from schemas import (UnifiedStocktakeStartRequest,
WarehouseInventoryItem, WarehouseInventoryCursorPage, WarehouseLedgerItem, WarehouseLedgerCursorPage,
WarehouseStatusResponse, SimpleProductVariantItem, SimpleProductVariantCursorPage, ProductVariantResolveRequest,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )
"""
    text = replace_once(text, old_import, new_import, "warehouse schema imports")

    # Insert generic, query-bound ProductVariant cursor helpers after _escape_like.
    _, escape_end = _function_span(text, "_escape_like")
    lines = text.splitlines(keepends=True)
    text = (
        "".join(lines[:escape_end])
        + "\n"
        + VARIANT_CURSOR_HELPERS
        + "\n"
        + "".join(lines[escape_end:])
    )

    text = remove_function(
        text,
        "get_warehouse_alerts",
        "# Legacy unbounded /warehouse/alerts removed; alert metadata now comes from inventory cursor.",
    )
    text = replace_function(text, "get_warehouse_inventory", INVENTORY_FUNC)
    text = replace_function(
        text,
        "get_simple_product_variants",
        CATALOG_FUNC + "\n\n" + RESOLVE_FUNC,
    )

    ast.parse(text)

    for stale in (
        '@router.get("/warehouse/alerts"',
        '@router.get("/warehouse/inventory",',
        '@router.get("/product_variants/simple", response_model=List',
    ):
        if stale in text:
            raise RuntimeError(f"warehouse.py: unbounded legacy route remains: {stale}")

    for token in (
        '"/warehouse/inventory/cursor"',
        '"/product_variants/simple/cursor"',
        '"/product_variants/simple/resolve"',
        "page_variant_ids",
        "_decode_variant_cursor(",
        "expected_scope=scope",
    ):
        if token not in text:
            raise RuntimeError(f"warehouse.py: missing cursor invariant: {token}")

    return text


def patch_utils(text: str) -> str:
    if "export interface SimpleProductVariant " in text:
        raise RuntimeError("inventoryUtils.ts: Stage 6C types موجودة مسبقاً.")

    if "  blocked_packs: number;\n" not in text:
        text = replace_once(
            text,
            "  reserved_packs: number;\n  total_packs: number;\n",
            "  reserved_packs: number;\n  blocked_packs: number;\n  total_packs: number;\n",
            "utils blocked_packs",
        )

    marker = "export interface WarehouseAlert {\n"
    addition = """export interface WarehouseInventoryCursorPage {
  items: WarehouseProduct[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  alert_count: number | null;
  alert_samples: string[];
}

export interface SimpleProductVariant {
  id: number;
  name: string;
  sku: string | null;
  packs_per_carton: number;
}

export interface SimpleProductVariantCursorPage {
  items: SimpleProductVariant[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

"""
    text = replace_once(text, marker, addition + marker, "utils cursor interfaces")
    return text


def patch_main(text: str) -> str:
    text = replace_once(
        text,
        'import { useState, useEffect, useCallback } from "react";',
        'import { useState, useEffect, useCallback, useRef } from "react";',
        "MainInventory react import",
    )
    text = replace_once(
        text,
        'import type { WarehouseProduct, WarehouseAlert } from "./inventoryUtils";',
        'import type { WarehouseProduct } from "./inventoryUtils";',
        "MainInventory inventory type import",
    )

    old_state = """  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [alerts, setAlerts] = useState<WarehouseAlert[]>([]);
  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date>(new Date());
"""
    new_state = """  const [stockItems, setStockItems] = useState<WarehouseProduct[]>([]);
  const [stockTotal, setStockTotal] = useState<number | null>(null);
  const [stockMatchingTotal, setStockMatchingTotal] = useState<number | null>(null);
  const [stockAlertCount, setStockAlertCount] = useState(0);
  const [stockAlertSamples, setStockAlertSamples] = useState<string[]>([]);
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [stockCursorHistory, setStockCursorHistory] = useState<Array<string | null>>([]);
  const [stockNextCursor, setStockNextCursor] = useState<string | null>(null);
  const [stockSearch, setStockSearch] = useState("");
  const [stockOnlyAlerts, setStockOnlyAlerts] = useState(false);
  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const stockRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date>(new Date());
"""
    text = replace_once(text, old_state, new_state, "MainInventory stock state")

    start = text.find("  const fetchStock = useCallback(async () => {")
    status_marker = text.find(
        "  // جلب حالة القفل للمستودع المحدد فقط",
        start,
    )
    if start == -1 or status_marker == -1:
        raise RuntimeError("MainInventory: stock/alerts fetch region not found.")

    new_fetch = """  const fetchStock = useCallback(async () => {
    if (!selectedLocationId) return;

    const requestSeq = ++stockRequestSeq.current;
    setLoadingStock(true);

    try {
      const params = new URLSearchParams({
        location_id: String(selectedLocationId),
        limit: "50",
      });

      if (stockCursor) params.set("cursor", stockCursor);
      if (stockSearch) params.set("search", stockSearch);
      if (stockOnlyAlerts) params.set("only_alerts", "true");

      const data = await authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`
      );

      if (requestSeq !== stockRequestSeq.current) return;
      if (!data || !Array.isArray(data.items)) {
        throw new Error("تنسيق صفحة المخزون غير صالح");
      }

      setStockItems(data.items);
      setStockNextCursor(data.next_cursor || null);

      if (typeof data.total === "number") {
        setStockMatchingTotal(data.total);

        if (!stockSearch && !stockOnlyAlerts && stockCursor === null) {
          setStockTotal(data.total);
        }
      }

      if (!stockSearch && !stockOnlyAlerts && stockCursor === null) {
        if (typeof data.alert_count === "number") {
          setStockAlertCount(data.alert_count);
        }
        if (Array.isArray(data.alert_samples)) {
          setStockAlertSamples(data.alert_samples);
        }
      }

      setLastSync(new Date());
    } catch (e: any) {
      if (requestSeq !== stockRequestSeq.current) return;
      toast.error(e?.message || "خطأ حرج في جلب المخزون");
      setStockItems([]);
      setStockNextCursor(null);
      setStockMatchingTotal(null);
    } finally {
      if (requestSeq === stockRequestSeq.current) {
        setLoadingStock(false);
      }
    }
  }, [
    authFetch,
    selectedLocationId,
    stockCursor,
    stockSearch,
    stockOnlyAlerts,
    stockRefreshKey,
  ]);

  const resetStockPagination = useCallback(() => {
    setStockCursor(null);
    setStockCursorHistory([]);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
  }, []);

  const refreshStock = useCallback(() => {
    resetStockPagination();
    setStockRefreshKey((value) => value + 1);
  }, [resetStockPagination]);

  const handleStockSearchChange = useCallback((value: string) => {
    resetStockPagination();
    setStockSearch(value);
  }, [resetStockPagination]);

  const handleStockAlertsChange = useCallback((value: boolean) => {
    resetStockPagination();
    setStockOnlyAlerts(value);
  }, [resetStockPagination]);

  const handleStockNext = useCallback(() => {
    if (!stockNextCursor) return;
    setStockCursorHistory((prev) => [...prev, stockCursor]);
    setStockCursor(stockNextCursor);
  }, [stockCursor, stockNextCursor]);

  const handleStockPrevious = useCallback(() => {
    if (stockCursorHistory.length === 0) return;
    const previousCursor = stockCursorHistory[stockCursorHistory.length - 1] ?? null;
    setStockCursorHistory((prev) => prev.slice(0, -1));
    setStockCursor(previousCursor);
  }, [stockCursorHistory]);

"""
    text = text[:start] + new_fetch + text[status_marker:]

    old_effect = """  // جلب المخزون فور توفر المستودع
  useEffect(() => {
    if (selectedLocationId) {
      fetchStock();
      fetchAlerts();
    }
  }, [selectedLocationId, fetchStock, fetchAlerts]);
"""
    new_effect = """  useEffect(() => {
    stockRequestSeq.current += 1;
    setStockItems([]);
    setStockTotal(null);
    setStockMatchingTotal(null);
    setStockAlertCount(0);
    setStockAlertSamples([]);
    setStockSearch("");
    setStockOnlyAlerts(false);
    setStockCursor(null);
    setStockCursorHistory([]);
    setStockNextCursor(null);
  }, [selectedLocationId]);

  useEffect(() => {
    if (selectedLocationId) fetchStock();
  }, [selectedLocationId, fetchStock]);
"""
    text = replace_once(text, old_effect, new_effect, "MainInventory stock effect")

    text = replace_once(
        text,
        '<span className="text-[#1e87bb]">{products.length}</span> صنف',
        '<span className="text-[#1e87bb]">{stockTotal ?? "—"}</span> صنف',
        "MainInventory stock total",
    )
    text = replace_once(
        text,
        'onClick={() => { fetchStock(); fetchStatus(); fetchAlerts(); }}',
        'onClick={() => { refreshStock(); fetchStatus(); }}',
        "MainInventory top refresh",
    )

    old_tab1 = """        {activeTab === "live" && (
          <Tab1LiveStock
            products={products}
            alerts={alerts}
            loading={loadingStock}
            // +++ الكي الجراحي: عند ضغط زر التحديث من داخل الجدول، نحدث النواقص والمخزون معاً +++
            onRefresh={() => { fetchStock(); fetchAlerts(); }}
          />
        )}
"""
    new_tab1 = """        {activeTab === "live" && selectedLocationId && (
          <Tab1LiveStock
            locationId={selectedLocationId}
            products={stockItems}
            loading={loadingStock}
            alertCount={stockAlertCount}
            alertSamples={stockAlertSamples}
            matchingTotal={stockMatchingTotal}
            pageNumber={stockCursorHistory.length + 1}
            hasMore={!!stockNextCursor}
            hasPrevious={stockCursorHistory.length > 0}
            onlyAlerts={stockOnlyAlerts}
            onSearchChange={handleStockSearchChange}
            onOnlyAlertsChange={handleStockAlertsChange}
            onNext={handleStockNext}
            onPrevious={handleStockPrevious}
            onRefresh={refreshStock}
          />
        )}
"""
    text = replace_once(text, old_tab1, new_tab1, "MainInventory Tab1 props")

    text = replace_once(
        text,
        """          <Tab2Inbound
            products={products}
            locationId={selectedLocationId}""",
        """          <Tab2Inbound
            locationId={selectedLocationId}""",
        "MainInventory Tab2 products",
    )
    text = replace_once(
        text,
        """            onSuccess={async () => {
              await Promise.all([fetchStock(), fetchAlerts()]);
              setLedgerRefreshKey((value) => value + 1);
            }}
""",
        """            onSuccess={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
""",
        "MainInventory inbound refresh",
    )

    text = replace_once(
        text,
        """          <Tab3Stocktake
            products={products}
            locationId={selectedLocationId}""",
        """          <Tab3Stocktake
            locationId={selectedLocationId}""",
        "MainInventory Tab3 products",
    )
    text = replace_once(
        text,
        """              await Promise.all([fetchStock(), fetchAlerts()]);
              setLedgerRefreshKey((value) => value + 1);
""",
        """              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
""",
        "MainInventory stocktake refresh",
    )

    for stale in (
        "fetchAlerts",
        "setProducts(",
        "setAlerts(",
        "products={products}",
        "alerts={alerts}",
        "/warehouse/inventory?",
    ):
        if stale in text:
            raise RuntimeError(f"MainInventory: stale token remains: {stale}")

    return text


def patch_stocktake(text: str) -> str:
    text = replace_once(
        text,
        'import type { WarehouseProduct, StocktakeRow } from "./inventoryUtils";',
        'import type { StocktakeRow } from "./inventoryUtils";',
        "Tab3Stocktake type import",
    )
    text = replace_once(
        text,
        """interface Props {
  products: WarehouseProduct[];
  locationId: number;
""",
        """interface Props {
  locationId: number;
""",
        "Tab3Stocktake products prop",
    )
    text = replace_once(
        text,
        """export function Tab3Stocktake({
  products: _products,
  locationId,
""",
        """export function Tab3Stocktake({
  locationId,
""",
        "Tab3Stocktake destructuring",
    )
    text = replace_once(
        text,
        """  // products يبقى في Props للتوافق مع MainInventory، لكن الجرد لا يستخدمه حتى لا يتسرب الرصيد المتوقع للعدّاد.
  void _products;

""",
        "",
        "Tab3Stocktake stale compatibility code",
    )
    return text


def validate_ts_shape(name: str, text: str) -> None:
    if "\x00" in text or not text.strip():
        raise RuntimeError(f"{name}: invalid/empty source")
    if text.count("{") == 0 or text.count("}") == 0:
        raise RuntimeError(f"{name}: unexpected TSX source shape")


def maybe_typescript_syntax_check(prepared: dict[str, str]) -> None:
    node = shutil.which("node.exe") or shutil.which("node")
    ts_js = DASHBOARD / "node_modules" / "typescript" / "lib" / "typescript.js"
    if node is None or not ts_js.is_file():
        print("TYPESCRIPT_TRANSPILE_CHECK=SKIPPED (run npm build from your normal WSL environment)")
        return

    check_dir = ROOT / ".stage6c_ts_check"
    if check_dir.exists():
        shutil.rmtree(check_dir)
    check_dir.mkdir()

    try:
        for key in ("main", "live", "inbound", "stocktake", "utils"):
            suffix = ".tsx" if key != "utils" else ".ts"
            (check_dir / f"{key}{suffix}").write_text(
                prepared[key],
                encoding="utf-8",
                newline="\n",
            )

        checker = check_dir / "check.cjs"
        checker.write_text(
            """const ts = require(process.argv[2]);
const fs = require("fs");
let failed = false;
for (const file of process.argv.slice(3)) {
  const src = fs.readFileSync(file, "utf8");
  const result = ts.transpileModule(src, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.ESNext,
      jsx: ts.JsxEmit.ReactJSX,
    },
    reportDiagnostics: true,
    fileName: file,
  });
  for (const d of result.diagnostics || []) {
    if (d.category === ts.DiagnosticCategory.Error) {
      failed = true;
      console.error(file + ": " + ts.flattenDiagnosticMessageText(d.messageText, "\\n"));
    }
  }
}
process.exit(failed ? 1 : 0);
""",
            encoding="utf-8",
        )

        source_files = [
            str(check_dir / "main.tsx"),
            str(check_dir / "live.tsx"),
            str(check_dir / "inbound.tsx"),
            str(check_dir / "stocktake.tsx"),
            str(check_dir / "utils.ts"),
        ]
        result = subprocess.run(
            [node, str(checker), str(ts_js), *source_files],
            cwd=ROOT,
            text=True,
            capture_output=True,
            shell=False,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            raise RuntimeError("TypeScript syntax/transpile check failed.")
        print("TYPESCRIPT_TRANSPILE_CHECK=OK")
    finally:
        shutil.rmtree(check_dir, ignore_errors=True)


def validate(prepared: dict[str, str]) -> None:
    ast.parse(prepared["models"])
    ast.parse(prepared["schemas"])
    ast.parse(prepared["warehouse"])

    if prepared["models"].count("ix_product_variant_company_name_id") != 1:
        raise RuntimeError("models.py: cursor index duplication detected.")

    if '@router.get("/warehouse/alerts"' in prepared["warehouse"]:
        raise RuntimeError("warehouse.py: unbounded alerts route still present.")

    required = {
        "schemas": [
            "class WarehouseInventoryCursorPage(BaseModel):",
            "class SimpleProductVariantCursorPage(BaseModel):",
            "class ProductVariantResolveRequest(RequestModel):",
        ],
        "warehouse": [
            '"/warehouse/inventory/cursor"',
            '"/product_variants/simple/cursor"',
            '"/product_variants/simple/resolve"',
            "page_variant_ids",
            "expected_scope=scope",
        ],
        "main": [
            "/warehouse/inventory/cursor?",
            "stockCursorHistory",
            "refreshStock",
        ],
        "live": [
            "onSearchChange",
            "hasPrevious",
            "blocked_packs",
        ],
        "inbound": [
            "/product_variants/simple/cursor",
            "/product_variants/simple/resolve",
            "freshProducts",
            "inbound_draft_products_v3",
        ],
    }
    for key, tokens in required.items():
        for token in tokens:
            if token not in prepared[key]:
                raise RuntimeError(f"{key}: missing Stage 6C invariant: {token}")

    for key in ("main", "live", "inbound", "stocktake", "utils"):
        validate_ts_shape(key, prepared[key])


def main() -> None:
    for key, path in FILES.items():
        if not path.is_file():
            raise SystemExit(f"ERROR: missing {path}")

    originals = {key: path.read_bytes() for key, path in FILES.items()}
    prepared: dict[str, str] = {}

    for key, path in FILES.items():
        text = normalize(originals[key])
        if key == "models":
            text = patch_models(text)
        elif key == "schemas":
            text = patch_schemas(text)
        elif key == "warehouse":
            text = patch_warehouse(text)
        elif key == "main":
            text = patch_main(text)
        elif key == "live":
            if "alertIds" not in text or "displayedProducts" not in text:
                raise RuntimeError(
                    "Tab1LiveStock.tsx: current file does not match the pre-Stage6C contract."
                )
            text = TAB1_FINAL
        elif key == "inbound":
            for token in (
                "inbound_batch_drafts_v2",
                "wanasah_inbound_request_id_",
                "batch_number",
                "expiry_date",
            ):
                if token not in text:
                    raise RuntimeError(
                        f"Tab2Inbound.tsx: Stage 6B marker missing: {token}"
                    )
            text = TAB2_FINAL
        elif key == "stocktake":
            text = patch_stocktake(text)
        elif key == "utils":
            text = patch_utils(text)

        prepared[key] = text

    validate(prepared)
    maybe_typescript_syntax_check(prepared)

    # Compile backend from temporary paths before touching user files.
    tmp_dir = ROOT / ".stage6c_backend_check"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()
    try:
        for key in ("models", "schemas", "warehouse"):
            tmp = tmp_dir / f"{key}.py"
            tmp.write_text(prepared[key], encoding="utf-8", newline="\n")
            py_compile.compile(str(tmp), doraise=True)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    written: list[str] = []
    try:
        for key, path in FILES.items():
            path.write_text(prepared[key], encoding="utf-8", newline="\n")
            written.append(key)

        # Final compile on actual backend paths.
        for key in ("models", "schemas", "warehouse"):
            py_compile.compile(str(FILES[key]), doraise=True)

    except Exception:
        for key in written:
            FILES[key].write_bytes(originals[key])
        raise

    print("WAREHOUSE_STAGE6_LIVE_CATALOG_CURSOR_PATCH_OK")
    print("BACKEND_PY_COMPILE=OK")
    print("MODEL_CURSOR_INDEX=EXACTLY_ONCE")
    print("LEGACY_UNBOUNDED_ALERTS=REMOVED")
    print("LEGACY_UNBOUNDED_INVENTORY=REMOVED")
    print("LEGACY_UNBOUNDED_SIMPLE_CATALOG=REMOVED")
    print("INVENTORY_CURSOR=BOUNDED_AGGREGATION")
    print("CATALOG_CURSOR=ENABLED")
    print("INBOUND_DRAFT_METADATA=RETRY_SAFE_AND_FRESHLY_RESOLVED")
    print("NEXT=REBUILD_DEV_SCHEMA_AND_WSL_DASHBOARD_BUILD")


if __name__ == "__main__":
    main()
