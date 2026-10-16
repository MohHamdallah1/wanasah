import { useTransferTranslation as useTranslation, formatTransferNumber } from "./transfers/i18n";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus,
  RefreshCcw,
  Search,
  Truck,
} from "lucide-react";
import {
  TRANSFER_STATUSES,
  isTransferStatus,
  STATUS_META,
} from "./transfers/constants";
import type { Props, WarehouseTransferListItem } from "./transfers/types";
import { TransferTable } from "./transfers/TransferTable";
import { TransferDetailModal } from "./transfers/TransferDetailModal";
import { TransferDecisionModal } from "./transfers/TransferDecisionModal";
import { TransferCreateModal } from "./transfers/TransferCreateModal";
import { useTransferList } from "./transfers/hooks/useTransferList";
import { useTransferActions } from "./transfers/hooks/useTransferActions";
import { useTransferCreate } from "./transfers/hooks/useTransferCreate";

export function TabTransfers({
  locationId,
  focus = null,
  onFocusConsumed,
  onInventoryChanged,
}: Props) {
  const { t } = useTranslation();
  const access = useInventoryAccess(locationId);
  const focusIdRef = useRef<number | null>(null);
  const [focusedTransfer, setFocusedTransfer] = useState<WarehouseTransferListItem | null>(null);
  const transferList = useTransferList(locationId);
  const {
    items,
    status,
    setStatus,
    direction,
    setDirection,
    searchInput,
    setSearchInput,
    total,
    loading,
    cursorHistory,
    nextCursor,
    detail,
    detailLoading,
    inTransitCount,
    openDetail,
    openDetailById,
    closeDetail,
    resetDetail,
    refreshTransfers,
    handleNext,
    handlePrevious,
  } = transferList;

  const handleTransferActionCompleted = useCallback(() => {
    focusIdRef.current = null;
    setFocusedTransfer(null);
    resetDetail();
    refreshTransfers();
  }, [refreshTransfers, resetDetail]);

  useEffect(() => {
    focusIdRef.current = null;
    setFocusedTransfer(null);
  }, [locationId]);

  useEffect(() => {
    if (!focus) return;
    focusIdRef.current = focus.headerId;
    setSearchInput(focus.reference);
    onFocusConsumed?.();
    void openDetailById(focus.headerId);
  }, [focus, onFocusConsumed, openDetailById, setSearchInput]);

  useEffect(() => {
    if (detail?.transfer.id === focusIdRef.current) setFocusedTransfer(detail.transfer);
  }, [detail]);

  const transferActions = useTransferActions({
    locationId,
    onInventoryChanged,
    onCompleted: handleTransferActionCompleted,
  });
  const {
    action,
    actionTransfer,
    decisionReason,
    actionSubmitting,
    openAction,
    closeAction,
    updateDecisionReason,
    handleAction,
  } = transferActions;

  const transferCreate = useTransferCreate({
    locationId,
    onInventoryChanged,
    onCompleted: refreshTransfers,
  });

  return (
    <div className="inventory-view inventory-transfers flex flex-col gap-4 min-h-0 flex-1">
      <div className="glass-card inventory-section-header rounded-2xl p-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="font-black text-slate-800 flex items-center gap-2">
            <Truck className="w-5 h-5 text-blue-600" />{t("inventoryTransfers.title")}</h2>
          <p className="text-xs text-slate-500 mt-1">
            {t("inventoryTransfers.locationSummary", { id: formatTransferNumber(locationId), total: total === null ? "—" : formatTransferNumber(total), count: formatTransferNumber(inTransitCount) })}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            disabled={!(access.can('transfer.send') || (access.can('transfer.destination') && access.canAny('transfer.send')))}
            onClick={transferCreate.openCreate}
            className="px-4 py-2 rounded-xl bg-blue-600 text-white font-bold text-sm flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />{t("inventoryTransfers.newTransfer")}</button>

          <button
            onClick={refreshTransfers}
            disabled={loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 font-bold text-xs disabled:opacity-50"
            title={t("inventoryTransfers.refresh")}
          >
            <RefreshCcw
              className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
            />
          </button>
        </div>
      </div>

      <div className="glass-card inventory-toolbar rounded-2xl p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="relative">
          <Search className="w-4 h-4 absolute start-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label={t("inventoryTransfers.search")}
            placeholder={t("inventoryTransfers.search")}
            maxLength={100}
            className="w-full ps-10 pe-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        <select
          aria-label={t("inventoryTransfers.status")}
          value={status}
          onChange={(event) => {
            const value = event.target.value;
            setStatus(value && isTransferStatus(value) ? value : "");
          }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
        >
          <option value="">{t("inventoryTransfers.allStatuses")}</option>
          {TRANSFER_STATUSES.map((value) => (
            <option key={value} value={value}>
              {t(STATUS_META[value].label)}
            </option>
          ))}
        </select>

        <select
          aria-label={t("inventoryTransfers.direction")}
          value={direction}
          onChange={(event) => {
            const value = event.target.value;
            if (
              value === "all" ||
              value === "source" ||
              value === "destination"
            ) {
              setDirection(value);
            }
          }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
        >
          <option value="all">{t("inventoryTransfers.allDirections")}</option>
          <option value="source">{t("inventoryTransfers.outgoing")}</option>
          <option value="destination">{t("inventoryTransfers.incoming")}</option>
        </select>
      </div>

      {transferList.failure && <div role="alert" className="rounded-xl border p-3 text-sm"><p>{t(`inventoryTransfers.${transferList.failure.phase === "first" ? "firstFailure" : transferList.failure.phase === "refresh" ? "refreshFailure" : "continuationFailure"}`)}</p><p>{transferList.failure.message}</p><button type="button" disabled={loading} onClick={transferList.retry}>{t("inventoryTransfers.retry")}</button></div>}

      <TransferTable
        items={focusedTransfer ? [items.find((item) => item.id === focusedTransfer.id) ?? focusedTransfer, ...items.filter((item) => item.id !== focusedTransfer.id)] : items}
        locationId={locationId}
        loading={loading}
        cursorHistoryLength={cursorHistory.length}
        nextCursor={nextCursor}
        onOpenDetail={async (transfer) => { await openDetail(transfer); }}
        onOpenAction={openAction}
        onPrevious={handlePrevious}
        onNext={handleNext}
      />

      {transferCreate.command.pending && !transferCreate.createOpen && <div role="alert" className="rounded-xl border p-3"><p>{t("inventoryTransfers.pending")}</p><button type="button" disabled={transferCreate.command.busy} onClick={() => void transferCreate.retryPendingDispatch()}>{t("inventoryTransfers.pendingTransfer")}</button></div>}
      {transferActions.command.pending && !action && <div role="alert" className="rounded-xl border p-3"><p>{t("inventoryTransfers.pending")}</p><button type="button" disabled={transferActions.command.busy} onClick={() => void transferActions.retryPendingAction()}>{t("inventoryTransfers.retry")}</button></div>}

      <TransferCreateModal
        locationId={locationId}
        controller={transferCreate}
      />

      <TransferDetailModal
        detail={detail}
        loading={detailLoading}
        onClose={closeDetail}
      />

      <TransferDecisionModal
        action={action}
        transfer={actionTransfer}
        decisionReason={decisionReason}
        submitting={actionSubmitting || transferActions.command.busy || Boolean(transferActions.command.pending)}
        pending={Boolean(transferActions.command.pending)}
        retrying={transferActions.command.busy}
        onRetry={transferActions.retryPendingAction}
        onClose={closeAction}
        onDecisionReasonChange={updateDecisionReason}
        onSubmit={handleAction}
      />
    </div>
  );
}
