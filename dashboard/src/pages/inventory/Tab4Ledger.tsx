import { apiErrorMessage } from "@/lib/apiErrors";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { History, Search, ChevronRight, ChevronLeft, Eye, FileText, Package, RefreshCcw } from "lucide-react";
import { getLedgerBadge } from "./inventoryUtils";
import { absoluteQuantity, addQuantity, compareQuantity, formatCommercialQuantity, formatQuantity } from "./quantity";
import {
  buildLedgerAdjustmentPayload,
  formatLedgerDate,
  parseLedgerMutationResponse,
  parseLedgerPage,
  type LedgerEntry,
} from "./ledger/contracts";
import { Modal } from "@/components/ui/modal";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";

interface Props {
  locationId: number;
  refreshKey: number;
  onInventoryChanged: () => void;
}

const PAGE_SIZE = 20;

type LedgerUiContractError = Error & { code: string };

const ledgerUiContractError = (code: string): never => {
  const error = new Error(code) as LedgerUiContractError;
  error.code = code;
  throw error;
};

export function Tab4Ledger({ locationId, refreshKey, onInventoryChanged }: Props) {
  const authenticatedFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess(locationId);

  const uomLabel = (code: string | null) =>
    code
      ? t(`uom.${code}`, { defaultValue: t("inventoryCommon.unit") })
      : t("inventoryCommon.unit");

  const formatMoney = (value: string, currency: string) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return value;
    try {
      return new Intl.NumberFormat(
        i18n.language.startsWith("ar") ? "ar-JO" : "en-US",
        {
          style: "currency",
          currency,
          minimumFractionDigits: 3,
          maximumFractionDigits: 6,
        },
      ).format(numeric);
    } catch {
      return value;
    }
  };

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
  const [newQty, setNewQty] = useState("0");
  const [adjSubmitting, setAdjSubmitting] = useState(false);

  const requestSequence = useRef(0);
  const pageAbortRef = useRef<AbortController | null>(null);
  const referenceRequestSequence = useRef(0);
  const referenceAbortRef = useRef<AbortController | null>(null);

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
    pageAbortRef.current?.abort();
    const requestController = new AbortController();
    pageAbortRef.current = requestController;
    setLoading(true);

    try {
      const data = parseLedgerPage(await authenticatedFetch(
        buildUrl(cursor),
        { signal: requestController.signal },
      ));
      if (sequence !== requestSequence.current) return;

      setEntries(data.items);
      setNextCursor(data.next_cursor);
      setHasMore(data.has_more);
      setPageIndex(targetPage);

      if (typeof data.total === "number") setTotal(data.total);
      if (targetPage === 0) {
        setAvailableTypes(data.available_types);
      }
    } catch (e: unknown) {
      if (sequence !== requestSequence.current) return;
      if (e instanceof Error && e.name === "AbortError") return;
      setEntries([]);
      setNextCursor(null);
      setHasMore(false);
      setTotal(null);
      toast.error(apiErrorMessage(e, t("inventoryLedger.errors.loadFailed")));
    } finally {
      if (pageAbortRef.current === requestController) {
        pageAbortRef.current = null;
      }
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

  useEffect(() => () => {
    requestSequence.current += 1;
    referenceRequestSequence.current += 1;
    pageAbortRef.current?.abort();
    referenceAbortRef.current?.abort();
  }, []);

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

  const fetchAllByReference = useCallback(async (reference: string, signal: AbortSignal) => {
    const all: LedgerEntry[] = [];
    const movementIds = new Set<number>();
    let cursor: string | null = null;

    for (let page = 0; page < 50; page += 1) {
      const data = parseLedgerPage(await authenticatedFetch(
        buildUrl(cursor, { exactReference: reference, pageSize: 200 }),
        { signal },
      ));

      for (const item of data.items) {
        if (movementIds.has(item.id)) {
          ledgerUiContractError("LEDGER_REFERENCE_DUPLICATE_MOVEMENT");
        }
        movementIds.add(item.id);
      }
      all.push(...data.items);

      if (!data.has_more) return all;
      if (!data.next_cursor) ledgerUiContractError("LEDGER_REFERENCE_CURSOR_INVALID");
      cursor = data.next_cursor;
    }

    ledgerUiContractError("LEDGER_REFERENCE_TOO_LARGE");
  }, [authenticatedFetch, buildUrl]);

  const openReference = async (reference: string) => {
    const sequence = ++referenceRequestSequence.current;
    referenceAbortRef.current?.abort();
    const requestController = new AbortController();
    referenceAbortRef.current = requestController;
    setSelectedReference(reference);
    setDeliveryNoteItems([]);
    setReferenceLoading(true);
    try {
      const items = await fetchAllByReference(reference, requestController.signal);
      if (sequence !== referenceRequestSequence.current) return;
      setDeliveryNoteItems(items);
    } catch (e: unknown) {
      if (sequence !== referenceRequestSequence.current) return;
      if (e instanceof Error && e.name === "AbortError") return;
      toast.error(apiErrorMessage(e, t("inventoryLedger.errors.referenceDetailsFailed")));
      setSelectedReference(null);
    } finally {
      if (referenceAbortRef.current === requestController) {
        referenceAbortRef.current = null;
      }
      if (sequence === referenceRequestSequence.current) setReferenceLoading(false);
    }
  };

  const openAdjustment = async (entry: LedgerEntry) => {
    if (!access.can('ledger.adjust')) {
      toast.error(t("inventoryLedger.errors.adjustmentPermission"));
      return;
    }
    if (!entry.reference) return;
    const sequence = ++referenceRequestSequence.current;
    referenceAbortRef.current?.abort();
    const requestController = new AbortController();
    referenceAbortRef.current = requestController;
    setReferenceLoading(true);
    try {
      const all = await fetchAllByReference(entry.reference, requestController.signal);
      if (sequence !== referenceRequestSequence.current) return;
      const relevant = all.filter((movement) => (
        movement.product_variant_id === entry.product_variant_id
        && (movement.type === "INBOUND_SUPPLIER" || movement.type === "INBOUND_CORRECTION")
      ));
      const net = relevant.reduce((sum, movement) => addQuantity(sum, movement.quantity), "0");
      const safeNet = compareQuantity(net, "0") < 0 ? "0" : net;
      setAdjustingEntry(entry);
      setNewQty(safeNet);
    } catch (e: unknown) {
      if (sequence !== referenceRequestSequence.current) return;
      if (e instanceof Error && e.name === "AbortError") return;
      toast.error(apiErrorMessage(e, t("inventoryLedger.errors.receiptNetFailed")));
    } finally {
      if (referenceAbortRef.current === requestController) {
        referenceAbortRef.current = null;
      }
      if (sequence === referenceRequestSequence.current) setReferenceLoading(false);
    }
  };

  const closeReference = () => {
    referenceRequestSequence.current += 1;
    referenceAbortRef.current?.abort();
    referenceAbortRef.current = null;
    setReferenceLoading(false);
    setSelectedReference(null);
    setDeliveryNoteItems([]);
  };

  return (
    <div className="inventory-view inventory-ledger flex flex-col h-full flex-1 min-h-0 pt-1">
      <div className="inventory-surface inventory-data-panel relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm flex-1 min-h-0">
        <div className="inventory-panel-label absolute -top-3.5 right-6 bg-gradient-to-r from-blue-600 to-indigo-700 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
          <History className="w-4 h-4" /> سجل الحركات {total !== null ? `(${total})` : ""}
        </div>

        <div className="inventory-panel-toolbar p-3 pt-5 border-b border-slate-100 flex flex-col sm:flex-row items-center justify-end gap-3 bg-slate-50 rounded-t-2xl">
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
              maxLength={100}
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
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.batch")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.balanceBefore")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.quantity")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.balanceAfter")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.purchaseCost")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.averageAfter")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">{t("inventoryLedger.supervisor")}</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المرجع</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الملاحظات</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">التاريخ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading && (
                <tr><td colSpan={12} className="text-center py-12 text-slate-400 font-bold">{t("common.loading")}</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan={12} className="text-center py-12 text-slate-400">لا توجد حركات مطابقة</td></tr>
              )}
              {!loading && entries.map((entry) => {
                const badge = getLedgerBadge(entry.type);
                const isNeg = compareQuantity(entry.quantity, "0") < 0;
                const reference = entry.reference || "";
                const displayName = uomLabel(entry.display_uom_code);
                const baseName = uomLabel(entry.base_uom_code);
                const renderBaseQuantity = (value: typeof entry.quantity) =>
                  formatCommercialQuantity(
                    value,
                    displayName,
                    baseName,
                    entry.display_factor_to_base,
                  ).primary;
                const movementQuantity =
                  entry.input_quantity && entry.input_uom_code
                    ? formatQuantity(
                        entry.input_quantity,
                        uomLabel(entry.input_uom_code),
                      )
                    : renderBaseQuantity(absoluteQuantity(entry.quantity));

                return (
                  <tr key={entry.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-lg text-[11px] font-black ${badge.bg} ${badge.text}`}>{badge.label}</span></td>
                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>
                    <td className="px-4 py-3 text-xs font-black text-slate-600">{entry.batch_number || "—"}</td>
                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">
                      {entry.balance_before === null
                        ? "—"
                        : renderBaseQuantity(entry.balance_before)}
                    </td>
                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>
                      {isNeg ? "-" : "+"}{movementQuantity}
                    </td>
                    <td className="px-4 py-3 text-slate-800 font-bold text-xs bg-slate-50/50">{entry.balance_after === null ? "—" : renderBaseQuantity(entry.balance_after)}</td>
                    <td className="px-4 py-3 text-slate-700 font-black text-xs">
                      {entry.input_unit_cost && entry.input_uom_code ? (
                        <>
                          <div>
                            {formatMoney(entry.input_unit_cost, entry.currency_code)} / {uomLabel(entry.input_uom_code)}
                          </div>
                          {entry.total_cost ? (
                            <div className="mt-0.5 text-[10px] font-semibold text-slate-400">
                              {t("inventoryLedger.totalCost")}: {formatMoney(entry.total_cost, entry.currency_code)}
                            </div>
                          ) : null}
                        </>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-black text-xs">
                      {entry.average_cost_after && entry.average_cost_uom_code
                        ? `${formatMoney(entry.average_cost_after, entry.currency_code)} / ${uomLabel(entry.average_cost_uom_code)}`
                        : "—"}
                    </td>
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
                            disabled={referenceLoading || !access.can('ledger.adjust')}
                            onClick={() => { void openAdjustment(entry); }}
                            className="text-xs text-purple-600 bg-purple-50 px-2 py-1 rounded-lg border border-purple-100 disabled:opacity-40"
                          >
                            تعديل
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-[11px] font-semibold whitespace-nowrap" dir="ltr">
                      {formatLedgerDate(entry.date, i18n.resolvedLanguage || i18n.language)}
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
        onClose={closeReference}
        title={`وصل تسليم مجمع: ${selectedReference || ""}`}
        maxWidth="max-w-2xl"
      >
        {referenceLoading ? (
          <div className="py-12 text-center text-sm font-bold text-slate-400">{t("inventoryLedger.loadingReference")}</div>
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
                      <td className="px-4 py-3 text-center font-bold">{compareQuantity(item.quantity, "0") < 0 ? "-" : "+"}{formatQuantity(absoluteQuantity(item.quantity), item.base_uom_code)}</td>
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
                setAdjSubmitting(true);
                try {
                  const payload = buildLedgerAdjustmentPayload(
                    newQty,
                    adjustingEntry,
                    adjPassword,
                  );
                  const response = parseLedgerMutationResponse(await authenticatedFetch(`/warehouse/ledger/${adjustingEntry.id}/adjust`, {
                    method: "POST",
                    body: JSON.stringify(payload),
                  }));
                  toast.success(response.message);
                  setAdjustingEntry(null);
                  setAdjPassword("");
                  onInventoryChanged();
                } catch (e: unknown) {
                  toast.error(apiErrorMessage(e, t("inventoryLedger.errors.adjustmentFailed")));
                } finally {
                  setAdjSubmitting(false);
                }
              }}
              className="flex-1 bg-purple-600 text-white py-2 rounded-xl font-bold hover:bg-purple-700 disabled:opacity-50"
            >
              {adjSubmitting ? t("common.saving") : t("inventoryLedger.confirmAdjustment")}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-purple-50 p-3 rounded-xl border border-purple-100">
            <p className="text-[11px] font-bold text-purple-800">صنف: {adjustingEntry?.product_name}</p>
            <p className="text-[10px] text-purple-600 mt-1">المرجع: {adjustingEntry?.reference}</p>
          </div>
          <div>
            <label className="text-xs font-black text-slate-600">الإجمالي الصحيح بوحدة الأساس ({adjustingEntry?.base_uom_code})</label>
            <input inputMode="decimal" value={newQty} onChange={(e) => setNewQty(e.target.value.replace(/[^0-9.]/g, ""))} className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black outline-none" />
            <p className="mt-1 text-[10px] text-slate-500">الدقة {adjustingEntry?.quantity_scale ?? 0} · الخطوة {adjustingEntry?.quantity_step ?? "1"}</p>
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
