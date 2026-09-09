import { useCallback, useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
} from "../types";
import { parseStocktakeReview } from "../parsers";

interface UseStocktakeReviewArgs {
  locationId: number;
  phaseKey: string;
  authenticatedFetch: StocktakeAuthFetch;
  review: StocktakeReview | null;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
}

export function useStocktakeReview({
  locationId,
  phaseKey,
  authenticatedFetch,
  review,
  setReview,
  setRows,
  setSessionId,
  setPhase,
}: UseStocktakeReviewArgs) {
  const loadReview = useCallback(async (sid: string) => {
    const raw = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/review`
    );
    const data = parseStocktakeReview(raw);

    if (data.location_id !== locationId) {
      throw new Error(
        "مرفوض: جلسة الجرد لا تطابق المستودع المحدد حالياً."
      );
    }

    setSessionId(sid);
    setReview(data);
    setRows([]);
    setPhase("REVIEW");
    localStorage.setItem(phaseKey, "REVIEW");
  }, [
    authenticatedFetch,
    locationId,
    phaseKey,
    setPhase,
    setReview,
    setRows,
    setSessionId,
  ]);

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
        if (line.variance_quantity === 0) {
          acc.matched += 1;
        }
        if (line.variance_quantity < 0) {
          acc.shortage += Math.abs(
            line.variance_quantity
          );
        }
        if (line.variance_quantity > 0) {
          acc.overage += line.variance_quantity;
        }
        if (line.variance_quantity !== 0) {
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
    review?.latest_attempt.requires_independent_recount &&
    !review?.independent_recount_satisfied
  );

  return {
    loadReview,
    reviewTotals,
    approvalBlocked,
  };
}
