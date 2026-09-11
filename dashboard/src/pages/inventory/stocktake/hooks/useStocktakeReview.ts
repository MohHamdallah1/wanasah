import { parseInventoryCapabilities, hasInventoryPermission } from "@/hooks/useInventoryAccess";
import { useCallback, useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
} from "../types";
import { parseStocktakeReview } from "../parsers";
import { compareQuantity } from "../../quantity";

interface UseStocktakeReviewArgs {
  sessionLocationId: number | null;
  phaseKey: string;
  authenticatedFetch: StocktakeAuthFetch;
  review: StocktakeReview | null;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setSessionLocationId: Dispatch<SetStateAction<number | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
}

export function useStocktakeReview({
  sessionLocationId,
  phaseKey,
  authenticatedFetch,
  review,
  setReview,
  setRows,
  setSessionId,
  setSessionLocationId,
  setPhase,
}: UseStocktakeReviewArgs) {
  const loadReview = useCallback(
    async (
      sid: string,
      targetLocationId?: number
    ) => {
      const effectiveLocationId =
        targetLocationId ?? sessionLocationId;

      if (
        effectiveLocationId === null ||
        !Number.isInteger(effectiveLocationId) ||
        effectiveLocationId <= 0
      ) {
        throw new Error(
          "موقع جلسة الجرد الفعلي غير معروف."
        );
      }

      const capabilities = parseInventoryCapabilities(await authenticatedFetch(
        `/inventory/access/me?location_id=${effectiveLocationId}`
      ));
      if (capabilities.location_id !== effectiveLocationId) throw new Error("نطاق الصلاحيات غير مطابق.");
      if (!hasInventoryPermission(capabilities, 'stocktake.review')) {
        setSessionLocationId(effectiveLocationId);
        setSessionId(sid);
        setReview(null);
        setRows([]);
        setPhase("REVIEW");
        return;
      }

      const raw = await authenticatedFetch(
        `/warehouse/unified/stocktake/${sid}/review`
      );
      const data =
        parseStocktakeReview(raw);

      if (
        data.location_id !==
        effectiveLocationId
      ) {
        throw new Error(
          "مرفوض: جلسة الجرد لا تطابق موقع الجلسة الفعلي."
        );
      }

      setSessionLocationId(
        effectiveLocationId
      );
      setSessionId(sid);
      setReview(data);
      setRows([]);
      setPhase("REVIEW");
      localStorage.setItem(
        phaseKey,
        "REVIEW"
      );
    },
    [
      authenticatedFetch,
      phaseKey,
      sessionLocationId,
      setPhase,
      setReview,
      setRows,
      setSessionId,
      setSessionLocationId,
    ]
  );

  const reviewTotals = useMemo(() => {
    if (!review) {
      return {
        total: 0,
        matched: 0,
        shortage: 0,
        overage: 0,
        varianceItems: 0,
      };
    }

    return review.lines.reduce(
      (acc, line) => {
        acc.total += 1;
        if (
          compareQuantity(line.variance_quantity, "0") === 0
        ) {
          acc.matched += 1;
        }
        if (
          compareQuantity(line.variance_quantity, "0") < 0
        ) {
          acc.shortage += 1;
        }
        if (
          compareQuantity(line.variance_quantity, "0") > 0
        ) {
          acc.overage += 1;
        }
        if (
          compareQuantity(line.variance_quantity, "0") !== 0
        ) {
          acc.varianceItems += 1;
        }
        return acc;
      },
      {
        total: 0,
        matched: 0,
        shortage: 0,
        overage: 0,
        varianceItems: 0,
      }
    );
  }, [review]);

  const approvalBlocked = Boolean(
    review?.latest_attempt
      .requires_independent_recount &&
      !review
        ?.independent_recount_satisfied
  );

  return {
    loadReview,
    reviewTotals,
    approvalBlocked,
  };
}
