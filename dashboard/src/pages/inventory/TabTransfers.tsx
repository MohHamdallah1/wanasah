import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Plus, RefreshCcw, Search, Truck } from "lucide-react";
import { useTransferTranslation as useTranslation, formatTransferNumber } from "./transfers/i18n";
import { TRANSFER_STATUSES, isTransferStatus, STATUS_META } from "./transfers/constants";
import type { Props, WarehouseTransferListItem } from "./transfers/types";
import { TransferTable } from "./transfers/TransferTable";
import { TransferDetailModal } from "./transfers/TransferDetailModal";
import { TransferDecisionModal } from "./transfers/TransferDecisionModal";
import { TransferCreateModal } from "./transfers/TransferCreateModal";
import { useTransferList } from "./transfers/hooks/useTransferList";
import { useTransferActions } from "./transfers/hooks/useTransferActions";
import { useTransferCreate } from "./transfers/hooks/useTransferCreate";
import { useTenantIdentity } from "@/features/tenantIdentity/useTenantIdentity";

class TransferWorkspaceErrorBoundary extends Component<
  { children: ReactNode; retryLabel: string; message: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <section
          role="alert"
          className="inventory-surface flex min-h-48 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-red-200 bg-red-50 p-6 text-center"
        >
          <p className="max-w-xl text-sm font-bold text-red-800">
            {this.props.message}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ failed: false })}
            className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-black text-red-700"
          >
            {this.props.retryLabel}
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}

function TabTransfersWorkspace({
  focus = null,
  onFocusConsumed,
  onInventoryChanged,
}: Props) {
  const { t, i18n } = useTranslation();
  const tenantIdentity = useTenantIdentity();
  const timeZone = tenantIdentity.data?.timezone;
  const focusIdRef = useRef<number | null>(null);
  const [focusedTransfer, setFocusedTransfer] = useState<WarehouseTransferListItem | null>(null);
  const transferList = useTransferList();
  const {
    items,
    status,
    setStatus,
    searchInput,
    setSearchInput,
    total,
    loading,
    loadingMore,
    hasMore,
    detail,
    detailLoading,
    inTransitCount,
    openDetail,
    openDetailById,
    closeDetail,
    resetDetail,
    refreshTransfers,
    loadMore,
  } = transferList;

  const handleTransferActionCompleted = useCallback(() => {
    focusIdRef.current = null;
    setFocusedTransfer(null);
    resetDetail();
    refreshTransfers();
  }, [refreshTransfers, resetDetail]);

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
    onInventoryChanged,
    onCompleted: refreshTransfers,
  });

  const visibleItems = focusedTransfer
    ? [
        items.find((item) => item.id === focusedTransfer.id) ?? focusedTransfer,
        ...items.filter((item) => item.id !== focusedTransfer.id),
      ]
    : items;

  return (
    <div
      dir={i18n.dir()}
      className="inventory-view inventory-transfers flex min-h-0 flex-1 flex-col gap-2"
      data-cp13-density="compact"
      data-cp13-surface="transfers"
    >
      <section className="inventory-surface inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-2 sm:flex-nowrap sm:px-4" data-cp13-controls="transfer-list">
          <div className="min-w-0 shrink-0">
            <h2 className="flex items-center gap-2 text-sm font-black text-slate-900">
              <Truck className="h-4 w-4 text-blue-700" aria-hidden="true" />
              {t("inventoryTransfers.title")}
            </h2>
            <p className="mt-0.5 truncate text-[10px] font-bold text-slate-500">
              {t("inventoryTransfers.workspaceSummary", {
                total: total === null ? "—" : formatTransferNumber(total),
                count: formatTransferNumber(inTransitCount),
              })}
            </p>
          </div>

          <div className="relative w-full min-w-56 flex-1 sm:w-auto">
            <Search className="pointer-events-none absolute start-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              aria-label={t("inventoryTransfers.search")}
              placeholder={t("inventoryTransfers.search")}
              maxLength={100}
              className="h-9 w-full rounded-lg border border-slate-200 bg-white ps-9 pe-3 text-xs font-bold text-slate-800 outline-none focus-visible:border-blue-300 focus-visible:ring-2 focus-visible:ring-blue-100"
            />
          </div>

          <select
            aria-label={t("inventoryTransfers.status")}
            value={status}
            onChange={(event) => {
              const value = event.target.value;
              setStatus(value && isTransferStatus(value) ? value : "");
            }}
            className="h-9 w-full shrink-0 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold text-slate-700 outline-none focus-visible:border-blue-300 focus-visible:ring-2 focus-visible:ring-blue-100 sm:w-44"
          >
            <option value="">{t("inventoryTransfers.allStatuses")}</option>
            {TRANSFER_STATUSES.map((value) => (
              <option key={value} value={value}>{t(STATUS_META[value].label)}</option>
            ))}
          </select>

          <button
            type="button"
            disabled={!transferCreate.canOpen}
            onClick={transferCreate.openCreate}
            className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-blue-700 px-3 text-xs font-black text-white outline-none hover:bg-blue-800 disabled:opacity-40 focus-visible:ring-2 focus-visible:ring-blue-300"
            data-cp13-action-priority="primary"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
            {t("inventoryTransfers.newTransfer")}
          </button>

          <button
            type="button"
            onClick={refreshTransfers}
            disabled={loading}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 outline-none hover:bg-slate-50 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-300"
            title={t("inventoryTransfers.refresh")}
            aria-label={t("inventoryTransfers.refresh")}
          >
            <RefreshCcw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </header>

        {transferList.failure ? (
          <div role="alert" data-cp13-state={transferList.failure.phase === "first" ? "error" : "stale"} className={`m-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${transferList.failure.phase === "first" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
            <div className="min-w-0">
              <p>{t(`inventoryTransfers.${transferList.failure.phase === "first" ? "firstFailure" : transferList.failure.phase === "refresh" ? "refreshFailure" : "continuationFailure"}`)}</p>
              <p className="mt-0.5 break-words text-[11px] font-semibold opacity-80">{transferList.failure.message}</p>
            </div>
            <button type="button" disabled={loading || loadingMore} onClick={transferList.retry} className="shrink-0 rounded-lg border border-current/20 bg-white px-2.5 py-1.5 text-[11px] font-black disabled:opacity-50">
              {t("inventoryTransfers.retry")}
            </button>
          </div>
        ) : null}

        <TransferTable
          items={visibleItems}
          loading={loading}
          loadingMore={loadingMore}
          hasMore={hasMore}
          timeZone={timeZone}
          onLoadMore={loadMore}
          onOpenDetail={async (transfer) => { await openDetail(transfer); }}
          onOpenAction={openAction}
        />
      </section>

      {transferCreate.command.pending && !transferCreate.createOpen ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
          <p>{t("inventoryTransfers.pending")}</p>
          <button type="button" disabled={transferCreate.command.busy} onClick={() => void transferCreate.retryPendingDispatch()} className="rounded-lg border border-amber-200 bg-white px-2.5 py-1.5">
            {t("inventoryTransfers.pendingTransfer")}
          </button>
        </div>
      ) : null}

      {transferActions.command.pending && !action ? (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
          <p>{t("inventoryTransfers.pending")}</p>
          <button type="button" disabled={transferActions.command.busy} onClick={() => void transferActions.retryPendingAction()} className="rounded-lg border border-amber-200 bg-white px-2.5 py-1.5">
            {t("inventoryTransfers.retry")}
          </button>
        </div>
      ) : null}

      <TransferCreateModal controller={transferCreate} />
      <TransferDetailModal
        detail={detail}
        loading={detailLoading}
        timeZone={timeZone}
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

export function TabTransfers(props: Props) {
  const { t } = useTranslation();
  return (
    <TransferWorkspaceErrorBoundary
      retryLabel={t("inventoryTransfers.retry")}
      message={t("inventoryTransfers.workspaceCrash")}
    >
      <TabTransfersWorkspace {...props} />
    </TransferWorkspaceErrorBoundary>
  );
}
