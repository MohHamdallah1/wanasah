import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useCallback } from "react";
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
import type { Props } from "./transfers/types";
import { TransferTable } from "./transfers/TransferTable";
import { TransferDetailModal } from "./transfers/TransferDetailModal";
import { TransferDecisionModal } from "./transfers/TransferDecisionModal";
import { TransferCreateModal } from "./transfers/TransferCreateModal";
import { useTransferList } from "./transfers/hooks/useTransferList";
import { useTransferActions } from "./transfers/hooks/useTransferActions";
import { useTransferCreate } from "./transfers/hooks/useTransferCreate";

export function TabTransfers({
  locationId,
  onInventoryChanged,
}: Props) {
  const access = useInventoryAccess(locationId);
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
    closeDetail,
    resetDetail,
    refreshTransfers,
    handleNext,
    handlePrevious,
  } = transferList;

  const handleTransferActionCompleted = useCallback(() => {
    resetDetail();
    refreshTransfers();
  }, [refreshTransfers, resetDetail]);

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
            <Truck className="w-5 h-5 text-blue-600" />
            الحوالات الموحّدة
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            الموقع #{locationId} ·{" "}
            {total !== null ? `${total} حوالة` : "—"} ·{" "}
            {inTransitCount} في الطريق بهذه الصفحة
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            disabled={!(access.can('transfer.send') || (access.can('transfer.destination') && access.canAny('transfer.send')))}
            onClick={transferCreate.openCreate}
            className="px-4 py-2 rounded-xl bg-blue-600 text-white font-bold text-sm flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            حوالة جديدة
          </button>

          <button
            onClick={refreshTransfers}
            disabled={loading}
            className="px-3 py-2 rounded-xl border border-slate-200 bg-white text-slate-600 font-bold text-xs disabled:opacity-50"
            title="تحديث"
          >
            <RefreshCcw
              className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
            />
          </button>
        </div>
      </div>

      <div className="glass-card inventory-toolbar rounded-2xl p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="relative">
          <Search className="w-4 h-4 absolute right-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="بحث برقم الحوالة"
            maxLength={100}
            className="w-full pr-10 pl-3 py-2.5 rounded-xl border border-slate-200 bg-white text-sm outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </div>

        <select
          value={status}
          onChange={(event) => {
            const value = event.target.value;
            setStatus(value && isTransferStatus(value) ? value : "");
          }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none"
        >
          <option value="">كل الحالات</option>
          {TRANSFER_STATUSES.map((value) => (
            <option key={value} value={value}>
              {STATUS_META[value].label}
            </option>
          ))}
        </select>

        <select
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
          <option value="all">كل الاتجاهات</option>
          <option value="source">صادرة من المستودع</option>
          <option value="destination">واردة إلى المستودع</option>
        </select>
      </div>

      <TransferTable
        items={items}
        locationId={locationId}
        loading={loading}
        cursorHistoryLength={cursorHistory.length}
        nextCursor={nextCursor}
        onOpenDetail={openDetail}
        onOpenAction={openAction}
        onPrevious={handlePrevious}
        onNext={handleNext}
      />

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
        submitting={actionSubmitting}
        onClose={closeAction}
        onDecisionReasonChange={updateDecisionReason}
        onSubmit={handleAction}
      />
    </div>
  );
}
