import { useCallback, useEffect, useRef, useState } from "react";
import type { TFunction } from "i18next";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  captureDashboardSession, isDashboardSessionCurrent, subscribeDashboardSession,
} from "@/lib/authStorage";
import { createInventoryTabNavigationState } from "@/features/inventory/navigation";
import { useNavigate } from "react-router-dom";
import { LedgerCostEvidence } from "./LedgerCostEvidence";
import type { LedgerEntry } from "./contracts";
import { formatLedgerDate } from "./contracts";
import { ledgerMovementLabel } from "./ledgerI18n";
import { ledgerLocationEvidence, ledgerSignedQuantity } from "./ledgerPresentation";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import {
  buildLedgerOperationUrl, parseLedgerOperationChildPage,
  type LedgerOperation, type LedgerOperationChild,
} from "./operationContracts";
import { ledgerOperationKindLabel } from "./LedgerOperationRows";
import { useLedgerWindow } from "./useLedgerWindow";

interface Props {
  operation: LedgerOperation;
  locationId: number;
  language: string;
  locale: string;
  t: TFunction;
  search: string;
  filterType: string;
  exactReference: string | null;
  onClose: () => void;
  onDenied: () => void;
  onOpenReference: (entry: LedgerEntry) => void;
  onAdjust: (entry: LedgerEntry) => void;
  canAdjust: boolean;
}

/** Bounded, lazy, separately authorized original movement evidence. */
export function LedgerOperationDetails({
  operation, locationId, language, locale, t, search, filterType, exactReference,
  onClose, onDenied, onOpenReference, onAdjust, canAdjust,
}: Props) {
  const ar = language.toLowerCase().startsWith("ar");
  const navigate = useNavigate();
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<LedgerOperationChild[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const cursorRef = useRef<string | null>(null);
  const idsRef = useRef(new Set<number>());
  const cursorSeen = useRef(new Set<string>());
  const pending = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const sessionRef = useRef(captureDashboardSession());
  const deniedRef = useRef(onDenied);
  deniedRef.current = onDenied;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const load = useCallback(async (cursor: string | null) => {
    if (pending.current || !alive.current || !isDashboardSessionCurrent(sessionRef.current)) return;
    pending.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    if (cursor === null) setLoading(true);
    else setLoadingMore(true);
    setError(false);
    try {
      const data = parseLedgerOperationChildPage(await authFetch(buildLedgerOperationUrl({
        locationId, groupKey: operation.group_key, cursor, limit: 50,
        search: exactReference === null ? search : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }), operation.group_key);
      if (!alive.current || !isDashboardSessionCurrent(sessionRef.current)) return;
      if (data.has_more && (!data.next_cursor || cursorSeen.current.has(data.next_cursor)))
        throw new Error("LEDGER_CHILD_CURSOR_STALLED");
      if (data.has_more && data.next_cursor) cursorSeen.current.add(data.next_cursor);
      const fresh = data.items.filter(item => {
        if (idsRef.current.has(item.id)) return false;
        idsRef.current.add(item.id);
        return true;
      });
      setItems(previous => [...previous, ...fresh]);
      cursorRef.current = data.next_cursor;
      setHasMore(data.has_more);
    } catch (failure) {
      if (!alive.current || !isDashboardSessionCurrent(sessionRef.current)) return;
      if (failure instanceof Error && failure.name === "AbortError") return;
      const status = Number((failure as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403 || status === 404) {
        setItems([]);
        setHasMore(false);
        deniedRef.current();
        onCloseRef.current();
        return;
      }
      setError(true);
    } finally {
      if (alive.current) {
        pending.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [authFetch, exactReference, filterType, locationId, operation.group_key, search]);

  useEffect(() => {
    alive.current = true;
    sessionRef.current = captureDashboardSession();
    void load(null);
    const unsubscribe = subscribeDashboardSession(() => {
      if (!isDashboardSessionCurrent(sessionRef.current)) {
        abortRef.current?.abort();
        setItems([]);
        deniedRef.current();
        onCloseRef.current();
      }
    });
    return () => {
      alive.current = false;
      abortRef.current?.abort();
      unsubscribe();
    };
  }, [load]);

  const more = useCallback(() => {
    if (!pending.current && hasMore && cursorRef.current) void load(cursorRef.current);
  }, [hasMore, load]);
  const retry = useCallback(() => {
    if (!pending.current) void load(cursorRef.current);
  }, [load]);
  const viewport = useLedgerWindow(items.length, 205, more, hasMore, loadingMore || error);
  const unit = (code: string) => t(`uom.${code}`, { defaultValue: code });
  const stage = (code: string) => {
    const label = ledgerMovementLabel(t, language, code);
    return label === code ? (ar ? "حركة موثقة" : "Recorded movement") : label;
  };
  const count = (n: number) => new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(n);
  const heading = `${ledgerOperationKindLabel(operation.group_kind, ar)} · ${operation.reference || (ar ? "بدون مرجع" : "No reference")}`;
  return (
    <Modal isOpen={true} onClose={onClose} title={heading} maxWidth="max-w-5xl">
      <div data-ledger-operation-details="true" className="flex max-h-[75vh] min-h-0 flex-col gap-2">
        <p className="text-xs font-semibold text-slate-600">
          {count(operation.product_variant_count)} {ar ? "أصناف" : "products"} · {count(operation.batch_count)} {ar ? "تشغيلات" : "lots"} · {count(operation.movement_count)} {ar ? "حركات أصلية مسجلة" : "original immutable movements"}
        </p>
        {operation.count_meaning === "POSTED_VARIANCE_MOVEMENTS" && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            {ar ? "هذه الحركات تخص فروقات الجرد المثبتة فقط؛ الأصناف التي لم يتغير رصيدها موجودة في تاريخ الجرد المكتمل." :
              "These are posted stocktake variances only. Unchanged counted products belong in completed stocktake history."}
            {operation.stocktake_history && (
              <button type="button" className="ms-2 rounded border border-amber-400 bg-white px-2 py-1 font-bold"
                onClick={() => {
                  onClose();
                  navigate("/inventory", { state: createInventoryTabNavigationState("stocktake", operation.stocktake_history!.warehouse_location_id) });
                }}>
                {ar ? "فتح تاريخ الجرد" : "Open stocktake history"} · <bdi dir="ltr">{operation.stocktake_history.reference}</bdi>
              </button>
            )}
          </div>
        )}
        {error && (
          <div role="alert" className="flex items-center justify-between rounded border border-amber-200 bg-amber-50 p-2 text-xs">
            {ar ? "تعذر استكمال التفاصيل؛ الحركات المحملة محفوظة." : "Could not continue details; loaded movements are retained."}
            <button type="button" onClick={retry} className="rounded border px-2 py-1">{ar ? "إعادة المحاولة" : "Retry"}</button>
          </div>
        )}
        <div ref={viewport.rootRef} onScroll={viewport.onScroll}
          className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2"
          data-ledger-child-list="true" data-ledger-mounted={viewport.mounted}>
          {loading && items.length === 0 && <p role="status" className="p-3 text-sm">{ar ? "جاري تحميل التفاصيل..." : "Loading details..."}</p>}
          {!loading && !error && items.length === 0 && <p role="status" className="p-3 text-sm">{ar ? "لا توجد حركات مرئية." : "No visible movements."}</p>}
          {viewport.before > 0 && <div aria-hidden="true" style={{ height: viewport.before }} />}
          {items.slice(viewport.first, viewport.last).map((item, index) => {
            const locations = ledgerLocationEvidence(t, language, item);
            return <article key={item.id} data-ledger-virtual-index={viewport.first + index} data-ledger-child-id={item.id}
              className={`mb-2 rounded-lg border p-3 text-xs ${item.matches_filter ? "border-blue-300 bg-blue-50/70" : "border-slate-200 bg-white"}`}>
              <div className="flex flex-wrap justify-between gap-2">
                <strong className="text-slate-900">{item.product_name} · {formatPublicBatchNumber(item.batch_number, ar ? "بدون تشغيلة" : "No lot")}</strong>
                <bdi dir="ltr" className="font-bold text-slate-500">#{item.id} · {formatLedgerDate(item.date, locale)}</bdi>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-slate-700">
                <span className="rounded bg-slate-100 px-2 py-0.5">{stage(item.reference_type)}</span>
                <bdi dir="auto" className="font-bold">{ledgerSignedQuantity(item, unit)}</bdi>
                <span>{ar ? "من" : "From"}: {locations.source} · {ar ? "إلى" : "To"}: {locations.destination}</span>
                {item.admin_name && <span>{ar ? "المنفذ" : "Actor"}: {item.admin_name}</span>}
              </div>
              <div className="mt-1"><LedgerCostEvidence t={t} language={language} entry={item} /></div>
              {item.notes && <p className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2">{item.notes}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {item.reference && <button type="button" className="rounded border border-blue-200 px-2 py-1 text-blue-800"
                  onClick={() => onOpenReference(item)}>{ar ? "دليل المرجع" : "Reference evidence"}</button>}
                {canAdjust && item.type === "INBOUND_SUPPLIER" &&
                  <button type="button" className="rounded border border-purple-200 px-2 py-1 text-purple-800"
                    onClick={() => onAdjust(item)}>{ar ? "تصحيح التوريد" : "Correct inbound"}</button>}
              </div>
            </article>;
          })}
          {viewport.after > 0 && <div aria-hidden="true" style={{ height: viewport.after }} />}
          <div ref={viewport.markerRef} data-ledger-bottom="true" className="h-px" aria-hidden="true" />
        </div>
        {loadingMore && <p role="status" className="text-center text-xs text-slate-500">{ar ? "جاري تحميل المزيد..." : "Loading more..."}</p>}
      </div>
    </Modal>
  );
}
