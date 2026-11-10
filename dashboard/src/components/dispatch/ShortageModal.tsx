import { resolveAppLocale } from "@/lib/locale";
import { useTranslation } from "react-i18next";
import { resolveI18nLocale } from "@/lib/locale";
import { useState, useMemo, useRef, useEffect, useId } from "react";
import {
  Minus, Plus, Trash2, Pencil, ChevronDown, ChevronUp,
  Package, AlertTriangle, Clock, X, Eraser,
} from "lucide-react";
import { ShortageProductPicker } from "./ShortageProductPicker";
import { groupText, type GroupIntent } from "@/features/dispatch/shortageGroup/contract";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone, Shop, Shortage } from "@/types/dispatch";
import { dispatchUiText, type DispatchUiKey } from "@/features/dispatch/dispatchUiText";

// ─── Props ────────────────────────────────────────────────────────────────────
interface ShortageModalProps {
  canCreate: boolean;
  canCancel: boolean;
  canEdit: boolean;
  focusShortageId?: string | null;
  isOpen: boolean;
  onClose: () => void;
  zones: Zone[];
  activeShops: Shop[];
  shortageZoneId: string;
  shortageShopId: string;
  onZoneChange: (id: string) => void;
  onShopChange: (id: string) => void;
  productScope: string | null;
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
  onEditShortageGroup: (shopId: string, driverId?: string) => void;
  editingShortageIds: string[];
  onCancelEdit: () => void;
  drivers: { id: string; name: string }[];
  shortageDriverId: string;
  onDriverChange: (id: string) => void;
  groupRecovery: {
    pending: { requestId: string; payload: GroupIntent } | null;
    blocked: boolean;
    restoring: boolean;
    busy: boolean;
    feedback: string | null;
    httpReference: string | null;
    onRetry: () => void;
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function groupByShop(shortages: Shortage[]) {
  const map = new Map<string, {
    shopId: string; shopName: string; zoneName: string;
    driverId: string;
    driverName: string;
    /** Earliest createdAt of items in this group */
    createdAt: string | undefined;
    items: Shortage[];
  }>();
  for (const sh of shortages) {
    const groupKey = `${sh.shopId}:${sh.driverId || ""}`;
    if (!map.has(groupKey)) {
      map.set(groupKey, {
        shopId: sh.shopId,
        shopName: sh.shopName,
        zoneName: sh.zoneName,
        driverId: sh.driverId || "",
        driverName: sh.driverName || "",
        createdAt: sh.createdAt,
        items: [],
      });
    }
    const entry = map.get(groupKey)!;
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
function formatTimestamp(isoStr: string | null | undefined, language: string): string {
  const text = (key: DispatchUiKey, count?: number) => dispatchUiText(language, key, count === undefined ? {} : { count });
  if (!isoStr) return text("shortageNow");
  const safeIso = /(?:Z|[+-]\d{2}:\d{2})$/.test(isoStr) ? isoStr : isoStr + "Z";
  const date = new Date(safeIso);
  if (Number.isNaN(date.getTime())) return text("shortageNow");
  const elapsed = Math.max(0, Date.now() - date.getTime());
  const minutes = Math.floor(elapsed / 60_000);
  const hours = Math.floor(minutes / 60);
  const relative = minutes < 1 ? text("shortageNow") :
    minutes < 60 ? text("shortageMinutes", minutes) :
    hours < 24 ? text("shortageHours", hours) : text("shortageDays", Math.floor(hours / 24));
  const locale = resolveAppLocale(language);
  const clock = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(date);
  const calendar = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(date);
  return `${relative} • ${clock}, ${calendar}`;
}

function isUrgentGroup(createdAt?: string): boolean {
  if (!createdAt) return false;
  return (Date.now() - new Date(createdAt).getTime()) / 60_000 >= 180;
}

// ─── Draft Qty Row ────────────────────────────────────────────────────────────
function DraftRow({
  item, idx, language, onQtyChange, onRemove,
}: {
  item: { productName: string; quantity: number };
  idx: number;
  language: string;
  onQtyChange: (idx: number, qty: number) => void;
  onRemove: (idx: number) => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const text = (key: DispatchUiKey) => dispatchUiText(language, key, { product: item.productName });
  useEffect(() => { if (confirmDelete) confirmRef.current?.focus(); }, [confirmDelete]);
  const cancel = () => {
    setConfirmDelete(false);
    requestAnimationFrame(() => deleteRef.current?.focus());
  };
  return (
    <tr className="group">
      <th scope="row" className="p-3 text-start font-medium text-slate-700 text-sm">{item.productName}</th>
      <td className="p-2 text-center w-36">
        <div className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-2 py-1">
          <button type="button" aria-label={text("shortageDecrease")}
            disabled={item.quantity <= 1}
            onClick={() => onQtyChange(idx, Math.max(1, item.quantity - 1))}
            className="min-h-9 min-w-9 rounded-lg border border-slate-200 bg-white text-slate-600 focus-visible:ring-2 focus-visible:ring-[#1e87bb] disabled:opacity-40">
            <Minus className="mx-auto h-4 w-4" />
          </button>
          <output className="min-w-8 text-center font-bold text-[#1e87bb] text-sm" aria-live="polite">{item.quantity}</output>
          <button type="button" aria-label={text("shortageIncrease")}
            onClick={() => onQtyChange(idx, item.quantity + 1)}
            className="min-h-9 min-w-9 rounded-lg border border-slate-200 bg-white text-slate-600 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
            <Plus className="mx-auto h-4 w-4" />
          </button>
        </div>
      </td>
      <td className="p-2 min-w-16 text-center">
        {confirmDelete ? (
          <div className="flex flex-wrap items-center justify-center gap-1"
            onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); event.preventDefault(); cancel(); } }}>
            <button type="button" ref={confirmRef} onClick={() => onRemove(idx)}
              className="min-h-9 rounded-lg bg-red-600 px-2 text-xs font-bold text-white focus-visible:ring-2 focus-visible:ring-offset-2">
              {text("shortageYes")}
            </button>
            <button type="button" onClick={cancel}
              className="min-h-9 rounded-lg bg-slate-100 px-2 text-xs font-bold text-slate-700 focus-visible:ring-2">
              {text("shortageNo")}
            </button>
          </div>
        ) : (
          <button type="button" ref={deleteRef} onClick={() => setConfirmDelete(true)}
            aria-label={text("shortageRemove")}
            title={text("shortageRemove")}
            className="min-h-9 min-w-9 rounded-lg text-slate-500 hover:bg-red-50 hover:text-red-600 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
            <Trash2 className="mx-auto h-4 w-4" />
          </button>
        )}
      </td>
    </tr>
  );
}

// ─── Shop Accordion Card ──────────────────────────────────────────────────────
function ShopCard({
  focusShortageId, group, language, isBeingEdited, isEditModeActive,
  canEdit, canCancel, onEdit, onDeleteAll, onDeleteOne,
}: {
  focusShortageId?: string | null;
  group: ReturnType<typeof groupByShop>[number];
  language: string;
  isBeingEdited: boolean;
  isEditModeActive: boolean;
  canEdit: boolean;
  canCancel: boolean;
  onEdit: () => void;
  onDeleteAll: () => void;
  onDeleteOne: (id: string) => void;
}) {
  const listId = useId();
  const [open, setOpen] = useState(() => group.items.some(item => item.id === focusShortageId));
  const [confirm, setConfirm] = useState<{ kind: "all" | "one"; id?: string; product?: string } | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const previousActionRef = useRef<HTMLElement | null>(null);
  const text = (key: DispatchUiKey, values: Record<string, string | number> = {}) =>
    dispatchUiText(language, key, { shop: group.shopName, ...values });
  useEffect(() => {
    if (focusShortageId && group.items.some(item => item.id === focusShortageId)) setOpen(true);
  }, [focusShortageId, group.items]);
  useEffect(() => { if (confirm) confirmRef.current?.focus(); }, [confirm]);
  const requestDelete = (event: React.MouseEvent<HTMLButtonElement>, next: typeof confirm) => {
    previousActionRef.current = event.currentTarget;
    setConfirm(next);
  };
  const cancelDelete = () => {
    setConfirm(null);
    requestAnimationFrame(() => previousActionRef.current?.isConnected && previousActionRef.current.focus());
  };
  const applyDelete = () => {
    if (!confirm) return;
    if (confirm.kind === "all") onDeleteAll();
    else if (confirm.id) onDeleteOne(confirm.id);
    setConfirm(null);
  };

  const urgent = isUrgentGroup(group.createdAt);
  const border = isBeingEdited ? "border-amber-300 ring-2 ring-amber-200" :
    urgent ? "border-red-200" : "border-slate-200";
  const bg = isBeingEdited ? "bg-amber-50" : urgent ? "bg-red-50" : "bg-slate-50";
  return (
    <section className={`overflow-hidden rounded-2xl border shadow-sm ${border}`}>
      <div className={`flex flex-wrap items-center justify-between gap-2 px-3 py-3 sm:px-5 ${bg}`}>
        <button type="button" aria-controls={listId} aria-expanded={open}
          aria-label={text(open ? "shortageCollapse" : "shortageExpand")}
          onClick={() => setOpen(value => !value)}
          className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-lg text-start focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
          <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#1e87bb]/10">
            {isBeingEdited ? <Pencil className="h-4 w-4 text-amber-600" /> :
              urgent ? <AlertTriangle className="h-4 w-4 text-red-500" /> :
                <Package className="h-4 w-4 text-[#1e87bb]" />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-2">
              <span className="break-words text-sm font-bold text-slate-800">{group.shopName}</span>
              {isBeingEdited && <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-bold text-white">{text("shortageEditing")}</span>}
              {!isBeingEdited && urgent && <span className="rounded-full bg-red-600 px-2 py-0.5 text-[10px] font-bold text-white">{text("shortageUrgent")}</span>}
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
              <span>{group.zoneName}</span><span aria-hidden="true">•</span>
              <span className={group.driverName ? "font-semibold text-[#1e87bb]" : "italic"}>
                {group.driverName || text("shortageNoDriver")}
              </span>
              <span aria-hidden="true">•</span>
              <Clock aria-hidden="true" className="h-3 w-3" />
              <span>{formatTimestamp(group.createdAt, language)}</span>
            </span>
          </span>
          {open ? <ChevronUp aria-hidden="true" className="h-4 w-4 shrink-0" /> :
            <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0" />}
        </button>
        <div className="flex flex-wrap items-center gap-2">
          {canEdit && !isBeingEdited && (
            <button type="button" onClick={onEdit} aria-label={text("shortageEdit")}
              className="min-h-11 rounded-xl border border-amber-200 bg-amber-50 px-3 text-xs font-bold text-amber-800 hover:bg-amber-100 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
              <Pencil aria-hidden="true" className="me-1 inline h-3 w-3" />{text("shortageEdit")}
            </button>
          )}
          {canCancel && !isEditModeActive && (
            <button type="button" onClick={event => requestDelete(event, { kind: "all" })}
              aria-label={text("shortageDeleteAll")}
              className="min-h-11 rounded-xl border border-red-200 bg-red-50 px-3 text-xs font-bold text-red-700 hover:bg-red-100 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
              <Trash2 aria-hidden="true" className="me-1 inline h-3 w-3" />{text("shortageDeleteAll")}
            </button>
          )}
        </div>
      </div>
      {confirm && (
        <div role="group" aria-label={text("shortageDeleteConfirm")}
          onKeyDown={event => {
            if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancelDelete(); }
          }}
          className="flex flex-wrap items-center gap-2 border-t border-red-100 bg-red-50 px-3 py-2 sm:px-5">
          <p className="min-w-0 flex-1 text-xs font-semibold text-red-800">
            {confirm.kind === "all" ? text("shortageDeleteAll") :
              text("shortageDeleteOne", { product: confirm.product ?? "" })}
          </p>
          <button type="button" ref={confirmRef} onClick={applyDelete}
            className="min-h-11 rounded-lg bg-red-700 px-3 text-xs font-bold text-white focus-visible:ring-2 focus-visible:ring-offset-2">
            {text("shortageYes")}
          </button>
          <button type="button" onClick={cancelDelete}
            className="min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-xs font-bold text-slate-800 focus-visible:ring-2">
            {text("shortageNo")}
          </button>
        </div>
      )}
      <div id={listId} hidden={!open} className="divide-y divide-slate-100 bg-white">
        {group.items.map((item, idx) => (
          <div key={item.id} data-shortage-id={item.id}
            className={`group flex items-center gap-2 px-3 py-2 sm:gap-3 sm:px-5 ${item.id === focusShortageId ? "bg-amber-50 ring-2 ring-inset ring-amber-300" : ""}`}>
            <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-500">{idx + 1}</span>
            <span className="min-w-0 flex-1 break-words text-sm font-semibold text-slate-700">{item.productName}</span>
            <span className="min-w-10 shrink-0 rounded-xl border border-[#1e87bb]/20 bg-[#1e87bb]/10 px-2 py-1 text-center text-sm font-bold text-[#1e87bb]">{item.quantity}</span>
            {canCancel && (
              <button type="button" onClick={event => requestDelete(event, { kind: "one", id: item.id, product: item.productName })}
                aria-label={text("shortageDeleteOne", { product: item.productName })}
                className="min-h-11 min-w-11 shrink-0 rounded-lg text-slate-600 hover:bg-red-50 hover:text-red-700 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
                <Trash2 aria-hidden="true" className="mx-auto h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export function ShortageModal({
  canCreate,
  canCancel,
  canEdit,
  focusShortageId,
  isOpen,
  onClose,
  zones,
  activeShops,
  shortageZoneId,
  shortageShopId,
  onZoneChange,
  onShopChange,
  productScope,
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
  groupRecovery,
}: ShortageModalProps) {
  const { t, i18n } = useTranslation();
  // +++ الكي الجراحي: تغليف الدالة بـ useMemo لمنع إعادة تجميع المصفوفة مع كل رندرة +++
  const grouped = useMemo(() => groupByShop(shortages), [shortages]);
  const isEditMode = editingShortageIds.length > 0;
  const qtyRef = useRef<HTMLInputElement>(null);
  const text = (key: DispatchUiKey, values: Record<string, string | number> = {}) =>
    dispatchUiText(i18n.language, key, values);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={text("shortageTitle")}
      initialFocusRef={qtyRef}
      maxWidth="max-w-5xl"
    >
      <div className="space-y-6">
        {canCancel && (groupRecovery.pending || groupRecovery.blocked || groupRecovery.feedback || groupRecovery.restoring) && (
          <section role="status" data-testid="shortage-group-recovery"
            dir={i18n.dir()}
            className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 space-y-2">
            <p className="font-semibold">{groupRecovery.blocked
              ? groupText(i18n.language, "blocked")
              : groupRecovery.pending ? groupText(i18n.language, "pending")
                : groupRecovery.restoring ? groupText(i18n.language, "inProgress") : groupRecovery.feedback}</p>
            {groupRecovery.feedback && groupRecovery.pending && (
              <p role="alert">{groupRecovery.feedback}</p>
            )}
            {groupRecovery.pending && (
              <div className="flex flex-wrap items-center gap-2">
                {groupRecovery.httpReference && (
                  <span className="text-xs" dir="auto" data-testid="shortage-group-http-ref">
                    {groupText(i18n.language, "serverReference")}: {groupRecovery.httpReference}
                  </span>
                )}
                <span className="text-xs" dir="auto">
                  {groupText(i18n.language, "reference")}: {groupRecovery.pending.requestId}
                </span>
                <span className="text-xs font-bold">
                  {groupText(i18n.language,
                    groupRecovery.pending.payload.action === "delete" ? "delete" : "edit")}
                </span>
                <button type="button" onClick={groupRecovery.onRetry}
                  disabled={groupRecovery.busy || groupRecovery.restoring || groupRecovery.blocked}
                  className="rounded-lg bg-amber-800 px-3 py-2 text-xs font-bold text-white disabled:opacity-50">
                  {groupRecovery.busy ? groupText(i18n.language, "inProgress")
                    : groupText(i18n.language, "retry")}
                </button>
              </div>
            )}
          </section>
        )}

        {/* ═══════════════════════════════════════════════════
            INPUT / EDIT SECTION — visually separated (#1)
        ═══════════════════════════════════════════════════ */}
        {canCreate && <fieldset disabled={Boolean(groupRecovery.pending || groupRecovery.blocked ||
          groupRecovery.busy || groupRecovery.restoring)}
          className={`rounded-2xl border shadow-sm ${isEditMode
          ? "bg-amber-50 border-amber-200 shadow-amber-100"
          : "bg-slate-50 border-slate-200"
        }`}>

          {/* Edit mode banner (#5) */}
          {isEditMode && (
            <div className="flex items-center justify-between bg-amber-100 border-b border-amber-200 rounded-t-2xl px-5 py-3">
              <div className="flex items-center gap-2 text-amber-800 text-sm font-bold">
                <Pencil className="w-4 h-4" />
                {text("shortageEditMode")}
              </div>
            </div>
          )}

          <div className="p-5 space-y-4">
            {/* Selects */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <CustomSelect
                label={text("shortageZone")}
                options={zones.map(z => ({ id: z.id, label: z.name }))}
                value={shortageZoneId}
                onChange={onZoneChange}
                disabled={isEditMode}
              />
              <CustomSelect
                label={text("shortageShop")}
                options={activeShops.filter(s => s.zoneId === shortageZoneId).map(s => ({ id: s.id, label: s.name }))}
                value={shortageShopId}
                onChange={onShopChange}
                disabled={isEditMode || !shortageZoneId}
              />
              <CustomSelect
                label={text("shortageDriver")}
                options={drivers.map(d => ({ id: d.id, label: d.name }))}
                value={shortageDriverId}
                onChange={onDriverChange}
                disabled={isEditMode}
              />
            </div>

            {/* Product + Qty picker */}
            <div className="grid grid-cols-1 sm:grid-cols-5 gap-3 items-end bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
              <div className="sm:col-span-2 flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-slate-600">{t("dispatchProductSearch.product")}</span>
                <ShortageProductPicker scope={productScope} selected={newShortage.productId && newShortage.productName
                  ? { id: newShortage.productId, name: newShortage.productName } : null} drafted={shortageDraft}
                  onSelect={(productId, productName) => onNewShortageChange({ ...newShortage, productId, productName })} />
              </div>
              <div className="sm:col-span-2 flex flex-col gap-1.5">
                <label htmlFor="dispatch-shortage-qty" className="text-xs font-semibold text-slate-600">{text("shortageQuantity")}</label>
                <input
                  id="dispatch-shortage-qty"
                  ref={qtyRef}
                  aria-label={text("shortageQtyName")}
                  type="number" min="1" step="1" inputMode="numeric"
                  value={newShortage.quantity || 0}
                  onChange={e => onNewShortageChange({ ...newShortage, quantity: parseInt(e.target.value) || 0 })}
                  onFocus={e => e.target.select()}
                  className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-center outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                />
              </div>
              <button type="button"
                onClick={onAddProductToDraft}
                disabled={!shortageShopId || !newShortage.productId || !Number.isSafeInteger(newShortage.quantity) || (newShortage.quantity ?? 0) < 1}
                className="h-[46px] rounded-xl font-bold text-sm bg-[#1e87bb] text-white hover:bg-[#156a94] transition-colors shadow-lg shadow-[#1e87bb]/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t("dispatchProductSearch.add")}
              </button>
            </div>

            {/* Draft table — only shown when draft has items */}
            {shortageDraft.length > 0 && (
              <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                {/* Draft table header with "Clear" button (#2) */}
                <div className="flex items-center justify-between px-4 py-2 bg-slate-50 border-b border-slate-100">
                  <span className="text-xs font-bold text-slate-600">{text("shortageDraftList", { count: shortageDraft.length })}</span>
                  <button type="button"
                    onClick={onClearDraft}
                    className="flex items-center gap-1 text-xs font-bold text-slate-400 hover:text-red-500 transition-colors"
                    title={text("shortageClear")}
                  >
                    <Eraser className="w-3.5 h-3.5" /> {text("shortageClear")}
                  </button>
                </div>
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-100">
                    <tr>
                      <th className="text-start p-3 text-slate-500 font-bold text-xs">{text("shortageProduct")}</th>
                      <th className="text-center p-3 text-slate-500 font-bold text-xs w-36">{text("shortageQuantity")}</th>
                      <th className="w-24 p-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {shortageDraft.map((item, idx) => (
                      <DraftRow
                        key={idx}
                        item={item}
                        idx={idx}
                        language={i18n.language}
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
              <button type="button"
                onClick={onConfirmShortages}
                disabled={shortageDraft.length === 0 || !shortageShopId || !shortageZoneId}
                className={`flex-1 py-3 rounded-xl font-bold transition-colors shadow-lg disabled:opacity-50 disabled:cursor-not-allowed text-white ${
                  isEditMode
                    ? "bg-amber-500 hover:bg-amber-600 shadow-amber-500/20"
                    : "bg-emerald-500 hover:bg-emerald-600 shadow-emerald-500/20"
                }`}
              >
                {text(isEditMode ? "shortageSaveEdit" : "shortageConfirm", { count: shortageDraft.length })}
              </button>
              {isEditMode && (
                <button type="button"
                  onClick={onCancelEdit}
                  className="flex items-center gap-2 px-5 py-3 rounded-xl border border-slate-300 text-slate-600 text-sm font-bold hover:bg-red-50 hover:text-red-600 hover:border-red-200 transition-all"
                >
                  <X className="w-4 h-4" /> {text("shortageCancelEdit")}
                </button>
              )}
            </div>
          </div>
        </fieldset>}

        {/* ═══════════════════════════════════════════════════
            PENDING LIST — visually distinct from input section
        ═══════════════════════════════════════════════════ */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <div className="w-1 h-5 bg-[#1e87bb] rounded-full" />
              <h3 className="text-sm font-bold text-slate-700">
                {text("shortagePending")}
              </h3>
              {grouped.length > 0 && (
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500 text-white text-[10px] font-bold">
                  {grouped.length}
                </span>
              )}
            </div>
            <span className="text-xs text-slate-400">{text("shortageTotal", { count: shortages.length })}</span>
          </div>

          {grouped.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-14 rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/60">
              <Package className="w-10 h-10 text-slate-200" />
              <p className="text-slate-400 text-sm font-medium">{text("shortageNone")}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {focusShortageId && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm font-bold" dir={i18n.dir()}>
                {t("archiveOwners.shortageFocus", { id: new Intl.NumberFormat(resolveI18nLocale(i18n)).format(Number(focusShortageId)) })}
              </p>}
              {grouped.map(group => (
                <ShopCard
                  focusShortageId={focusShortageId}
                  canEdit={canEdit}
                  canCancel={canCancel}
                  key={`${group.shopId}:${group.driverId}`}
                  group={group}
                  language={i18n.language}
                  isBeingEdited={group.items.some(it => editingShortageIds.includes(it.id))}
                  isEditModeActive={isEditMode}
                  onEdit={() => onEditShortageGroup(group.shopId, group.driverId)}
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
