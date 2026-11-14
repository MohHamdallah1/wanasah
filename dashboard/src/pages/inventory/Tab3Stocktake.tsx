import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { RefreshCcw } from "lucide-react";
import type { StocktakeAuthFetch } from "./stocktake/types";
import { soleVerifiedActiveStocktake, useStocktakeSessions } from "./stocktake/hooks/useStocktakeSessions";
import { getErrorMessage } from "./stocktake/parsers";
import { useStocktakeState } from "./stocktake/hooks/useStocktakeState";
import { useStocktakeCounting } from "./stocktake/hooks/useStocktakeCounting";
import { useStocktakeReview } from "./stocktake/hooks/useStocktakeReview";
import { useStocktakeActions } from "./stocktake/hooks/useStocktakeActions";
import { useStocktakeLifecycle } from "./stocktake/hooks/useStocktakeLifecycle";
import { useCycleCountStart } from "./stocktake/hooks/useCycleCountStart";
import { useStocktakeCopy } from "./stocktake/copy";
import { useStocktakeUiCopy } from "./stocktake/uiCopy";
import { StocktakeSessionCenter } from "./stocktake/StocktakeSessionCenter";
import { StocktakeHistoryDialog } from "./stocktake/StocktakeHistoryDialog";
import { StocktakeDiscoveredModal } from "./stocktake/StocktakeDiscoveredModal";
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
  locationName?: string | null;
  warehouseSelector?: ReactNode;
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
  locationName,
  warehouseSelector,
  companyId,
  isAuditLocked,
  authenticatedFetch,
  onStocktakeChanged,
}: Props) {
  const { dir } = useStocktakeCopy();
  const { copy: uiCopy } = useStocktakeUiCopy();
  const [showLockModal, setShowLockModal] = useState(false);
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [showVarianceModal, setShowVarianceModal] = useState(false);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRecountModal, setShowRecountModal] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<{ sessionId: string; locationId: number } | null>(null);
  const autoRecoveryAttemptRef = useRef<string | null>(null);
  const [showCycleModal, setShowCycleModal] = useState(false);
  const [showDiscoveredModal, setShowDiscoveredModal] = useState(false);
  const [showSessions, setShowSessions] = useState(false);

  const stocktakeState = useStocktakeState({ companyId, locationId });
  const warehouseAccess = useInventoryAccess(locationId);
  const sessionAccess = useInventoryAccess(stocktakeState.sessionLocationId ?? locationId);
  const canReadStocktake = warehouseAccess.can("stocktake.read");

  // A retained tab must not leave a portal open after access or location changes.
  // Its count/review drafts remain owned by the location-keyed existing state hook.
  useEffect(() => {
    if (!active || !canReadStocktake) setShowSessions(false);
  }, [active, canReadStocktake, locationId]);
  const durableIdentity = useMemo(() => warehouseAccess.data
    ? {
        companyId: warehouseAccess.data.company_id,
        backofficeUserId: warehouseAccess.data.backoffice_user_id,
      }
    : null, [warehouseAccess.data]);

  const { setRows, setReview } = stocktakeState;
  const {
    sessions: activeSessions,
    total: activeSessionsTotal,
    nextCursor: activeSessionsNextCursor,
    loading: sessionsLoading,
    loadingMore: sessionsLoadingMore,
    loadFailed: sessionsLoadFailed,
    verifiedLocationId,
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
    locationName,
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
    sessionId: cancelTarget?.sessionId ?? stocktakeState.sessionId,
    sessionLocationId: cancelTarget?.locationId ?? stocktakeState.sessionLocationId,
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

  const openServerSession = lifecycle.openServerSession;
  // Logout clears localStorage, not the signed server stocktake. Once a single
  // server session is verified for this warehouse, restore its real context.
  // The attempt key prevents loops on transient/denied count-sheet reads.
  const soleServerSession = soleVerifiedActiveStocktake(
    activeSessions, activeSessionsTotal, verifiedLocationId, locationId,
  );
  useEffect(() => {
    if (!active || !canReadStocktake || !durableIdentity ||
        stocktakeState.sessionId !== null || !soleServerSession ||
        sessionsLoading || sessionsLoadFailed ||
        localStorage.getItem(stocktakeState.sessionKey)) return;
    const attemptKey = `${companyId}:${locationId}:${soleServerSession.id}`;
    if (autoRecoveryAttemptRef.current === attemptKey) return;
    autoRecoveryAttemptRef.current = attemptKey;
    void openServerSession(soleServerSession);
  }, [active, canReadStocktake, companyId, durableIdentity, locationId,
      soleServerSession, sessionsLoading, sessionsLoadFailed,
      stocktakeState.sessionId, stocktakeState.sessionKey,
      openServerSession]);

  const openVerifiedCancellation = async () => {
    if (!soleServerSession || !warehouseAccess.can("stocktake.cancel")) return;
    try {
      const target = await lifecycle.prepareCancellation(soleServerSession);
      if (!target) return;
      setCancelTarget(target);
      setShowCancelModal(true);
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, uiCopy.sessions.recovery.cancelFailed));
    }
  };

  const closeCancelModal = () => {
    // Dismissing the modal leaves the server session and user's count draft
    // untouched. The command only receives this verified ID while modal opens.
    setShowCancelModal(false);
    setCancelTarget(null);
  };

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
    if (await actionWorkflow.handleCancel()) {
      setShowCancelModal(false);
      setCancelTarget(null);
    }
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
  const selectedSession = activeSessions.find((session) =>
    session.id === Number(stocktakeState.sessionId) &&
    session.location_id === locationId,
  );
  const cycleStartDisabled =
    isAuditLocked || sessionsLoading || !warehouseAccess.can("stocktake.start");
  const isIdle = stocktakeState.sessionId === null;
  const serverSessionsVerified = verifiedLocationId === locationId;
  const activeServerCount = serverSessionsVerified ? activeSessionsTotal : null;
  const recoveryText = uiCopy.sessions.recovery;
  const warehouseLabel = locationName || (dir === "rtl" ? "المستودع المحدد" : "selected warehouse");
  const workspacePhase = isIdle ? "idle" : stocktakeState.phase.toLowerCase();

  return (
    <div dir={dir} className="inventory-view inventory-stocktake flex h-full min-h-0 flex-1 flex-col gap-2 pt-0">
      <div data-stocktake-toolbar="true"
        className="relative flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white/90 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {warehouseSelector}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StocktakeSessionCenter
            sessions={activeSessions}
            total={activeSessionsTotal}
            loading={sessionsLoading}
            loadingMore={sessionsLoadingMore}
            nextCursor={activeSessionsNextCursor}
            currentSessionId={lifecycle.selectedSessionId}
            canRead={active && canReadStocktake}
            open={showSessions}
            onOpenChange={setShowSessions}
            onLoadMore={loadMoreSessions}
            onOpenSession={async (session) => {
              await lifecycle.openServerSession(session);
              setShowSessions(false);
            }}
          />
          <StocktakeHistoryDialog
            active={active}
            locationId={locationId}
            canRead={canReadStocktake}
            canReview={warehouseAccess.can("stocktake.review")}
            canLedgerRead={warehouseAccess.can("ledger.read")}
            authenticatedFetch={authenticatedFetch}
          />
          <button type="button" onClick={refreshSessions} disabled={sessionsLoading}
            aria-label={uiCopy.sessions.refresh} title={uiCopy.sessions.refresh}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50 disabled:opacity-40">
            <RefreshCcw className={`h-4 w-4 ${sessionsLoading ? "animate-spin" : ""}`} aria-hidden="true" />
            <span>{uiCopy.sessions.refresh}</span>
          </button>
          <button type="button" onClick={() => setShowCycleModal(true)}
            disabled={cycleStartDisabled}
            title={cycleStartDisabled ? uiCopy.sessions.cycleLocked : uiCopy.sessions.cycleHint}
            className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-black text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40">
            {uiCopy.sessions.cycleAction}
          </button>
        </div>
      </div>

      {/* The original door and both count types occupy one workspace; never parallel tables. */}
      <div data-stocktake-workspace={workspacePhase}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {isIdle ? (
          <div className="flex min-h-0 flex-1 flex-col gap-3 p-3" data-stocktake-server-recovery="true">
            {!canReadStocktake && (
              <p role="alert" className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                {recoveryText.permission}
              </p>
            )}
            {canReadStocktake && !serverSessionsVerified && !sessionsLoadFailed && (
              <p role="status" className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
                {recoveryText.checking}
              </p>
            )}
            {canReadStocktake && sessionsLoadFailed && (
              <div role="alert" className="rounded-xl border border-slate-300 bg-white p-4 text-sm text-slate-700">
                <p>{recoveryText.unavailable}</p>
                <button type="button" onClick={refreshSessions}
                  className="mt-3 rounded-lg border border-slate-300 px-3 py-2 font-bold hover:bg-slate-50">
                  {recoveryText.retry}
                </button>
              </div>
            )}
            {canReadStocktake && serverSessionsVerified && soleServerSession && (
              <section role="status" data-stocktake-recoverable-session="true"
                className="rounded-xl border border-amber-200 bg-amber-50/70 p-4 text-sm text-slate-800">
                <p className="font-bold">{recoveryText.found(
                  warehouseLabel, soleServerSession.reference_number,
                  uiCopy.sessions.statuses[soleServerSession.status],
                )}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button type="button" onClick={() => void lifecycle.openServerSession(soleServerSession)}
                    className="rounded-lg bg-slate-800 px-4 py-2 font-bold text-white hover:bg-slate-700">
                    {recoveryText.resume}
                  </button>
                  {warehouseAccess.can("stocktake.cancel") && (
                    <button type="button" onClick={() => void openVerifiedCancellation()}
                      className="rounded-lg border border-red-300 bg-white px-4 py-2 font-bold text-red-800 hover:bg-red-50">
                      {recoveryText.cancel}
                    </button>
                  )}
                </div>
              </section>
            )}
            {canReadStocktake && serverSessionsVerified && activeServerCount !== null &&
              activeServerCount > 1 && (
              <section role="status" className="rounded-xl border border-amber-200 bg-white p-4 text-sm text-slate-700">
                <p>{recoveryText.multiple(warehouseLabel, activeServerCount)}</p>
                <button type="button" onClick={() => setShowSessions(true)}
                  className="mt-3 rounded-lg border border-slate-300 px-4 py-2 font-bold hover:bg-slate-50">
                  {recoveryText.choose}
                </button>
              </section>
            )}
            {canReadStocktake && serverSessionsVerified && activeServerCount === 0 && isAuditLocked && (
              <section role="alert" className="rounded-xl border border-slate-300 bg-white p-4 text-sm text-slate-700">
                <p>{recoveryText.mismatch(warehouseLabel)}</p>
                <button type="button" onClick={refreshSessions}
                  className="mt-3 rounded-lg border border-slate-300 px-4 py-2 font-bold hover:bg-slate-50">
                  {recoveryText.retry}
                </button>
              </section>
            )}
            {canReadStocktake && serverSessionsVerified && activeServerCount !== null &&
              activeServerCount !== 1 && !isAuditLocked && warehouseAccess.can("stocktake.start") && (
              <StocktakeIdlePanel onStart={() => setShowLockModal(true)} />
            )}
          </div>
        ) : (
          <>
            {selectedSession && (
              <div role="status" data-stocktake-open-session="true"
                className="mb-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700">
                {warehouseLabel} · {selectedSession.reference_number}
                {" · "}{uiCopy.sessions.statuses[selectedSession.status]}
              </div>
            )}
            {stocktakeState.phase === "WAITING_INDEPENDENT" && (
              <StocktakeIndependentWait
                canCancel={sessionAccess.can("stocktake.cancel")}
                onCancel={() => setShowCancelModal(true)}
              />
            )}

            {stocktakeState.phase === "COUNTING" && sessionAccess.can("stocktake.count") && (
              <StocktakeCountingPanel
                warehouseName={stocktakeState.sessionLocationId === locationId ? locationName : null}
                scopeProductName={selectedSession?.scope_product_name ?? null}
                stocktakeType={selectedSession?.stocktake_type ?? null}
                canCancel={sessionAccess.can("stocktake.cancel")}
                rows={stocktakeState.rows}
                progress={countingWorkflow.countProgress}
                onUpdateRow={countingWorkflow.updateRow}
                onConfirmZero={countingWorkflow.confirmZeroCount}
                onUndoCount={countingWorkflow.undoRowCount}
                onUpdatePart={countingWorkflow.updateCountPart}
                onAddDiscovered={() => setShowDiscoveredModal(true)}
                onRemoveDiscovered={countingWorkflow.removeDiscoveredRow}
                onCancel={() => setShowCancelModal(true)}
                onSubmit={() => setShowSubmitModal(true)}
              />
            )}

            {stocktakeState.phase === "REVIEW" && stocktakeState.review && sessionAccess.can("stocktake.review") && (
              <StocktakeReviewPanel
                warehouseName={stocktakeState.sessionLocationId === locationId ? locationName : null}
                scopeProductName={selectedSession?.scope_product_name ?? null}
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

            {(
              (stocktakeState.phase === "REVIEW" && !sessionAccess.can("stocktake.review")) ||
              (stocktakeState.phase === "COUNTING" && !sessionAccess.can("stocktake.count"))
            ) && (
              <div role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-slate-700">
                <p>{recoveryText.permission}</p>
                {sessionAccess.can("stocktake.cancel") && (
                  <button type="button" onClick={() => setShowCancelModal(true)}
                    className="mt-3 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-bold text-red-800 hover:bg-red-50">
                    {recoveryText.cancel}
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>

      <StocktakeDiscoveredModal
        open={active && showDiscoveredModal && stocktakeState.phase === "COUNTING" && sessionAccess.can("stocktake.count")}
        sessionId={stocktakeState.sessionId}
        authenticatedFetch={authenticatedFetch}
        onClose={() => setShowDiscoveredModal(false)}
        onAdd={countingWorkflow.addDiscoveredRow}
      />
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
        onClose={closeCancelModal}
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
