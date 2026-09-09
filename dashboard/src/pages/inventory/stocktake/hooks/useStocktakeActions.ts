import { useCallback, useState } from "react";
import { toast } from "sonner";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
} from "../types";
import {
  getErrorMessage,
  parseRecountRequiresIndependent,
  readMessage,
} from "../parsers";

interface UseStocktakeActionsArgs {
  authenticatedFetch: StocktakeAuthFetch;
  sessionId: string | null;
  review: StocktakeReview | null;
  draftKey: string | null;
  sessionKey: string;
  phaseKey: string;
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
  loadCountSheet: (sessionId: string) => Promise<void>;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useStocktakeActions({
  authenticatedFetch,
  sessionId,
  review,
  draftKey,
  sessionKey,
  phaseKey,
  setRows,
  setReview,
  setSessionId,
  setPhase,
  loadCountSheet,
  notifyStocktakeChanged,
}: UseStocktakeActionsArgs) {
  const [approvePassword, setApprovePassword] =
    useState("");
  const [approveNotes, setApproveNotes] =
    useState("");
  const [recountReason, setRecountReason] =
    useState("");
  const [authorizerUsername, setAuthorizerUsername] =
    useState("");
  const [authorizerPassword, setAuthorizerPassword] =
    useState("");
  const [cancelReason, setCancelReason] =
    useState("");
  const [cancelPassword, setCancelPassword] =
    useState("");
  const [actionBusy, setActionBusy] =
    useState(false);

  const handleApprove = useCallback(async () => {
    if (!sessionId) return false;

    if (!review) {
      toast.error(
        "مراجعة الجرد الحالية غير موجودة."
      );
      return false;
    }

    if (!approvePassword) {
      toast.error(
        "أدخل كلمة مرور المشرف للاعتماد النهائي."
      );
      return false;
    }

    setActionBusy(true);

    try {
      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/approve`,
        {
          method: "POST",
          body: JSON.stringify({
            count_attempt_id:
              review.latest_attempt.id,
            password: approvePassword,
            notes: approveNotes || null,
          }),
        }
      );

      if (draftKey) {
        localStorage.removeItem(draftKey);
      }
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);

      setApprovePassword("");
      setApproveNotes("");
      setReview(null);
      setRows([]);
      setSessionId(null);

      await notifyStocktakeChanged();

      toast.success(
        readMessage(raw) ||
          "تم اعتماد الجرد وترحيل الفروقات بنجاح."
      );
      return true;
    } catch (error: unknown) {
      toast.error(
        getErrorMessage(
          error,
          "فشل اعتماد الجرد."
        )
      );
      return false;
    } finally {
      setActionBusy(false);
    }
  }, [
    approveNotes,
    approvePassword,
    authenticatedFetch,
    draftKey,
    notifyStocktakeChanged,
    phaseKey,
    review,
    sessionId,
    sessionKey,
    setReview,
    setRows,
    setSessionId,
  ]);

  const handleRecount = useCallback(async () => {
    if (!sessionId) return null;

    if (!review) {
      toast.error(
        "مراجعة الجرد الحالية غير موجودة."
      );
      return null;
    }

    if (recountReason.trim().length < 5) {
      toast.error(
        "اكتب سبباً واضحاً لإعادة الجرد."
      );
      return null;
    }

    if (
      !authorizerUsername.trim() ||
      !authorizerPassword
    ) {
      toast.error(
        "أدخل بيانات المستخدم المخول لتفويض إعادة الجرد."
      );
      return null;
    }

    setActionBusy(true);

    try {
      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/recount`,
        {
          method: "POST",
          body: JSON.stringify({
            count_attempt_id:
              review.latest_attempt.id,
            reason: recountReason.trim(),
            authorizer_username:
              authorizerUsername.trim(),
            authorizer_password:
              authorizerPassword,
          }),
        }
      );

      if (draftKey) {
        localStorage.removeItem(draftKey);
      }

      setRecountReason("");
      setAuthorizerUsername("");
      setAuthorizerPassword("");
      setReview(null);

      if (
        parseRecountRequiresIndependent(raw)
      ) {
        setRows([]);
        setPhase("WAITING_INDEPENDENT");
        localStorage.setItem(
          phaseKey,
          "WAITING_INDEPENDENT"
        );
        toast.success(
          "تم تفويض إعادة عد مستقلة. يجب أن ينفذ المحاولة التالية مستخدم مخول آخر."
        );
        return "WAITING_INDEPENDENT" as const;
      }

      await loadCountSheet(sessionId);
      toast.success(
        "تم تفويض Recount جديد. المحاولة السابقة محفوظة بالكامل."
      );
      return "COUNTING" as const;
    } catch (error: unknown) {
      toast.error(
        getErrorMessage(
          error,
          "فشل تفويض إعادة الجرد."
        )
      );
      return null;
    } finally {
      setActionBusy(false);
    }
  }, [
    authenticatedFetch,
    authorizerPassword,
    authorizerUsername,
    draftKey,
    loadCountSheet,
    phaseKey,
    recountReason,
    review,
    sessionId,
    setPhase,
    setReview,
    setRows,
  ]);

  const handleCancel = useCallback(async () => {
    if (!sessionId) return false;

    if (cancelReason.trim().length < 5) {
      toast.error(
        "اكتب سبباً واضحاً لإلغاء الجرد."
      );
      return false;
    }

    if (!cancelPassword) {
      toast.error(
        "أدخل كلمة مرور المشرف لتأكيد الإلغاء."
      );
      return false;
    }

    setActionBusy(true);

    try {
      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/cancel`,
        {
          method: "POST",
          body: JSON.stringify({
            password: cancelPassword,
            reason: cancelReason.trim(),
          }),
        }
      );

      if (draftKey) {
        localStorage.removeItem(draftKey);
      }
      localStorage.removeItem(sessionKey);
      localStorage.removeItem(phaseKey);

      setCancelReason("");
      setCancelPassword("");
      setReview(null);
      setRows([]);
      setSessionId(null);

      await notifyStocktakeChanged();

      toast.success(
        readMessage(raw) ||
          "تم إلغاء جلسة الجرد وفك الأقفال."
      );
      return true;
    } catch (error: unknown) {
      toast.error(
        getErrorMessage(
          error,
          "فشل إلغاء جلسة الجرد."
        )
      );
      return false;
    } finally {
      setActionBusy(false);
    }
  }, [
    authenticatedFetch,
    cancelPassword,
    cancelReason,
    draftKey,
    notifyStocktakeChanged,
    phaseKey,
    sessionId,
    sessionKey,
    setReview,
    setRows,
    setSessionId,
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
