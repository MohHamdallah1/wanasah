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

FILES = {
    "schemas": BACKEND / "schemas.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
    "main": DASHBOARD / "src" / "pages" / "inventory" / "MainInventory.tsx",
    "inbound": DASHBOARD / "src" / "pages" / "inventory" / "Tab2Inbound.tsx",
    "ledger": DASHBOARD / "src" / "pages" / "inventory" / "Tab4Ledger.tsx",
    "utils": DASHBOARD / "src" / "pages" / "inventory" / "inventoryUtils.ts",
}


def normalize(data: bytes) -> str:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def patch_schemas(text: str) -> str:
    marker = "class WarehouseLedgerItem(BaseModel):\n    id: int\n"
    if "class WarehouseLedgerItem(BaseModel):\n    id: int\n    product_variant_id: int\n" not in text:
        text = replace_once(
            text,
            marker,
            "class WarehouseLedgerItem(BaseModel):\n    id: int\n    product_variant_id: int\n",
            "schemas WarehouseLedgerItem.product_variant_id",
        )
    return text


def patch_warehouse(text: str) -> str:
    if '"/warehouse/ledger/cursor"' not in text:
        raise RuntimeError(
            "warehouse.py: /warehouse/ledger/cursor غير موجود. "
            "طبّق باتش Cursor Backend أولاً."
        )

    # Remove the old list endpoint only after the dashboard is migrated in this same atomic patch.
    legacy_start = text.find(
        '@router.get("/warehouse/ledger", response_model=List[WarehouseLedgerItem], status_code=200)'
    )
    cursor_marker = text.find("# Cursor API الجديد لسجل الحركات.")

    if legacy_start == -1:
        raise RuntimeError("warehouse.py: legacy /warehouse/ledger endpoint غير موجود أو أزيل مسبقاً.")
    if cursor_marker == -1 or cursor_marker <= legacy_start:
        raise RuntimeError("warehouse.py: cursor endpoint marker غير موجود بعد legacy endpoint.")

    text = (
        text[:legacy_start]
        + "# Legacy list ledger endpoint removed after Dashboard cursor migration.\n"
        + text[cursor_marker:]
    )

    # Expose stable product identity; product name alone is not a safe identity for invoice corrections.
    response_marker = '''            result.append({
                "id": movement.id,
                "product_name": product_name,
'''
    if '"product_variant_id": movement.product_variant_id' not in text:
        text = replace_once(
            text,
            response_marker,
            '''            result.append({
                "id": movement.id,
                "product_variant_id": movement.product_variant_id,
                "product_name": product_name,
''',
            "warehouse cursor product_variant_id",
        )

    # Exact reference lookup should use the composite btree index added in Stage 6.
    old_ref = '''        if reference_id:
            normalized_reference = reference_id.strip().lower()
            if normalized_reference:
                stmt = stmt.filter(
                    func.lower(func.trim(InventoryMovement.reference_id))
                    == normalized_reference
                )
'''
    new_ref = '''        if reference_id:
            clean_reference = reference_id.strip()
            if clean_reference:
                stmt = stmt.filter(
                    InventoryMovement.reference_id == clean_reference
                )
'''
    if old_ref in text:
        text = replace_once(text, old_ref, new_ref, "warehouse exact reference lookup")

    # DISTINCT reference types are needed only on the first page, not on every cursor hop.
    old_types = '''        type_stmt = select(
            InventoryMovement.reference_type
        ).filter(
            InventoryMovement.company_id == company_id,
        )

        if location_id is not None:
            type_stmt = type_stmt.filter(
                or_(
                    InventoryMovement.source_location_id == location_id,
                    InventoryMovement.destination_location_id == location_id,
                )
            )

        available_types = list(
            (
                await db.execute(
                    type_stmt.distinct().order_by(
                        InventoryMovement.reference_type.asc()
                    )
                )
            ).scalars().all()
        )
'''
    new_types = '''        available_types: list[str] = []
        if cursor is None and reference_id is None:
            type_stmt = select(
                InventoryMovement.reference_type
            ).filter(
                InventoryMovement.company_id == company_id,
            )

            if location_id is not None:
                type_stmt = type_stmt.filter(
                    or_(
                        InventoryMovement.source_location_id == location_id,
                        InventoryMovement.destination_location_id == location_id,
                    )
                )

            available_types = list(
                (
                    await db.execute(
                        type_stmt.distinct().order_by(
                            InventoryMovement.reference_type.asc()
                        )
                    )
                ).scalars().all()
            )
'''
    if old_types in text:
        text = replace_once(text, old_types, new_types, "warehouse cursor available_types")

    if '@router.get("/warehouse/ledger", response_model=List[WarehouseLedgerItem]' in text:
        raise RuntimeError("warehouse.py: legacy /warehouse/ledger endpoint ما زال موجوداً.")
    if '@router.post("/warehouse/ledger/{entry_id}/adjust"' not in text:
        raise RuntimeError("warehouse.py: adjustment endpoint حُذف بالخطأ.")
    return text


def patch_utils(text: str) -> str:
    # Stage 6 query semantics added this field on the backend; reflect it in the UI type.
    if "  blocked_packs: number;\n" not in text:
        text = replace_once(
            text,
            "  reserved_packs: number;\n  total_packs: number;\n",
            "  reserved_packs: number;\n  blocked_packs: number;\n  total_packs: number;\n",
            "inventoryUtils WarehouseProduct.blocked_packs",
        )

    if "  product_variant_id: number;\n" not in text.split("export interface LedgerEntry {", 1)[1].split("}", 1)[0]:
        text = replace_once(
            text,
            "export interface LedgerEntry {\n  id: number;\n",
            "export interface LedgerEntry {\n  id: number;\n  product_variant_id: number;\n",
            "inventoryUtils LedgerEntry.product_variant_id",
        )

    # Backend fields are nullable by design for defensive legacy rows.
    text = text.replace("  balance_before: number;", "  balance_before: number | null;")
    text = text.replace("  balance_after: number;", "  balance_after: number | null;")
    text = text.replace("  reference: string;", "  reference: string | null;")
    text = text.replace("  notes: string;", "  notes: string | null;")
    text = text.replace("  sku: string;", "  sku: string | null;")
    return text


TAB2_INBOUND = r'''import { useState, useMemo, useEffect } from "react";
import { FilePlus, Search, Eraser, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { WarehouseProduct } from "./inventoryUtils";
import { toTotalPacks } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal";

interface Props {
  products: WarehouseProduct[];
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

export function Tab2Inbound({ products, locationId, authenticatedFetch, onSuccess }: Props) {
  const [drafts, setDrafts] = useState<InboundDraftMap>(() => loadDrafts());
  const [search, setSearch] = useState("");
  const [referenceId, setReferenceId] = useState(() => localStorage.getItem("inbound_draft_ref") || "");
  const [notes, setNotes] = useState(() => localStorage.getItem("inbound_draft_notes") || "");
  const [submitting, setSubmitting] = useState(false);
  const [isConfirmClearOpen, setIsConfirmClearOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem("inbound_batch_drafts_v2", JSON.stringify(drafts));
  }, [drafts]);
  useEffect(() => { localStorage.setItem("inbound_draft_ref", referenceId); }, [referenceId]);
  useEffect(() => { localStorage.setItem("inbound_draft_notes", notes); }, [notes]);

  const updateBatch = (
    productId: string,
    rowId: string,
    patch: Partial<Omit<InboundBatchDraft, "row_id">>,
  ) => {
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

  const addBatch = (productId: string) => {
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
    setReferenceId("");
    setNotes("");
    localStorage.removeItem("inbound_batch_drafts_v2");
    localStorage.removeItem("inbound_draft_quantities");
    localStorage.removeItem("inbound_draft_ref");
    localStorage.removeItem("inbound_draft_notes");
    clearStoredRequestIdentity();
    setIsConfirmClearOpen(false);
    toast.success("تم تصفير التوريدة والمسودة بالكامل بنجاح");
  };

  const handleSubmit = async () => {
    const itemsToSubmit: Array<{
      product_variant_id: number;
      quantity_packs: number;
      batch_number: string;
      production_date: string | null;
      expiry_date: string;
    }> = [];

    const seenBatchKeys = new Set<string>();

    for (const [productId, rows] of Object.entries(drafts)) {
      const product = products.find((p) => String(p.id) === productId);
      if (!product) continue;
      const ppc = product.packs_per_carton || 1;

      for (const row of rows) {
        if (row.cartons === 0 && row.loose_packs === 0) continue;

        if (row.loose_packs >= ppc) {
          toast.error(`خطأ في (${product.name}): الحبات يجب أن تكون أقل من ${ppc}.`);
          return;
        }

        const batchNumber = row.batch_number.trim();
        if (!batchNumber) {
          toast.error(`أدخل رقم الدفعة للصنف (${product.name}).`);
          return;
        }
        if (!row.expiry_date) {
          toast.error(`أدخل تاريخ الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`);
          return;
        }
        if (row.production_date && row.production_date > row.expiry_date) {
          toast.error(`تاريخ الإنتاج بعد الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`);
          return;
        }

        const duplicateKey = `${product.id}|${batchNumber}`;
        if (seenBatchKeys.has(duplicateKey)) {
          toast.error(`الدفعة (${batchNumber}) مكررة للصنف (${product.name}). اجمع الكمية في سطر واحد.`);
          return;
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

    if (itemsToSubmit.length === 0) {
      toast.error("أضف كمية لصنف واحد على الأقل لتوريده.");
      return;
    }
    if (!referenceId.trim()) {
      toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد.");
      return;
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

    setSubmitting(true);
    try {
      const data = await authenticatedFetch("/warehouse/inbound", {
        method: "POST",
        body: JSON.stringify({ request_id: requestId, ...businessPayload }),
      });

      toast.success(data?.message || "تم استلام البضاعة وتوثيقها بنجاح ✅");
      setDrafts({});
      setReferenceId("");
      setNotes("");
      localStorage.removeItem("inbound_batch_drafts_v2");
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

  const displayedProducts = useMemo(() => {
    if (!search.trim()) return products;
    const tokens = search.toLowerCase().trim().split(/\s+/);
    return products.filter((p) => tokens.every((token) => (
      p.name.toLowerCase().includes(token)
      || (p.sku && p.sku.toLowerCase().includes(token))
    )));
  }, [products, search]);

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
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
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
              {displayedProducts.length === 0 ? (
                <tr><td colSpan={4} className="text-center py-12 text-slate-400">لا توجد منتجات مطابقة</td></tr>
              ) : displayedProducts.map((product) => {
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
                            onChange={(e) => updateBatch(productId, row.row_id, { batch_number: e.target.value })}
                            placeholder="رقم الدفعة *"
                            className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-bold outline-none focus:border-emerald-400"
                          />
                          <div>
                            <label className="block text-[9px] text-slate-400 mb-0.5">الإنتاج (اختياري)</label>
                            <input
                              type="date"
                              value={row.production_date}
                              onChange={(e) => updateBatch(productId, row.row_id, { production_date: e.target.value })}
                              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs outline-none focus:border-emerald-400"
                            />
                          </div>
                          <div>
                            <label className="block text-[9px] text-slate-400 mb-0.5">الصلاحية *</label>
                            <input
                              type="date"
                              value={row.expiry_date}
                              onChange={(e) => updateBatch(productId, row.row_id, { expiry_date: e.target.value })}
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
                              onChange={(value) => updateBatch(productId, row.row_id, { cartons: value })}
                            />
                          </div>
                          <div className="flex flex-col items-center gap-1">
                            <span className={`text-[10px] font-bold ${looseError ? "text-red-600" : "text-slate-500"}`}>حبات</span>
                            <QuantityInput
                              value={row.loose_packs}
                              onChange={(value) => updateBatch(productId, row.row_id, { loose_packs: value })}
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
                              onClick={() => addBatch(productId)}
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
'''


TAB4_LEDGER = r'''import { useState, useEffect, useCallback, useRef } from "react";
import { History, Search, ChevronRight, ChevronLeft, Eye, FileText, Package, RefreshCcw } from "lucide-react";
import type { LedgerEntry } from "./inventoryUtils";
import { getLedgerBadge, formatQty } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";

interface Props {
  locationId: number;
  refreshKey: number;
}

interface LedgerCursorPage {
  items: LedgerEntry[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  available_types: string[];
}

export function Tab4Ledger({ locationId, refreshKey }: Props) {
  const authenticatedFetch = useAuthFetch();

  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterType, setFilterType] = useState("ALL");
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);

  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const [selectedNote, setSelectedNote] = useState<string | null>(null);
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [deliveryNoteItems, setDeliveryNoteItems] = useState<LedgerEntry[]>([]);
  const [referenceLoading, setReferenceLoading] = useState(false);

  const [adjustingEntry, setAdjustingEntry] = useState<LedgerEntry | null>(null);
  const [adjPassword, setAdjPassword] = useState("");
  const [newQty, setNewQty] = useState({ cartons: 0, loose: 0 });
  const [adjSubmitting, setAdjSubmitting] = useState(false);

  const requestSequence = useRef(0);
  const PAGE_SIZE = 20;

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const buildUrl = useCallback((
    cursor: string | null,
    options?: { exactReference?: string; pageSize?: number },
  ) => {
    const params = new URLSearchParams({
      location_id: String(locationId),
      limit: String(options?.pageSize ?? PAGE_SIZE),
    });

    if (cursor) params.set("cursor", cursor);

    if (options?.exactReference) {
      params.set("reference_id", options.exactReference);
    } else {
      if (debouncedSearch.length >= 2) params.set("search", debouncedSearch);
      if (filterType !== "ALL") params.set("reference_type", filterType);
    }

    return `/warehouse/ledger/cursor?${params.toString()}`;
  }, [locationId, debouncedSearch, filterType]);

  const loadPage = useCallback(async (cursor: string | null, targetPage: number) => {
    const sequence = ++requestSequence.current;
    setLoading(true);

    try {
      const data = await authenticatedFetch(buildUrl(cursor)) as LedgerCursorPage;
      if (sequence !== requestSequence.current) return;
      if (!data || !Array.isArray(data.items)) throw new Error("استجابة سجل الحركات غير صالحة.");

      setEntries(data.items);
      setNextCursor(data.next_cursor || null);
      setHasMore(data.has_more === true);
      setPageIndex(targetPage);

      if (typeof data.total === "number") setTotal(data.total);
      if (Array.isArray(data.available_types) && data.available_types.length > 0) {
        setAvailableTypes(data.available_types);
      }
    } catch (e: any) {
      if (sequence !== requestSequence.current) return;
      setEntries([]);
      setNextCursor(null);
      setHasMore(false);
      toast.error(e?.message || "تعذر جلب سجل الحركات.");
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [authenticatedFetch, buildUrl]);

  const resetAndLoad = useCallback(() => {
    requestSequence.current += 1;
    setCursorHistory([null]);
    setPageIndex(0);
    setNextCursor(null);
    setHasMore(false);
    setTotal(null);
    void loadPage(null, 0);
  }, [loadPage]);

  useEffect(() => {
    resetAndLoad();
  }, [resetAndLoad, refreshKey]);

  const goNext = () => {
    if (!hasMore || !nextCursor || loading) return;
    const target = pageIndex + 1;
    setCursorHistory((prev) => {
      const next = prev.slice(0, target);
      next[target] = nextCursor;
      return next;
    });
    void loadPage(nextCursor, target);
  };

  const goPrevious = () => {
    if (pageIndex <= 0 || loading) return;
    const target = pageIndex - 1;
    void loadPage(cursorHistory[target] ?? null, target);
  };

  const fetchAllByReference = useCallback(async (reference: string) => {
    const all: LedgerEntry[] = [];
    let cursor: string | null = null;

    for (let page = 0; page < 50; page += 1) {
      const data = await authenticatedFetch(
        buildUrl(cursor, { exactReference: reference, pageSize: 200 })
      ) as LedgerCursorPage;

      if (!data || !Array.isArray(data.items)) throw new Error("استجابة تفاصيل المرجع غير صالحة.");
      all.push(...data.items);

      if (!data.has_more) return all;
      if (!data.next_cursor) throw new Error("Cursor تفاصيل المرجع غير متسق.");
      cursor = data.next_cursor;
    }

    throw new Error("عدد حركات المرجع تجاوز 10,000 حركة؛ استخدم تقريراً مخصصاً.");
  }, [authenticatedFetch, buildUrl]);

  const openReference = async (reference: string) => {
    setSelectedReference(reference);
    setDeliveryNoteItems([]);
    setReferenceLoading(true);
    try {
      setDeliveryNoteItems(await fetchAllByReference(reference));
    } catch (e: any) {
      toast.error(e?.message || "تعذر جلب تفاصيل المرجع.");
      setSelectedReference(null);
    } finally {
      setReferenceLoading(false);
    }
  };

  const openAdjustment = async (entry: LedgerEntry) => {
    if (!entry.reference) return;
    setReferenceLoading(true);
    try {
      const all = await fetchAllByReference(entry.reference);
      const relevant = all.filter((movement) => (
        movement.product_variant_id === entry.product_variant_id
        && (movement.type === "INBOUND_SUPPLIER" || movement.type === "INBOUND_CORRECTION")
      ));
      const net = relevant.reduce((sum, movement) => sum + movement.quantity_packs, 0);
      const ppc = entry.packs_per_carton || 1;
      const safeNet = Math.max(0, net);
      setAdjustingEntry(entry);
      setNewQty({ cartons: Math.floor(safeNet / ppc), loose: safeNet % ppc });
    } catch (e: any) {
      toast.error(e?.message || "تعذر حساب صافي فاتورة التوريد.");
    } finally {
      setReferenceLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full flex-1 min-h-0 pt-1">
      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm flex-1 min-h-0">
        <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-blue-600 to-indigo-700 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
          <History className="w-4 h-4" /> سجل الحركات {total !== null ? `(${total})` : ""}
        </div>

        <div className="p-3 pt-5 border-b border-slate-100 flex flex-col sm:flex-row items-center justify-end gap-3 bg-slate-50 rounded-t-2xl">
          <button
            onClick={resetAndLoad}
            disabled={loading}
            className="p-2 rounded-xl border border-slate-200 bg-white text-slate-600 hover:text-blue-600 disabled:opacity-40"
            title="تحديث السجل"
          >
            <RefreshCcw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>

          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm"
          >
            <option value="ALL">جميع الحركات</option>
            {availableTypes.map((type) => (
              <option key={type} value={type}>{getLedgerBadge(type).label}</option>
            ))}
          </select>

          <div className="relative w-full sm:w-72">
            <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ابحث (حرفان فأكثر)..."
              className="w-full rounded-xl border border-slate-200 bg-white pr-9 pl-3 py-2 text-xs font-bold text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm"
            />
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar bg-white rounded-b-2xl">
          <table className="w-full text-sm min-w-[1150px]">
            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur shadow-sm border-b border-slate-200 text-right">
              <tr>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">نوع العملية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المنتج</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد قبل</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الكمية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد بعد</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المرجع</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الملاحظات</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">التاريخ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading && (
                <tr><td colSpan={9} className="text-center py-12 text-slate-400 font-bold">جارٍ التحميل...</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan={9} className="text-center py-12 text-slate-400">لا توجد حركات مطابقة</td></tr>
              )}
              {!loading && entries.map((entry) => {
                const badge = getLedgerBadge(entry.type);
                const ppc = entry.packs_per_carton || 1;
                const isNeg = entry.quantity_packs < 0;
                const reference = entry.reference || "";

                return (
                  <tr key={entry.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-lg text-[11px] font-black ${badge.bg} ${badge.text}`}>{badge.label}</span></td>
                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>
                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">{formatQty(entry.balance_before ?? 0, ppc)}</td>
                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>{isNeg ? "-" : "+"}{formatQty(Math.abs(entry.quantity_packs), ppc)}</td>
                    <td className="px-4 py-3 text-slate-800 font-bold text-xs bg-slate-50/50">{formatQty(entry.balance_after ?? 0, ppc)}</td>
                    <td className="px-4 py-3 text-slate-600 text-xs font-bold">{entry.admin_name || "—"}</td>
                    <td className="px-4 py-3">
                      {reference ? (
                        entry.type === "INBOUND_SUPPLIER" || entry.type === "INBOUND_CORRECTION" ? (
                          <span className="text-[11px] font-bold text-slate-700 bg-slate-100 border border-slate-200 px-2 py-1 rounded-md">فاتورة مورد: {reference}</span>
                        ) : (
                          <button onClick={() => { void openReference(reference); }} className="flex items-center gap-1 text-xs text-blue-700 hover:bg-blue-50 px-2 py-1 rounded-md">
                            <FileText className="w-3.5 h-3.5" /> {reference}
                          </button>
                        )
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {entry.notes ? (
                          <button onClick={() => setSelectedNote(entry.notes)} className="p-1.5 rounded-lg bg-slate-100 text-slate-500 hover:text-slate-800"><Eye className="w-3.5 h-3.5" /></button>
                        ) : <span className="text-slate-300">—</span>}
                        {entry.type === "INBOUND_SUPPLIER" && reference && (
                          <button
                            disabled={referenceLoading}
                            onClick={() => { void openAdjustment(entry); }}
                            className="text-xs text-purple-600 bg-purple-50 px-2 py-1 rounded-lg border border-purple-100 disabled:opacity-40"
                          >
                            تعديل
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-[11px] font-semibold whitespace-nowrap" dir="ltr">
                      {entry.date ? new Date(entry.date.endsWith("Z") || entry.date.includes("+") ? entry.date : `${entry.date}Z`).toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" }) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!loading && (pageIndex > 0 || hasMore) && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50 rounded-b-2xl">
            <span className="text-xs font-bold text-slate-500">صفحة {pageIndex + 1} — {entries.length} حركة</span>
            <div className="flex gap-2">
              <button onClick={goPrevious} disabled={pageIndex === 0} className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30"><ChevronRight className="w-4 h-4" /></button>
              <button onClick={goNext} disabled={!hasMore || !nextCursor} className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30"><ChevronLeft className="w-4 h-4" /></button>
            </div>
          </div>
        )}
      </div>

      <Modal isOpen={!!selectedNote} onClose={() => setSelectedNote(null)} title="تفاصيل الحركة المحاسبية" maxWidth="max-w-md">
        <div className="p-4 bg-slate-50 rounded-xl border border-slate-100"><p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{selectedNote}</p></div>
      </Modal>

      <Modal
        isOpen={!!selectedReference}
        onClose={() => { setSelectedReference(null); setDeliveryNoteItems([]); }}
        title={`وصل تسليم مجمع: ${selectedReference || ""}`}
        maxWidth="max-w-2xl"
      >
        {referenceLoading ? (
          <div className="py-12 text-center text-sm font-bold text-slate-400">جارٍ تحميل جميع حركات المرجع...</div>
        ) : (
          <div className="border border-slate-200 rounded-xl overflow-hidden max-h-[60vh] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 sticky top-0"><tr><th className="px-4 py-2 text-right">الصنف</th><th className="px-4 py-2">الكمية</th><th className="px-4 py-2 text-right">النوع</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {deliveryNoteItems.map((item) => {
                  const badge = getLedgerBadge(item.type);
                  return (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-bold text-slate-800 flex items-center gap-2"><Package className="w-4 h-4 text-slate-400" />{item.product_name}</td>
                      <td className="px-4 py-3 text-center font-bold">{item.quantity_packs < 0 ? "-" : "+"}{formatQty(Math.abs(item.quantity_packs), item.packs_per_carton || 1)}</td>
                      <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-md text-[10px] font-bold ${badge.bg} ${badge.text}`}>{badge.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={!!adjustingEntry}
        onClose={() => { setAdjustingEntry(null); setAdjPassword(""); }}
        title="🛠️ تعديل فاتورة توريد"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-2 w-full">
            <button onClick={() => setAdjustingEntry(null)} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl">إلغاء</button>
            <button
              disabled={adjSubmitting || !adjPassword}
              onClick={async () => {
                if (!adjustingEntry) return;
                const ppc = adjustingEntry.packs_per_carton || 1;
                if (newQty.loose >= ppc) {
                  toast.error(`عدد الحبات يجب أن يكون أقل من ${ppc}.`);
                  return;
                }
                setAdjSubmitting(true);
                try {
                  const totalPacks = (newQty.cartons * ppc) + newQty.loose;
                  await authenticatedFetch(`/warehouse/ledger/${adjustingEntry.id}/adjust`, {
                    method: "POST",
                    body: JSON.stringify({ password: adjPassword, new_total_packs: totalPacks }),
                  });
                  toast.success("تم تسجيل حركة التصحيح وتحديث المخزون بنجاح ✅");
                  setAdjustingEntry(null);
                  setAdjPassword("");
                  resetAndLoad();
                } catch (e: any) {
                  toast.error(e?.message || "حدث خطأ أثناء التصحيح.");
                } finally {
                  setAdjSubmitting(false);
                }
              }}
              className="flex-1 bg-purple-600 text-white py-2 rounded-xl font-bold hover:bg-purple-700 disabled:opacity-50"
            >
              {adjSubmitting ? "جاري المعالجة..." : "تأكيد التعديل"}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-purple-50 p-3 rounded-xl border border-purple-100">
            <p className="text-[11px] font-bold text-purple-800">صنف: {adjustingEntry?.product_name}</p>
            <p className="text-[10px] text-purple-600 mt-1">المرجع: {adjustingEntry?.reference}</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-black text-slate-600">الإجمالي الصحيح (كراتين)</label>
              <input type="number" min={0} value={newQty.cartons} onChange={(e) => setNewQty((prev) => ({ ...prev, cartons: Math.max(0, parseInt(e.target.value) || 0) }))} className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black outline-none" />
            </div>
            <div>
              <label className="text-xs font-black text-slate-600">الإجمالي الصحيح (حبات)</label>
              <input type="number" min={0} value={newQty.loose} onChange={(e) => setNewQty((prev) => ({ ...prev, loose: Math.max(0, parseInt(e.target.value) || 0) }))} className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black outline-none" />
            </div>
          </div>
          <div>
            <label className="text-xs font-black text-red-600">كلمة مرور المسؤول للتأكيد 🔑</label>
            <input type="password" value={adjPassword} onChange={(e) => setAdjPassword(e.target.value)} className="w-full rounded-xl border-2 border-red-100 p-3 text-center font-black focus:border-red-500 outline-none" placeholder="••••••••" />
          </div>
        </div>
      </Modal>
    </div>
  );
}
'''


def patch_main(text: str) -> str:
    text = replace_once(
        text,
        'import { useState, useEffect, useCallback, useRef } from "react";',
        'import { useState, useEffect, useCallback } from "react";',
        "MainInventory react import",
    )
    text = replace_once(
        text,
        'import type { WarehouseProduct, WarehouseAlert, LedgerEntry } from "./inventoryUtils";',
        'import type { WarehouseProduct, WarehouseAlert } from "./inventoryUtils";',
        "MainInventory ledger type import",
    )

    text = replace_once(
        text,
        '''  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [alerts, setAlerts] = useState<WarehouseAlert[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const ledgerFetchedRef = useRef(false); 
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [loadingLedger, setLoadingLedger] = useState(false);
''',
        '''  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [alerts, setAlerts] = useState<WarehouseAlert[]>([]);
  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
''',
        "MainInventory ledger state",
    )

    start = text.find("  const fetchLedger = useCallback(async (force = false) => {")
    end = text.find("  // ── on mount ────────────────────────────────────────────────────────────────", start)
    if start == -1 or end == -1:
        raise RuntimeError("MainInventory: fetchLedger block غير موجود.")
    text = text[:start] + text[end:]

    text = replace_once(
        text,
        '''  useEffect(() => {
    if (selectedLocationId) {
      ledgerFetchedRef.current = false; // إعادة طلب السجل للمستودع الجديد
      fetchStock();
      fetchAlerts();
      if (activeTab === "ledger") fetchLedger();
    }
  }, [selectedLocationId, fetchStock, fetchAlerts, fetchLedger, activeTab]);
''',
        '''  useEffect(() => {
    if (selectedLocationId) {
      fetchStock();
      fetchAlerts();
    }
  }, [selectedLocationId, fetchStock, fetchAlerts]);
''',
        "MainInventory stock effect",
    )

    text = replace_once(
        text,
        '''            onSuccess={async () => {
              await Promise.all([
                fetchStock(),
                fetchAlerts(),
                fetchLedger(true)
              ]);
            }}
''',
        '''            onSuccess={async () => {
              await Promise.all([fetchStock(), fetchAlerts()]);
              setLedgerRefreshKey((value) => value + 1);
            }}
''',
        "MainInventory inbound refresh",
    )

    text = replace_once(
        text,
        '''              // +++  (I-09): إجبار مسح الكاش وتحديث دفتر الأستاذ (Ledger) بعد الجرد +++
              ledgerFetchedRef.current = false;
              await Promise.all([fetchStock(), fetchAlerts(), fetchLedger(true)]);
''',
        '''              await Promise.all([fetchStock(), fetchAlerts()]);
              setLedgerRefreshKey((value) => value + 1);
''',
        "MainInventory stocktake refresh",
    )

    text = replace_once(
        text,
        '''        {activeTab === "ledger" && (
          <Tab4Ledger
            entries={ledger}
            loading={loadingLedger}
            // +++   تمرير دالة التحديث للابن لمنع الريفرش الإجباري +++
            onRefresh={() => fetchLedger(true)}
          />
        )}
''',
        '''        {activeTab === "ledger" && selectedLocationId && (
          <Tab4Ledger
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
          />
        )}
''',
        "MainInventory cursor ledger props",
    )

    for stale in ("fetchLedger(", "ledgerFetchedRef", "loadingLedger", "setLedger("):
        if stale in text:
            raise RuntimeError(f"MainInventory: stale ledger token remains: {stale}")
    return text


def validate_frontend_source(name: str, text: str) -> None:
    if "\x00" in text:
        raise RuntimeError(f"{name}: NUL byte detected")
    if text.count("{") == 0:
        raise RuntimeError(f"{name}: source unexpectedly empty")


def validate(prepared: dict[str, str]) -> None:
    wh = prepared["warehouse"]
    schemas = prepared["schemas"]
    main = prepared["main"]
    inbound = prepared["inbound"]
    ledger = prepared["ledger"]
    utils = prepared["utils"]

    required = [
        ('warehouse', '"/warehouse/ledger/cursor"', wh),
        ('warehouse', '"product_variant_id": movement.product_variant_id', wh),
        ('warehouse', '@router.post("/warehouse/ledger/{entry_id}/adjust"', wh),
        ('schemas', 'product_variant_id: int', schemas),
        ('main', 'locationId={selectedLocationId}', main),
        ('main', 'refreshKey={ledgerRefreshKey}', main),
        ('inbound', 'request_id: requestId', inbound),
        ('inbound', 'batch_number: batchNumber', inbound),
        ('inbound', 'expiry_date: row.expiry_date', inbound),
        ('inbound', 'production_date: row.production_date || null', inbound),
        ('inbound', 'crypto.randomUUID()', inbound),
        ('ledger', '/warehouse/ledger/cursor?', ledger),
        ('ledger', 'cursorHistory', ledger),
        ('ledger', 'fetchAllByReference', ledger),
        ('utils', 'product_variant_id: number', utils),
        ('utils', 'blocked_packs: number', utils),
    ]
    for file_name, token, source in required:
        if token not in source:
            raise RuntimeError(f"{file_name}: missing invariant: {token}")

    if '@router.get("/warehouse/ledger", response_model=List[WarehouseLedgerItem]' in wh:
        raise RuntimeError("warehouse: legacy list ledger endpoint still exists")
    if 'authFetch(`/warehouse/ledger?location_id=' in main:
        raise RuntimeError("MainInventory: legacy ledger fetch still exists")


def run_dashboard_build() -> None:
    if os.environ.get("WANASAH_SKIP_DASHBOARD_BUILD") == "YES":
        print("DASHBOARD_BUILD=SKIPPED_BY_EXPLICIT_ENV")
        return

    package_json = DASHBOARD / "package.json"
    if not package_json.is_file():
        raise RuntimeError("dashboard/package.json غير موجود.")

    # لا نشغّل npm scripts هنا لأن بعض بيئات Windows تحمل إعداد
    # script-shell=/bin/bash، فيفشل npm رغم أن Node/Vite سليمين.
    # package.json الحالي يعرّف build = "vite build"، لذلك تشغيل
    # Vite مباشرة عبر Node مكافئ وظيفياً ويتجنب أي shell وسيط.
    node = shutil.which("node.exe") or shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js غير موجود في PATH؛ لم يتم اعتماد التعديلات.")

    vite_js = DASHBOARD / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_js.is_file():
        raise RuntimeError(
            "Vite المحلي غير موجود داخل dashboard/node_modules. "
            "نفّذ npm install داخل dashboard أولاً."
        )

    result = subprocess.run(
        [node, str(vite_js), "build"],
        cwd=DASHBOARD,
        text=True,
        capture_output=True,
        shell=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            "Dashboard build failed; all source files will be restored."
        )

    print("DASHBOARD_BUILD=OK")


def main() -> None:
    for name, path in FILES.items():
        if not path.is_file():
            raise SystemExit(f"ERROR: missing file ({name}): {path}")

    originals = {name: path.read_bytes() for name, path in FILES.items()}
    prepared: dict[str, str] = {}

    for name, path in FILES.items():
        text = normalize(originals[name])
        if name == "schemas":
            text = patch_schemas(text)
            ast.parse(text, filename=str(path))
        elif name == "warehouse":
            text = patch_warehouse(text)
            ast.parse(text, filename=str(path))
        elif name == "utils":
            text = patch_utils(text)
            validate_frontend_source(name, text)
        elif name == "main":
            text = patch_main(text)
            validate_frontend_source(name, text)
        elif name == "inbound":
            if 'authenticatedFetch("/warehouse/inbound"' not in text:
                raise RuntimeError("Tab2Inbound.tsx: expected inbound screen marker not found.")
            text = TAB2_INBOUND
            validate_frontend_source(name, text)
        elif name == "ledger":
            if 'export function Tab4Ledger' not in text:
                raise RuntimeError("Tab4Ledger.tsx: expected component marker not found.")
            text = TAB4_LEDGER
            validate_frontend_source(name, text)
        prepared[name] = text

    validate(prepared)

    written: list[str] = []
    temp_paths: list[Path] = []
    try:
        # Syntax-compile Python targets before replacing originals.
        for name in ("schemas", "warehouse"):
            path = FILES[name]
            tmp = path.with_suffix(path.suffix + ".stage6b.tmp")
            tmp.write_text(prepared[name], encoding="utf-8", newline="\n")
            temp_paths.append(tmp)
            py_compile.compile(str(tmp), doraise=True)

        for name, path in FILES.items():
            output = prepared[name].encode("utf-8")
            tmp = path.with_suffix(path.suffix + ".stage6b.write.tmp")
            tmp.write_bytes(output)
            temp_paths.append(tmp)
            os.replace(tmp, path)
            written.append(name)

        # Python import syntax and real Vite build are both mandatory.
        py_compile.compile(str(FILES["schemas"]), doraise=True)
        py_compile.compile(str(FILES["warehouse"]), doraise=True)
        run_dashboard_build()

    except Exception:
        for name in written:
            FILES[name].write_bytes(originals[name])
        raise
    finally:
        for tmp in temp_paths:
            if tmp.exists():
                tmp.unlink()

    print("WAREHOUSE_STAGE6_DASHBOARD_CURSOR_V2_OK")
    print("warehouse.py: legacy GET /warehouse/ledger removed")
    print("warehouse.py: exact indexed reference lookup + cursor response identity hardened")
    print("schemas.py: product_variant_id exposed in ledger item")
    print("MainInventory.tsx: 500-row fake ledger cache removed")
    print("Tab4Ledger.tsx: server-side cursor/search/filter/reference traversal enabled")
    print("Tab2Inbound.tsx: request_id retry safety + batch/expiry contract aligned")
    print("inventoryUtils.ts: backend contract types aligned")


if __name__ == "__main__":
    main()
