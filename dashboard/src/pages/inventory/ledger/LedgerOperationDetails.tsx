import { ledgerOperationKindLabel, operationText, operationFailureText, parseLedgerOperationFailure, type LedgerOperationFailure } from "./operationI18n";
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
  const navigate = useNavigate();
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<LedgerOperationChild[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [failure, setFailure] = useState<LedgerOperationFailure | null>(null);
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
    setFailure(null);
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
      setFailure(parseLedgerOperationFailure(failure));
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
    return label === code ? (operationText(t, language, "copy10")) : label;
  };
  const count = (n: number) => new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(n);
  const heading = `${ledgerOperationKindLabel(operation.group_kind, t, language)} · ${operation.reference || (operationText(t, language, "copy11"))}`;
  return (
    <Modal isOpen={true} onClose={onClose} title={heading} maxWidth="max-w-5xl">
      <div data-ledger-operation-details="true" className="flex max-h-[75vh] min-h-0 flex-col gap-2">
        <p className="text-xs font-semibold text-slate-600">
          {count(operation.product_variant_count)} {operationText(t, language, "copy4")} · {count(operation.batch_count)} {operationText(t, language, "copy5")} · {count(operation.movement_count)} {operationText(t, language, "copy12")}
        </p>
        {operation.count_meaning === "POSTED_VARIANCE_MOVEMENTS" && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            {operationText(t, language, "copy13")}
            {operation.stocktake_history && (
              <button type="button" className="ms-2 rounded border border-amber-400 bg-white px-2 py-1 font-bold"
                onClick={() => {
                  onClose();
                  navigate("/inventory", { state: createInventoryTabNavigationState("stocktake", operation.stocktake_history!.warehouse_location_id) });
                }}>
                {operationText(t, language, "copy14")} · <bdi dir="ltr">{operation.stocktake_history.reference}</bdi>
              </button>
            )}
          </div>
        )}
        {error && (
          <div role="alert" className="flex items-center justify-between rounded border border-amber-200 bg-amber-50 p-2 text-xs">
            <span className="min-w-0 break-words">
              {failure ? operationFailureText(t, language, failure) : operationText(t, language, "copy15")}
              {failure?.code && failure.status >= 400 && failure.status < 500 && (
                <span className="ms-2">{operationText(t, language, "errorCode")}: <bdi dir="ltr">{failure.code}</bdi></span>
              )}
              {failure?.context && <span className="ms-2">{failure.context}</span>}
              {failure?.requestId && <span className="ms-2">{operationText(t, language, "requestId")}: <bdi dir="ltr">{failure.requestId}</bdi></span>}
            </span>
            <button type="button" onClick={retry} className="rounded border px-2 py-1">{operationText(t, language, "copy16")}</button>
          </div>
        )}
        <div ref={viewport.rootRef} onScroll={viewport.onScroll}
          className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2"
          data-ledger-child-list="true" data-ledger-mounted={viewport.mounted}>
          {loading && items.length === 0 && <p role="status" className="p-3 text-sm">{operationText(t, language, "copy17")}</p>}
          {!loading && !error && items.length === 0 && <p role="status" className="p-3 text-sm">{operationText(t, language, "copy18")}</p>}
          {viewport.before > 0 && <div aria-hidden="true" style={{ height: viewport.before }} />}
          {items.slice(viewport.first, viewport.last).map((item, index) => {
            const locations = ledgerLocationEvidence(t, language, item);
            // A null counterpart may be redacted by Backend warehouse RLS,
            // not an actual external source/destination. Do not invent a
            // physical location or reveal the inaccessible warehouse.
            const visibleLocation = (side: "source" | "destination") => {
              const id = side === "source" ? item.source_location_id : item.destination_location_id;
              const name = side === "source" ? item.source_location_name : item.destination_location_name;
              if (id !== null || name !== null) return locations[side];
              // A genuine supplier receipt has a documented outside source.
              if (side === "source" && operation.group_kind === "RECEIPT" &&
                  item.reference_type === "INBOUND_SUPPLIER") return locations.source;
              return operationText(t, language, "locationNotShown");
            };
            return <article key={item.id} data-ledger-virtual-index={viewport.first + index} data-ledger-child-id={item.id}
              className={`mb-2 rounded-lg border p-3 text-xs ${item.matches_filter ? "border-blue-300 bg-blue-50/70" : "border-slate-200 bg-white"}`}>
              <div className="flex flex-wrap justify-between gap-2">
                <strong className="text-slate-900">{item.product_name} · {formatPublicBatchNumber(item.batch_number, operationText(t, language, "copy19"))}</strong>
                <bdi dir="ltr" className="font-bold text-slate-500">#{item.id} · {formatLedgerDate(item.date, locale)}</bdi>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-slate-700">
                <span className="rounded bg-slate-100 px-2 py-0.5">{stage(item.reference_type)}</span>
                <bdi dir="auto" className="font-bold">{ledgerSignedQuantity(item, unit)}</bdi>
                <span>{operationText(t, language, "copy8")}: {visibleLocation("source")} · {operationText(t, language, "copy9")}: {visibleLocation("destination")}</span>
                {item.admin_name && <span>{operationText(t, language, "copy20")}: {item.admin_name}</span>}
              </div>
              <div className="mt-1"><LedgerCostEvidence t={t} language={language} entry={item} /></div>
              {item.notes && <p className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-2">{item.notes}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                {item.reference && <button type="button" className="rounded border border-blue-200 px-2 py-1 text-blue-800"
                  onClick={() => onOpenReference(item)}>{operationText(t, language, "copy21")}</button>}
                {canAdjust && item.type === "INBOUND_SUPPLIER" &&
                  <button type="button" className="rounded border border-purple-200 px-2 py-1 text-purple-800"
                    onClick={() => onAdjust(item)}>{operationText(t, language, "copy22")}</button>}
              </div>
            </article>;
          })}
          {viewport.after > 0 && <div aria-hidden="true" style={{ height: viewport.after }} />}
          <div ref={viewport.markerRef} data-ledger-bottom="true" className="h-px" aria-hidden="true" />
        </div>
        {loadingMore && <p role="status" className="text-center text-xs text-slate-500">{operationText(t, language, "copy23")}</p>}
      </div>
    </Modal>
  );
}
