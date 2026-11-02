import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useCallback, useState } from "react";
import type { StocktakeAuthFetch } from "./stocktake/types";
import { useStocktakeSessions } from "./stocktake/hooks/useStocktakeSessions";
import { useStocktakeState } from "./stocktake/hooks/useStocktakeState";
import { useStocktakeCounting } from "./stocktake/hooks/useStocktakeCounting";
import { useStocktakeReview } from "./stocktake/hooks/useStocktakeReview";
import { useStocktakeActions } from "./stocktake/hooks/useStocktakeActions";
import { useStocktakeLifecycle } from "./stocktake/hooks/useStocktakeLifecycle";
import { useCycleCountStart } from "./stocktake/hooks/useCycleCountStart";
import { useStocktakeCopy } from "./stocktake/copy";
import { StocktakeSessionCenter } from "./stocktake/StocktakeSessionCenter";
import { StocktakeCycleStartModal } from "./stocktake/StocktakeCycleStartModal";
import { StocktakeIdlePanel } from "./stocktake/StocktakeIdlePanel";
import { StocktakeIndependentWait } from "./stocktake/StocktakeIndependentWait";
import { StocktakeCountingPanel } from "./stocktake/StocktakeCountingPanel";
import { StocktakeReviewPanel } from "./stocktake/StocktakeReviewPanel";
import {
  StocktakeStartModal,
  StocktakeSubmitModal,
} from "./stocktake/StocktakeCountModals";
import {
  StocktakeApproveModal,
  StocktakeCancelModal,
  StocktakeRecountModal,
  StocktakeVarianceModal,
} from "./stocktake/StocktakeDecisionModals";

interface Props {
  active?: boolean;
  focusSessionId?: number;
  onFocusUnavailable?: (error: unknown) => void;
  locationId: number;
  companyId: string;
  isAuditLocked: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  onStocktakeChanged: () => void | Promise<void>;
}

export function Tab3Stocktake({
  active = true,
  focusSessionId,
  onFocusUnavailable,
  locationId,
  companyId,
  isAuditLocked,
  authenticatedFetch,
  onStocktakeChanged,
}: Props) {
  const { copy, dir } = useStocktakeCopy();
  const [showLockModal, setShowLockModal] = useState(false);
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [showVarianceModal, setShowVarianceModal] = useState(false);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRecountModal, setShowRecountModal] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [showCycleModal, setShowCycleModal] = useState(false);

  const stocktakeState = useStocktakeState({ companyId, locationId });
  const warehouseAccess = useInventoryAccess(locationId);
  const sessionAccess = useInventoryAccess(stocktakeState.sessionLocationId ?? locationId);
  const canReadStocktake = warehouseAccess.can("stocktake.read");
  const durableIdentity = warehouseAccess.data
    ? {
        companyId: warehouseAccess.data.company_id,
        backofficeUserId: warehouseAccess.data.backoffice_user_id,
      }
    : null;

  const { setRows, setReview } = stocktakeState;
  const {
    sessions: activeSessions,
    total: activeSessionsTotal,
    nextCursor: activeSessionsNextCursor,
    loading: sessionsLoading,
    loadingMore: sessionsLoadingMore,
    loadFailed: sessionsLoadFailed,
    refreshSessions,
    loadMore: loadMoreSessions,
  } = useStocktakeSessions({
    enabled: active && canReadStocktake,
    locationId,
    authenticatedFetch,
  });

  const notifyStocktakeChanged = useCallback(async () => {
    await onStocktakeChanged();
    refreshSessions();
  }, [onStocktakeChanged, refreshSessions]);

  const clearRows = useCallback(() => setRows([]), [setRows]);
  const clearReview = useCallback(() => setReview(null), [setReview]);

  const reviewWorkflow = useStocktakeReview({
    sessionLocationId: stocktakeState.sessionLocationId,
    phaseKey: stocktakeState.phaseKey,
    authenticatedFetch,
    review: stocktakeState.review,
    setReview: stocktakeState.setReview,
    setRows: stocktakeState.setRows,
    setSessionId: stocktakeState.setSessionId,
    setSessionLocationId: stocktakeState.setSessionLocationId,
    setPhase: stocktakeState.setPhase,
  });

  const countingWorkflow = useStocktakeCounting({
    durableIdentity,
    companyScope: stocktakeState.companyScope,
    phaseKey: stocktakeState.phaseKey,
    phase: stocktakeState.phase,
    sessionId: stocktakeState.sessionId,
    sessionLocationId: stocktakeState.sessionLocationId,
    draftKey: stocktakeState.draftKey,
    authenticatedFetch,
    rows: stocktakeState.rows,
    setRows: stocktakeState.setRows,
    setReview: stocktakeState.setReview,
    setSessionId: stocktakeState.setSessionId,
    setSessionLocationId: stocktakeState.setSessionLocationId,
    setPhase: stocktakeState.setPhase,
    onSubmitted: reviewWorkflow.loadReview,
  });

  const cycleWorkflow = useCycleCountStart({
    durableIdentity,
    locationId,
    enabled: active && showCycleModal,
    authenticatedFetch,
    sessionKey: stocktakeState.sessionKey,
    phaseKey: stocktakeState.phaseKey,
    setSessionId: stocktakeState.setSessionId,
    setSessionLocationId: stocktakeState.setSessionLocationId,
    loadCountSheet: countingWorkflow.loadCountSheet,
    notifyStocktakeChanged,
  });

  const actionWorkflow = useStocktakeActions({
    authenticatedFetch,
    durableIdentity,
    sessionId: stocktakeState.sessionId,
    sessionLocationId: stocktakeState.sessionLocationId,
    review: stocktakeState.review,
    draftKey: stocktakeState.draftKey,
    sessionKey: stocktakeState.sessionKey,
    phaseKey: stocktakeState.phaseKey,
    setRows: stocktakeState.setRows,
    setReview: stocktakeState.setReview,
    setSessionId: stocktakeState.setSessionId,
    setSessionLocationId: stocktakeState.setSessionLocationId,
    setPhase: stocktakeState.setPhase,
    loadCountSheet: countingWorkflow.loadCountSheet,
    notifyStocktakeChanged,
  });

  const lifecycle = useStocktakeLifecycle({
    active,
    durableIdentity,
    focusSessionId,
    onFocusUnavailable,
    locationId,
    sessionKey: stocktakeState.sessionKey,
    phaseKey: stocktakeState.phaseKey,
    sessionId: stocktakeState.sessionId,
    sessionLocationId: stocktakeState.sessionLocationId,
    activeSessions,
    activeSessionsTotal,
    sessionsLoading,
    sessionsLoadFailed,
    authenticatedFetch,
    loadCountSheet: countingWorkflow.loadCountSheet,
    loadReview: reviewWorkflow.loadReview,
    setSessionId: stocktakeState.setSessionId,
    setSessionLocationId: stocktakeState.setSessionLocationId,
    setPhase: stocktakeState.setPhase,
    clearRows,
    clearReview,
    notifyStocktakeChanged,
  });

  const submitCount = async () => {
    if (await countingWorkflow.handleSubmit()) setShowSubmitModal(false);
  };
  const approve = async () => {
    if (await actionWorkflow.handleApprove()) setShowApproveModal(false);
  };
  const recount = async () => {
    if (await actionWorkflow.handleRecount()) setShowRecountModal(false);
  };
  const cancel = async () => {
    if (await actionWorkflow.handleCancel()) setShowCancelModal(false);
  };
  const start = async () => {
    if (await lifecycle.startStocktake()) setShowLockModal(false);
  };
  const closeCycleModal = () => {
    if (cycleWorkflow.starting) return;
    setShowCycleModal(false);
    cycleWorkflow.resetForm();
  };
  const startCycle = async () => {
    if (await cycleWorkflow.startCycleCount()) setShowCycleModal(false);
  };
  return (
    <div dir={dir} className="inventory-view inventory-stocktake flex h-full min-h-0 flex-1 flex-col gap-4 pt-1">
      <StocktakeSessionCenter
        sessions={activeSessions}
        total={activeSessionsTotal}
        loading={sessionsLoading}
        loadingMore={sessionsLoadingMore}
        nextCursor={activeSessionsNextCursor}
        currentSessionId={lifecycle.selectedSessionId}
        onRefresh={refreshSessions}
        onStartCycle={() => setShowCycleModal(true)}
        cycleStartDisabled={isAuditLocked || sessionsLoading || !warehouseAccess.can("stocktake.start")}
        onLoadMore={loadMoreSessions}
        onOpenSession={lifecycle.openServerSession}
      />

      {stocktakeState.sessionId === null &&
        !isAuditLocked && warehouseAccess.can("stocktake.start") && (
          <StocktakeIdlePanel onStart={() => setShowLockModal(true)} />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase === "WAITING_INDEPENDENT" && (
          <StocktakeIndependentWait
            canCancel={sessionAccess.can("stocktake.cancel")}
            onCancel={() => setShowCancelModal(true)}
          />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase === "COUNTING" && sessionAccess.can("stocktake.count") && (
          <StocktakeCountingPanel
            canCancel={sessionAccess.can("stocktake.cancel")}
            rows={stocktakeState.rows}
            progress={countingWorkflow.countProgress}
            onUpdateRow={countingWorkflow.updateRow}
            onConfirmZero={countingWorkflow.confirmZeroCount}
            onCancel={() => setShowCancelModal(true)}
            onSubmit={() => setShowSubmitModal(true)}
          />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase === "REVIEW" &&
        stocktakeState.review && sessionAccess.can("stocktake.review") && (
          <StocktakeReviewPanel
            canCancel={sessionAccess.can("stocktake.cancel")}
            canRecount={sessionAccess.can("stocktake.recount")}
            canApprove={sessionAccess.can("stocktake.approve")}
            review={stocktakeState.review}
            totals={reviewWorkflow.reviewTotals}
            approvalBlocked={reviewWorkflow.approvalBlocked}
            onVariance={() => setShowVarianceModal(true)}
            onCancel={() => setShowCancelModal(true)}
            onRecount={() => setShowRecountModal(true)}
            onApprove={() => setShowApproveModal(true)}
          />
        )}

      {stocktakeState.sessionId !== null && (
        (stocktakeState.phase === "REVIEW" && !sessionAccess.can("stocktake.review")) ||
        (stocktakeState.phase === "COUNTING" && !sessionAccess.can("stocktake.count"))
      ) && (
        <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-slate-700">
          {copy.generic.authorizationRequired}
        </p>
      )}

      <StocktakeCycleStartModal
        open={active && showCycleModal}
        controller={cycleWorkflow}
        onClose={closeCycleModal}
        onStart={startCycle}
      />
      <StocktakeStartModal
        open={active && showLockModal}
        locking={lifecycle.locking}
        onClose={() => setShowLockModal(false)}
        onStart={start}
      />
      <StocktakeSubmitModal
        open={active && showSubmitModal}
        submitting={countingWorkflow.submitting}
        notes={countingWorkflow.notes}
        onNotesChange={countingWorkflow.setNotes}
        onClose={() => setShowSubmitModal(false)}
        onSubmit={submitCount}
      />
      <StocktakeApproveModal
        open={active && showApproveModal}
        busy={actionWorkflow.actionBusy}
        blocked={reviewWorkflow.approvalBlocked}
        password={actionWorkflow.approvePassword}
        notes={actionWorkflow.approveNotes}
        onPasswordChange={actionWorkflow.setApprovePassword}
        onNotesChange={actionWorkflow.setApproveNotes}
        onClose={() => setShowApproveModal(false)}
        onApprove={approve}
      />
      <StocktakeRecountModal
        open={active && showRecountModal}
        busy={actionWorkflow.actionBusy}
        reason={actionWorkflow.recountReason}
        username={actionWorkflow.authorizerUsername}
        password={actionWorkflow.authorizerPassword}
        onReasonChange={actionWorkflow.setRecountReason}
        onUsernameChange={actionWorkflow.setAuthorizerUsername}
        onPasswordChange={actionWorkflow.setAuthorizerPassword}
        onClose={() => setShowRecountModal(false)}
        onRecount={recount}
      />
      <StocktakeCancelModal
        open={active && showCancelModal}
        busy={actionWorkflow.actionBusy}
        reason={actionWorkflow.cancelReason}
        password={actionWorkflow.cancelPassword}
        onReasonChange={actionWorkflow.setCancelReason}
        onPasswordChange={actionWorkflow.setCancelPassword}
        onClose={() => setShowCancelModal(false)}
        onCancel={cancel}
      />
      <StocktakeVarianceModal
        open={active && showVarianceModal}
        review={stocktakeState.review}
        onClose={() => setShowVarianceModal(false)}
      />
    </div>
  );
}
