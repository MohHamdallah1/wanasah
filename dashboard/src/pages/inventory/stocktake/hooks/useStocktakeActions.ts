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
  loadCountSheet: (
    sessionId: string,
    sessionLocationId?: number
  ) => Promise<void>;
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
  const { copy, isArabic } = useStocktakeCopy();
  const [approvePassword, setApprovePassword] = useState("");
  const [approveNotes, setApproveNotes] = useState("");
  const [recountReason, setRecountReason] = useState("");
  const [authorizerUsername, setAuthorizerUsername] = useState("");
  const [authorizerPassword, setAuthorizerPassword] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [cancelPassword, setCancelPassword] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const scopeUnavailable = isArabic
    ? "تعذر تثبيت هوية المستخدم ونطاق جلسة الجرد. أعد تحميل البيانات ثم حاول مجدداً."
    : "The user identity or stocktake session scope is unavailable. Refresh the data and try again.";

  const clearSelectedSession = useCallback(() => {
    setReview(null);
    setRows([]);
    setSessionId(null);
    setSessionLocationId(null);
  }, [setReview, setRows, setSessionId, setSessionLocationId]);

  const handleApprove = useCallback(async () => {
    if (!sessionId) return false;
    if (!review) {
      toast.error(isArabic ? "مراجعة الجرد الحالية غير موجودة." : "The current stocktake review is unavailable.");
      return false;
    }
    if (!sessionLocationId || !durableIdentity) {
      toast.error(scopeUnavailable);
      return false;
    }
    if (!approvePassword) {
      toast.error(isArabic ? "أدخل كلمة مرور المشرف للاعتماد النهائي." : "Enter the supervisor password to approve the stocktake.");
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
  }, [
    approveNotes,
    approvePassword,
    authenticatedFetch,
    clearSelectedSession,
    copy.action.approved,
    copy.generic.approveFailed,
    draftKey,
    durableIdentity,
    isArabic,
    notifyStocktakeChanged,
    phaseKey,
    review,
    scopeUnavailable,
    sessionId,
    sessionKey,
    sessionLocationId,
  ]);

  const handleRecount = useCallback(async () => {
    if (!sessionId) return null;
    if (!review) {
      toast.error(isArabic ? "مراجعة الجرد الحالية غير موجودة." : "The current stocktake review is unavailable.");
      return null;
    }
    if (!sessionLocationId || !durableIdentity) {
      toast.error(scopeUnavailable);
      return null;
    }
    if (recountReason.trim().length < 5) {
      toast.error(isArabic ? "اكتب سبباً واضحاً لإعادة الجرد." : "Enter a clear recount reason.");
      return null;
    }
    if (!authorizerUsername.trim() || !authorizerPassword) {
      toast.error(isArabic ? "أدخل بيانات المستخدم المخول لتفويض إعادة الجرد." : "Enter the authorized user's credentials for the recount.");
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
        toast.success(isArabic
          ? "تم تفويض إعادة عد مستقلة. يجب أن ينفذ المحاولة التالية مستخدم مخول آخر."
          : "An independent recount was authorized. A different authorized user must perform the next attempt.");
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
  }, [
    authenticatedFetch,
    authorizerPassword,
    authorizerUsername,
    copy.action.recounted,
    copy.generic.recountFailed,
    draftKey,
    durableIdentity,
    isArabic,
    loadCountSheet,
    phaseKey,
    recountReason,
    review,
    scopeUnavailable,
    sessionId,
    sessionLocationId,
    setPhase,
    setReview,
    setRows,
  ]);

  const handleCancel = useCallback(async () => {
    if (!sessionId) return false;
    if (!sessionLocationId || !durableIdentity) {
      toast.error(scopeUnavailable);
      return false;
    }
    if (cancelReason.trim().length < 5) {
      toast.error(isArabic ? "اكتب سبباً واضحاً لإلغاء الجرد." : "Enter a clear cancellation reason.");
      return false;
    }
    if (!cancelPassword) {
      toast.error(isArabic ? "أدخل كلمة مرور المشرف لتأكيد الإلغاء." : "Enter the supervisor password to confirm cancellation.");
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
  }, [
    authenticatedFetch,
    cancelPassword,
    cancelReason,
    clearSelectedSession,
    copy.action.cancelled,
    copy.generic.cancelFailed,
    draftKey,
    durableIdentity,
    isArabic,
    notifyStocktakeChanged,
    phaseKey,
    scopeUnavailable,
    sessionId,
    sessionKey,
    sessionLocationId,
  ]);

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
