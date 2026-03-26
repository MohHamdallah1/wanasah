import { useState } from "react";
import {
  Minus, Plus, Trash2, Pencil, ChevronDown, ChevronUp,
  Package, AlertTriangle, Clock, X, Eraser,
} from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone, Shop, Shortage } from "@/types/dispatch";

// ─── Props ────────────────────────────────────────────────────────────────────
interface ShortageModalProps {
  isOpen: boolean;
  onClose: () => void;
  zones: Zone[];
  activeShops: Shop[];
  shortageZoneId: string;
  shortageShopId: string;
  onZoneChange: (id: string) => void;
  onShopChange: (id: string) => void;
  products: { id: string; name: string }[];
  newShortage: Partial<Shortage>;
  onNewShortageChange: (shortage: Partial<Shortage>) => void;
  shortageDraft: { productId: string; productName: string; quantity: number }[];
  onAddProductToDraft: () => void;
  onRemoveProductFromDraft: (index: number) => void;
  onUpdateDraftQty: (index: number, qty: number) => void;
  onClearDraft: () => void;
  onConfirmShortages: () => void;
  shortages: Shortage[];
  onDeleteShortage: (id: string) => void;
  onDeleteShortageGroup: (ids: string[]) => void;
  onEditShortageGroup: (shopId: string) => void;
  editingShortageIds: string[];
  onCancelEdit: () => void;
  drivers: { id: string; name: string }[];
  shortageDriverId: string;
  onDriverChange: (id: string) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function groupByShop(shortages: Shortage[]) {
  const map = new Map<string, {
    shopId: string; shopName: string; zoneName: string;
    driverName: string;
    /** Earliest createdAt of items in this group */
    createdAt: string | undefined;
    items: Shortage[];
  }>();
  for (const sh of shortages) {
    if (!map.has(sh.shopId)) {
      map.set(sh.shopId, {
        shopId: sh.shopId,
        shopName: sh.shopName,
        zoneName: sh.zoneName,
        driverName: sh.driverName || "",
        createdAt: sh.createdAt,
        items: [],
      });
    }
    const entry = map.get(sh.shopId)!;
    entry.items.push(sh);
    // keep the earliest timestamp
    if (sh.createdAt && (!entry.createdAt || sh.createdAt < entry.createdAt)) {
      entry.createdAt = sh.createdAt;
    }
    // driver name from any item (first non-empty wins)
    if (!entry.driverName && sh.driverName) {
      entry.driverName = sh.driverName;
    }
  }
  return Array.from(map.values());
}

/** Arabic human-readable relative time + clock HH:MM · date */
function formatTimestamp(isoStr?: string | null): string {
  if (!isoStr) return "الآن";
  const date = new Date(isoStr);
  if (isNaN(date.getTime())) return "الآن";

  const diffMs = Date.now() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHrs = Math.floor(diffMins / 60);

  let relative: string;
  if (diffMins < 1) relative = "الآن";
  else if (diffMins < 60) relative = `منذ ${diffMins} دقيقة`;
  else if (diffHrs < 24) relative = `منذ ${diffHrs} ساعة`;
  else relative = `منذ ${Math.floor(diffHrs / 24)} يوم`;

  const timeStr = date.toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit", hour12: true });
  const dateStr = date.toLocaleDateString("ar-EG", { day: "numeric", month: "short" });

  return `${relative}  •  ${timeStr}، ${dateStr}`;
}

function isUrgentGroup(createdAt?: string): boolean {
  if (!createdAt) return false;
  return (Date.now() - new Date(createdAt).getTime()) / 60_000 >= 180;
}

// ─── Draft Qty Row ────────────────────────────────────────────────────────────
function DraftRow({
  item,
  idx,
  onQtyChange,
  onRemove,
}: {
  item: { productName: string; quantity: number };
  idx: number;
  onQtyChange: (idx: number, qty: number) => void;
  onRemove: (idx: number) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <tr className="group">
      <td className="p-3 font-medium text-slate-700 text-sm">{item.productName}</td>
      <td className="p-3 text-center w-36">
        <div className="inline-flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-xl px-2 py-1">
          <button
            onClick={() => onQtyChange(idx, Math.max(1, item.quantity - 1))}
            className="w-6 h-6 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-500 hover:bg-red-50 hover:text-red-500 hover:border-red-200 transition-all"
          >
            <Minus className="w-3 h-3" />
          </button>
          <span className="w-8 text-center font-bold text-[#1e87bb] text-sm">{item.quantity}</span>
          <button
            onClick={() => onQtyChange(idx, item.quantity + 1)}
            className="w-6 h-6 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-500 hover:bg-emerald-50 hover:text-emerald-500 hover:border-emerald-200 transition-all"
          >
            <Plus className="w-3 h-3" />
          </button>
        </div>
      </td>
      <td className="p-3 w-12 text-center">
        {confirmDelete ? (
          <div className="flex items-center gap-1 justify-center">
            <button
              onClick={() => onRemove(idx)}
              className="text-[10px] font-bold bg-red-500 text-white px-2 py-1 rounded-lg hover:bg-red-600 transition-all"
            >
              تأكيد
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-[10px] font-bold bg-slate-100 text-slate-600 px-2 py-1 rounded-lg hover:bg-slate-200 transition-all"
            >
              لا
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all"
            title="حذف هذا المنتج"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </td>
    </tr>
  );
}

// ─── Shop Accordion Card ──────────────────────────────────────────────────────
function ShopCard({
  group,
  isBeingEdited,
  isEditModeActive,
  onEdit,
  onDeleteAll,
  onDeleteOne,
}: {
  group: ReturnType<typeof groupByShop>[number];
  isBeingEdited: boolean;
  isEditModeActive: boolean;
  onEdit: () => void;
  onDeleteAll: () => void;
  onDeleteOne: (id: string) => void;
}) {
  const [open, setOpen] = useState(false); // collapsed by default (#1)
  const urgent = isUrgentGroup(group.createdAt);

  const borderCls = isBeingEdited
    ? "border-amber-300 ring-2 ring-amber-200 shadow-amber-100 shadow-md"
    : urgent
      ? "border-red-200 shadow-red-100 shadow-md"
      : "border-slate-200 shadow-sm";

  const headerBg = isBeingEdited
    ? "bg-gradient-to-l from-amber-50 to-yellow-50"
    : urgent
      ? "bg-gradient-to-l from-red-50 to-orange-50"
      : "bg-gradient-to-l from-slate-50 to-white";

  const iconBg = isBeingEdited ? "bg-amber-100" : urgent ? "bg-red-100" : "bg-[#1e87bb]/10";

  return (
    <div className={`rounded-2xl border overflow-hidden transition-all ${borderCls}`}>
      {/* Header */}
      <div
        className={`flex items-center justify-between px-5 py-3.5 cursor-pointer select-none transition-colors ${headerBg}`}
        onClick={() => setOpen(p => !p)}
      >
        {/* Left: icon + info */}
        <div className="flex items-center gap-3 min-w-0">
          <div className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center ${iconBg}`}>
            {isBeingEdited
              ? <Pencil className="w-4 h-4 text-amber-600" />
              : urgent
                ? <AlertTriangle className="w-4 h-4 text-red-500" />
                : <Package className="w-4 h-4 text-[#1e87bb]" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="font-bold text-slate-800 text-sm">{group.shopName}</p>
              {isBeingEdited && (
                <span className="text-[10px] font-bold bg-amber-500 text-white px-2 py-0.5 rounded-full">قيد التعديل</span>
              )}
              {!isBeingEdited && urgent && (
                <span className="text-[10px] font-bold bg-red-500 text-white px-2 py-0.5 rounded-full animate-pulse">عاجل!</span>
              )}
            </div>
            {/* Sub-line: zone • driver • time */}
            <p className="text-[11px] text-slate-400 mt-0.5 flex items-center gap-1.5 flex-wrap">
              <span>{group.zoneName}</span>
              <span className="text-slate-300">•</span>
              {/* Rule #7: driver name */}
              <span className={group.driverName ? "text-[#1e87bb] font-semibold" : "text-slate-400 italic"}>
                {group.driverName || "بدون مندوب"}
              </span>
              <span className="text-slate-300">•</span>
              <span className="inline-flex items-center gap-1">
                <Clock className="w-2.5 h-2.5" />
                {/* Rule #6: shop-level timestamp, never per-product */}
                {formatTimestamp(group.createdAt)}
              </span>
            </p>
          </div>
        </div>

        {/* Right: action buttons */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {!isBeingEdited && (
            <button
              onClick={e => { e.stopPropagation(); onEdit(); }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-50 hover:bg-amber-100 border border-amber-200 text-amber-700 text-xs font-bold transition-all"
            >
              <Pencil className="w-3 h-3" /> تعديل
            </button>
          )}
          {/* Rule #5: hide Delete All when in edit mode */}
          {!isEditModeActive && (
            <button
              onClick={e => { e.stopPropagation(); onDeleteAll(); }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-red-50 hover:bg-red-100 border border-red-200 text-red-600 text-xs font-bold transition-all"
            >
              <Trash2 className="w-3 h-3" /> حذف الكل
            </button>
          )}
          <button
            onClick={e => { e.stopPropagation(); setOpen(p => !p); }}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all"
          >
            {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Product list */}
      {open && (
        <div className="divide-y divide-slate-50 bg-white">
          {group.items.map((item, idx) => (
            <div
              key={item.id}
              className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/80 transition-colors group"
            >
              <span className="flex-shrink-0 w-5 h-5 rounded-full bg-slate-100 text-slate-400 text-[10px] font-bold flex items-center justify-center">
                {idx + 1}
              </span>
              <span className="flex-1 text-sm font-semibold text-slate-700">{item.productName}</span>
              <span className="flex-shrink-0 min-w-[52px] text-center px-3 py-1 rounded-xl bg-[#1e87bb]/10 text-[#1e87bb] text-sm font-bold border border-[#1e87bb]/20">
                {item.quantity}
              </span>
              <button
                onClick={() => onDeleteOne(item.id)}
                className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 transition-all flex-shrink-0"
                title="حذف هذا المنتج فقط"
              >
                <Minus className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export function ShortageModal({
  isOpen,
  onClose,
  zones,
  activeShops,
  shortageZoneId,
  shortageShopId,
  onZoneChange,
  onShopChange,
  products,
  newShortage,
  onNewShortageChange,
  shortageDraft,
  onAddProductToDraft,
  onRemoveProductFromDraft,
  onUpdateDraftQty,
  onClearDraft,
  onConfirmShortages,
  shortages,
  onDeleteShortage,
  onDeleteShortageGroup,
  onEditShortageGroup,
  editingShortageIds,
  onCancelEdit,
  drivers,
  shortageDriverId,
  onDriverChange,
}: ShortageModalProps) {
  const grouped = groupByShop(shortages);
  const isEditMode = editingShortageIds.length > 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="📦 طلبات ونواقص المحلات"
      maxWidth="max-w-5xl"
    >
      <div className="space-y-6">

        {/* ═══════════════════════════════════════════════════
            INPUT / EDIT SECTION — visually separated (#1)
        ═══════════════════════════════════════════════════ */}
        <div className={`rounded-2xl border shadow-sm ${isEditMode
          ? "bg-amber-50 border-amber-200 shadow-amber-100"
          : "bg-slate-50 border-slate-200"
        }`}>

          {/* Edit mode banner (#5) */}
          {isEditMode && (
            <div className="flex items-center justify-between bg-amber-100 border-b border-amber-200 rounded-t-2xl px-5 py-3">
              <div className="flex items-center gap-2 text-amber-800 text-sm font-bold">
                <Pencil className="w-4 h-4" />
                وضع التعديل — عدّل المنتجات والكميات ثم اضغط "حفظ التعديلات"
              </div>
            </div>
          )}

          <div className="p-5 space-y-4">
            {/* Selects */}
            <div className="grid grid-cols-3 gap-4">
              <CustomSelect
                label="المنطقة"
                options={zones.map(z => ({ id: z.id, label: z.name }))}
                value={shortageZoneId}
                onChange={onZoneChange}
              />
              <CustomSelect
                label="المحل"
                options={activeShops.filter(s => s.zoneId === shortageZoneId).map(s => ({ id: s.id, label: s.name }))}
                value={shortageShopId}
                onChange={onShopChange}
                disabled={!shortageZoneId}
              />
              <CustomSelect
                label="توجيه الطلب للمندوب"
                options={drivers.map(d => ({ id: d.id, label: d.name }))}
                value={shortageDriverId}
                onChange={onDriverChange}
              />
            </div>

            {/* Product + Qty picker */}
            <div className="grid grid-cols-5 gap-3 items-end bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <div className="col-span-2 flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-slate-600">المنتج</span>
                <select
                  value={newShortage.productName}
                  onChange={e => onNewShortageChange({ ...newShortage, productName: e.target.value })}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20 transition-all"
                >
                  {products.map(prod => (
                    <option key={prod.id} value={prod.name}>{prod.name}</option>
                  ))}
                </select>
              </div>
              <div className="col-span-2 flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-slate-600">الكمية</span>
                <input
                  type="number"
                  value={newShortage.quantity || 0}
                  onChange={e => onNewShortageChange({ ...newShortage, quantity: parseInt(e.target.value) || 0 })}
                  onFocus={e => e.target.select()}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-center outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                />
              </div>
              <button
                onClick={onAddProductToDraft}
                disabled={!shortageShopId}
                className="h-[46px] rounded-xl font-bold text-sm bg-[#1e87bb] text-white hover:bg-[#156a94] transition-colors shadow-lg shadow-[#1e87bb]/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                + إضافة
              </button>
            </div>

            {/* Draft table — only shown when draft has items */}
            {shortageDraft.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                {/* Draft table header with "Clear" button (#2) */}
                <div className="flex items-center justify-between px-4 py-2 bg-slate-50 border-b border-slate-100">
                  <span className="text-xs font-bold text-slate-600">قائمة المنتجات ({shortageDraft.length})</span>
                  <button
                    onClick={onClearDraft}
                    className="flex items-center gap-1 text-xs font-bold text-slate-400 hover:text-red-500 transition-colors"
                    title="تصفير كل المنتجات"
                  >
                    <Eraser className="w-3.5 h-3.5" /> تصفير
                  </button>
                </div>
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-100">
                    <tr>
                      <th className="text-start p-3 text-slate-500 font-bold text-xs">المنتج</th>
                      <th className="text-center p-3 text-slate-500 font-bold text-xs w-36">الكمية</th>
                      <th className="w-24 p-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {shortageDraft.map((item, idx) => (
                      <DraftRow
                        key={idx}
                        item={item}
                        idx={idx}
                        onQtyChange={onUpdateDraftQty}
                        onRemove={onRemoveProductFromDraft}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Confirm row — confirm button + cancel-edit button (#5) */}
            <div className={`flex items-center gap-3 ${isEditMode ? "flex-row-reverse" : ""}`}>
              <button
                onClick={onConfirmShortages}
                disabled={shortageDraft.length === 0}
                className={`flex-1 py-3 rounded-xl font-bold transition-colors shadow-lg disabled:opacity-50 disabled:cursor-not-allowed text-white ${
                  isEditMode
                    ? "bg-amber-500 hover:bg-amber-600 shadow-amber-500/20"
                    : "bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20"
                }`}
              >
                {isEditMode
                  ? `✅ حفظ التعديلات (${shortageDraft.length} منتجات)`
                  : `تأكيد الطلب وحفظ (${shortageDraft.length})`}
              </button>
              {isEditMode && (
                <button
                  onClick={onCancelEdit}
                  className="flex items-center gap-2 px-5 py-3 rounded-xl border border-slate-300 text-slate-600 text-sm font-bold hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-all"
                >
                  <X className="w-4 h-4" /> إلغاء التعديل
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            PENDING LIST — visually distinct from input section
        ═══════════════════════════════════════════════════ */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <div className="w-1 h-5 bg-[#1e87bb] rounded-full" />
              <h3 className="text-sm font-bold text-slate-700">
                الطلبات المعلقة
              </h3>
              {grouped.length > 0 && (
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500 text-white text-[10px] font-bold">
                  {grouped.length}
                </span>
              )}
            </div>
            <span className="text-xs text-slate-400">{shortages.length} منتج إجمالاً</span>
          </div>

          {grouped.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-14 rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/60">
              <Package className="w-10 h-10 text-slate-200" />
              <p className="text-slate-400 text-sm font-medium">لا توجد طلبات معلقة</p>
            </div>
          ) : (
            <div className="space-y-3">
              {grouped.map(group => (
                <ShopCard
                  key={group.shopId}
                  group={group}
                  isBeingEdited={group.items.some(it => editingShortageIds.includes(it.id))}
                  isEditModeActive={isEditMode}
                  onEdit={() => onEditShortageGroup(group.shopId)}
                  onDeleteAll={() => onDeleteShortageGroup(group.items.map(it => it.id))}
                  onDeleteOne={id => onDeleteShortage(id)}
                />
              ))}
            </div>
          )}
        </div>

      </div>
    </Modal>
  );
}
