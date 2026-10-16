import { useCallback, useState } from "react";
import { toast } from "sonner";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import { useStocktakeCopy } from "../copy";
import {
  executeStocktakeDurableCommand,
  type StocktakeDurableIdentity,
} from "../durableCommand";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
} from "../types";
import {
  getErrorMessage,
  parseRecountRequiresIndependent,
} from "../parsers";

interface UseStocktakeActionsArgs {
  authenticatedFetch: StocktakeAuthFetch;
  durableIdentity: StocktakeDurableIdentity | null;
  sessionId: string | null;
  sessionLocationId: number | null;
  review: StocktakeReview | null;
  draftKey: string | null;
  sessionKey: string;
  phaseKey: string;
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setSessionLocationId: Dispatch<SetStateAction<number | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
  loadCountSheet: (sessionId: string, sessionLocationId?: number) => Promise<void>;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useStocktakeActions({
  authenticatedFetch,
  durableIdentity,
  sessionId,
  sessionLocationId,
  review,
  draftKey,
  sessionKey,
  phaseKey,
  setRows,
  setReview,
  setSessionId,
  setSessionLocationId,
  setPhase,
  loadCountSheet,
  notifyStocktakeChanged,
}: UseStocktakeActionsArgs) {
  const { copy } = useStocktakeCopy();
  const [approvePassword, setApprovePassword] = useState("");
  const [approveNotes, setApproveNotes] = useState("");
  const [recountReason, setRecountReason] = useState("");
  const [authorizerUsername, setAuthorizerUsername] = useState("");
  const [authorizerPassword, setAuthorizerPassword] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [cancelPassword, setCancelPassword] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const clearSelectedSession = useCallback(() => {
    setReview(null);
    setRows([]);
    setSessionId(null);
    setSessionLocationId(null);
  }, [setReview, setRows, setSessionId, setSessionLocationId]);

  const handleApprove = useCallback(async () => {
    if (!sessionId) return false;
    if (!review) {
      toast.error(copy.action.reviewUnavailable);
      return false;
    }
    if (!sessionLocationId || !durableIdentity) {
      toast.error(copy.action.scopeUnavailable);
      return false;
    }
    if (!approvePassword) {
      toast.error(copy.action.approvePasswordRequired);
      return false;
    }

    setActionBusy(true);
    try {
      await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "approve",
        target: `${sessionLocationId}:${sessionId}`,
        payload: {
          count_attempt_id: review.latest_attempt.id,
          password: approvePassword,
          notes: approveNotes || null,
        },
        send: (body) => authenticatedFetch(
          `/warehouse/unified/stocktake/${sessionId}/approve`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      });

      if (draftKey) localStorage.removeItem(draftKey);
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);
      setApprovePassword("");
      setApproveNotes("");
      clearSelectedSession();
      await notifyStocktakeChanged();
      toast.success(copy.action.approved);
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.approveFailed));
      return false;
    } finally {
      setActionBusy(false);
    }
  }, [approveNotes, approvePassword, authenticatedFetch, clearSelectedSession, copy.action, copy.generic.approveFailed, draftKey, durableIdentity, notifyStocktakeChanged, phaseKey, review, sessionId, sessionKey, sessionLocationId]);

  const handleRecount = useCallback(async () => {
    if (!sessionId) return null;
    if (!review) {
      toast.error(copy.action.reviewUnavailable);
      return null;
    }
    if (!sessionLocationId || !durableIdentity) {
      toast.error(copy.action.scopeUnavailable);
      return null;
    }
    if (recountReason.trim().length < 5) {
      toast.error(copy.action.recountReasonRequired);
      return null;
    }
    if (!authorizerUsername.trim() || !authorizerPassword) {
      toast.error(copy.action.recountCredentialsRequired);
      return null;
    }

    setActionBusy(true);
    try {
      const raw = await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "recount",
        target: `${sessionLocationId}:${sessionId}`,
        payload: {
          count_attempt_id: review.latest_attempt.id,
          reason: recountReason.trim(),
          authorizer_username: authorizerUsername.trim(),
          authorizer_password: authorizerPassword,
        },
        send: (body) => authenticatedFetch(
          `/warehouse/unified/stocktake/${sessionId}/recount`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      });

      if (draftKey) localStorage.removeItem(draftKey);
      setRecountReason("");
      setAuthorizerUsername("");
      setAuthorizerPassword("");
      setReview(null);

      if (parseRecountRequiresIndependent(raw)) {
        setRows([]);
        setPhase("WAITING_INDEPENDENT");
        localStorage.setItem(phaseKey, "WAITING_INDEPENDENT");
        toast.success(copy.action.independentRecountAuthorized);
        return "WAITING_INDEPENDENT" as const;
      }

      await loadCountSheet(sessionId, sessionLocationId);
      toast.success(copy.action.recounted);
      return "COUNTING" as const;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.recountFailed));
      return null;
    } finally {
      setActionBusy(false);
    }
  }, [authenticatedFetch, authorizerPassword, authorizerUsername, copy.action, copy.generic.recountFailed, draftKey, durableIdentity, loadCountSheet, phaseKey, recountReason, review, sessionId, sessionLocationId, setPhase, setReview, setRows]);

  const handleCancel = useCallback(async () => {
    if (!sessionId) return false;
    if (!sessionLocationId || !durableIdentity) {
      toast.error(copy.action.scopeUnavailable);
      return false;
    }
    if (cancelReason.trim().length < 5) {
      toast.error(copy.action.cancelReasonRequired);
      return false;
    }
    if (!cancelPassword) {
      toast.error(copy.action.cancelPasswordRequired);
      return false;
    }

    setActionBusy(true);
    try {
      await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "cancel",
        target: `${sessionLocationId}:${sessionId}`,
        payload: { password: cancelPassword, reason: cancelReason.trim() },
        send: (body) => authenticatedFetch(
          `/warehouse/unified/stocktake/${sessionId}/cancel`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      });

      if (draftKey) localStorage.removeItem(draftKey);
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);
      setCancelReason("");
      setCancelPassword("");
      clearSelectedSession();
      await notifyStocktakeChanged();
      toast.success(copy.action.cancelled);
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.cancelFailed));
      return false;
    } finally {
      setActionBusy(false);
    }
  }, [authenticatedFetch, cancelPassword, cancelReason, clearSelectedSession, copy.action, copy.generic.cancelFailed, draftKey, durableIdentity, notifyStocktakeChanged, phaseKey, sessionId, sessionKey, sessionLocationId]);

  return {
    approvePassword,
    setApprovePassword,
    approveNotes,
    setApproveNotes,
    recountReason,
    setRecountReason,
    authorizerUsername,
    setAuthorizerUsername,
    authorizerPassword,
    setAuthorizerPassword,
    cancelReason,
    setCancelReason,
    cancelPassword,
    setCancelPassword,
    actionBusy,
    handleApprove,
    handleRecount,
    handleCancel,
  };
}
