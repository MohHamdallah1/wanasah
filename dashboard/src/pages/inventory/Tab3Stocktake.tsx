import {
  useCallback,
  useState,
} from "react";
import type { StocktakeAuthFetch } from "./stocktake/types";
import { useStocktakeSessions } from "./stocktake/hooks/useStocktakeSessions";
import { useStocktakeState } from "./stocktake/hooks/useStocktakeState";
import { useStocktakeCounting } from "./stocktake/hooks/useStocktakeCounting";
import { useStocktakeReview } from "./stocktake/hooks/useStocktakeReview";
import { useStocktakeActions } from "./stocktake/hooks/useStocktakeActions";
import { useStocktakeLifecycle } from "./stocktake/hooks/useStocktakeLifecycle";
import { useCycleCountStart } from "./stocktake/hooks/useCycleCountStart";
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
  locationId: number;
  companyId: string;
  isAuditLocked: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  onStocktakeChanged:
    () => void | Promise<void>;
}

export function Tab3Stocktake({
  locationId,
  companyId,
  isAuditLocked,
  authenticatedFetch,
  onStocktakeChanged,
}: Props) {
  const [showLockModal, setShowLockModal] =
    useState(false);
  const [showSubmitModal, setShowSubmitModal] =
    useState(false);
  const [showVarianceModal, setShowVarianceModal] =
    useState(false);
  const [showApproveModal, setShowApproveModal] =
    useState(false);
  const [showRecountModal, setShowRecountModal] =
    useState(false);
  const [showCancelModal, setShowCancelModal] =
    useState(false);
  const [showCycleModal, setShowCycleModal] =
    useState(false);

  const stocktakeState =
    useStocktakeState({
      companyId,
      locationId,
    });

  const {
    setRows,
    setReview,
  } = stocktakeState;

  const {
    sessions: activeSessions,
    total: activeSessionsTotal,
    nextCursor:
      activeSessionsNextCursor,
    loading: sessionsLoading,
    loadingMore:
      sessionsLoadingMore,
    loadFailed: sessionsLoadFailed,
    refreshSessions,
    loadMore: loadMoreSessions,
  } = useStocktakeSessions({
    locationId,
    authenticatedFetch,
  });

  const notifyStocktakeChanged =
    useCallback(async () => {
      await onStocktakeChanged();
      refreshSessions();
    }, [
      onStocktakeChanged,
      refreshSessions,
    ]);

  const clearRows = useCallback(() => {
    setRows([]);
  }, [setRows]);

  const clearReview = useCallback(() => {
    setReview(null);
  }, [setReview]);

  const reviewWorkflow =
    useStocktakeReview({
      locationId,
      phaseKey:
        stocktakeState.phaseKey,
      authenticatedFetch,
      review: stocktakeState.review,
      setReview:
        stocktakeState.setReview,
      setRows:
        stocktakeState.setRows,
      setSessionId:
        stocktakeState.setSessionId,
      setPhase:
        stocktakeState.setPhase,
    });

  const countingWorkflow =
    useStocktakeCounting({
      locationId,
      companyScope:
        stocktakeState.companyScope,
      phaseKey:
        stocktakeState.phaseKey,
      phase: stocktakeState.phase,
      sessionId:
        stocktakeState.sessionId,
      draftKey:
        stocktakeState.draftKey,
      authenticatedFetch,
      rows: stocktakeState.rows,
      setRows:
        stocktakeState.setRows,
      setReview:
        stocktakeState.setReview,
      setSessionId:
        stocktakeState.setSessionId,
      setPhase:
        stocktakeState.setPhase,
      onSubmitted:
        reviewWorkflow.loadReview,
    });

  const cycleWorkflow =
    useCycleCountStart({
      locationId,
      enabled: showCycleModal,
      authenticatedFetch,
      sessionKey: stocktakeState.sessionKey,
      phaseKey: stocktakeState.phaseKey,
      setSessionId: stocktakeState.setSessionId,
      loadCountSheet: countingWorkflow.loadCountSheet,
      notifyStocktakeChanged,
    });

  const actionWorkflow =
    useStocktakeActions({
      authenticatedFetch,
      sessionId:
        stocktakeState.sessionId,
      review: stocktakeState.review,
      draftKey:
        stocktakeState.draftKey,
      sessionKey:
        stocktakeState.sessionKey,
      phaseKey:
        stocktakeState.phaseKey,
      setRows:
        stocktakeState.setRows,
      setReview:
        stocktakeState.setReview,
      setSessionId:
        stocktakeState.setSessionId,
      setPhase:
        stocktakeState.setPhase,
      loadCountSheet:
        countingWorkflow.loadCountSheet,
      notifyStocktakeChanged,
    });

  const lifecycle =
    useStocktakeLifecycle({
      locationId,
      sessionKey:
        stocktakeState.sessionKey,
      phaseKey:
        stocktakeState.phaseKey,
      sessionId:
        stocktakeState.sessionId,
      activeSessions,
      activeSessionsTotal,
      sessionsLoading,
      sessionsLoadFailed,
      authenticatedFetch,
      loadCountSheet:
        countingWorkflow.loadCountSheet,
      loadReview:
        reviewWorkflow.loadReview,
      setSessionId:
        stocktakeState.setSessionId,
      setPhase:
        stocktakeState.setPhase,
      clearRows,
      clearReview,
      notifyStocktakeChanged,
    });

  const submitCount = async () => {
    if (
      await countingWorkflow.handleSubmit()
    ) {
      setShowSubmitModal(false);
    }
  };

  const approve = async () => {
    if (
      await actionWorkflow.handleApprove()
    ) {
      setShowApproveModal(false);
    }
  };

  const recount = async () => {
    if (
      await actionWorkflow.handleRecount()
    ) {
      setShowRecountModal(false);
    }
  };

  const cancel = async () => {
    if (
      await actionWorkflow.handleCancel()
    ) {
      setShowCancelModal(false);
    }
  };

  const start = async () => {
    if (
      await lifecycle.startStocktake()
    ) {
      setShowLockModal(false);
    }
  };

  const closeCycleModal = () => {
    if (cycleWorkflow.starting) return;
    setShowCycleModal(false);
    cycleWorkflow.resetForm();
  };

  const startCycle = async () => {
    if (await cycleWorkflow.startCycleCount()) {
      setShowCycleModal(false);
    }
  };

  return (
    <div className="flex flex-col gap-4 h-full flex-1 min-h-0 pt-1">
      <StocktakeSessionCenter
        sessions={activeSessions}
        total={activeSessionsTotal}
        loading={sessionsLoading}
        loadingMore={
          sessionsLoadingMore
        }
        nextCursor={
          activeSessionsNextCursor
        }
        currentSessionId={
          lifecycle.selectedSessionId
        }
        onRefresh={refreshSessions}
        onStartCycle={() => setShowCycleModal(true)}
        cycleStartDisabled={isAuditLocked || sessionsLoading}
        onLoadMore={loadMoreSessions}
        onOpenSession={
          lifecycle.openServerSession
        }
      />

      {stocktakeState.sessionId === null &&
        !isAuditLocked && (
          <StocktakeIdlePanel
            onStart={() =>
              setShowLockModal(true)
            }
          />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase ===
          "WAITING_INDEPENDENT" && (
          <StocktakeIndependentWait
            onCancel={() =>
              setShowCancelModal(true)
            }
          />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase ===
          "COUNTING" && (
          <StocktakeCountingPanel
            rows={stocktakeState.rows}
            progress={
              countingWorkflow.countProgress
            }
            onUpdateRow={
              countingWorkflow.updateRow
            }
            onConfirmZero={
              countingWorkflow.confirmZeroCount
            }
            onCancel={() =>
              setShowCancelModal(true)
            }
            onSubmit={() =>
              setShowSubmitModal(true)
            }
          />
        )}

      {stocktakeState.sessionId !== null &&
        stocktakeState.phase === "REVIEW" &&
        stocktakeState.review && (
          <StocktakeReviewPanel
            review={stocktakeState.review}
            totals={
              reviewWorkflow.reviewTotals
            }
            approvalBlocked={
              reviewWorkflow.approvalBlocked
            }
            onVariance={() =>
              setShowVarianceModal(true)
            }
            onCancel={() =>
              setShowCancelModal(true)
            }
            onRecount={() =>
              setShowRecountModal(true)
            }
            onApprove={() =>
              setShowApproveModal(true)
            }
          />
        )}

      <StocktakeCycleStartModal
        open={showCycleModal}
        controller={cycleWorkflow}
        onClose={closeCycleModal}
        onStart={startCycle}
      />

      <StocktakeStartModal
        open={showLockModal}
        locking={lifecycle.locking}
        onClose={() =>
          setShowLockModal(false)
        }
        onStart={start}
      />

      <StocktakeSubmitModal
        open={showSubmitModal}
        submitting={
          countingWorkflow.submitting
        }
        notes={countingWorkflow.notes}
        onNotesChange={
          countingWorkflow.setNotes
        }
        onClose={() =>
          setShowSubmitModal(false)
        }
        onSubmit={submitCount}
      />

      <StocktakeApproveModal
        open={showApproveModal}
        busy={actionWorkflow.actionBusy}
        blocked={
          reviewWorkflow.approvalBlocked
        }
        password={
          actionWorkflow.approvePassword
        }
        notes={
          actionWorkflow.approveNotes
        }
        onPasswordChange={
          actionWorkflow
            .setApprovePassword
        }
        onNotesChange={
          actionWorkflow.setApproveNotes
        }
        onClose={() =>
          setShowApproveModal(false)
        }
        onApprove={approve}
      />

      <StocktakeRecountModal
        open={showRecountModal}
        busy={actionWorkflow.actionBusy}
        reason={
          actionWorkflow.recountReason
        }
        username={
          actionWorkflow.authorizerUsername
        }
        password={
          actionWorkflow.authorizerPassword
        }
        onReasonChange={
          actionWorkflow.setRecountReason
        }
        onUsernameChange={
          actionWorkflow
            .setAuthorizerUsername
        }
        onPasswordChange={
          actionWorkflow
            .setAuthorizerPassword
        }
        onClose={() =>
          setShowRecountModal(false)
        }
        onRecount={recount}
      />

      <StocktakeCancelModal
        open={showCancelModal}
        busy={actionWorkflow.actionBusy}
        reason={
          actionWorkflow.cancelReason
        }
        password={
          actionWorkflow.cancelPassword
        }
        onReasonChange={
          actionWorkflow.setCancelReason
        }
        onPasswordChange={
          actionWorkflow.setCancelPassword
        }
        onClose={() =>
          setShowCancelModal(false)
        }
        onCancel={cancel}
      />

      <StocktakeVarianceModal
        open={showVarianceModal}
        review={stocktakeState.review}
        onClose={() =>
          setShowVarianceModal(false)
        }
      />
    </div>
  );
}
