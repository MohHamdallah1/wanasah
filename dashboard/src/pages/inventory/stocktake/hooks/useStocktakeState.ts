import { useMemo, useState } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import type {
  StocktakePhase,
  StocktakeReview,
} from "../types";

interface UseStocktakeStateArgs {
  companyId: string;
  locationId: number;
}

export function useStocktakeState({
  companyId,
  locationId,
}: UseStocktakeStateArgs) {
  const [phase, setPhase] =
    useState<StocktakePhase>("COUNTING");
  const [rows, setRows] =
    useState<StocktakeRow[]>([]);
  const [review, setReview] =
    useState<StocktakeReview | null>(null);
  const [sessionId, setSessionId] =
    useState<string | null>(null);

  const companyScope =
    companyId || "anonymous";

  const sessionKey = useMemo(
    () =>
      `unified_stocktake_session:${companyScope}:${locationId}`,
    [companyScope, locationId]
  );

  const phaseKey = useMemo(
    () =>
      `unified_stocktake_phase:${companyScope}:${locationId}`,
    [companyScope, locationId]
  );

  const draftKey = useMemo(
    () =>
      sessionId
        ? `wanasah_audit_draft:${companyScope}:${locationId}:${sessionId}`
        : null,
    [companyScope, locationId, sessionId]
  );

  return {
    companyScope,
    sessionKey,
    phaseKey,
    draftKey,
    phase,
    setPhase,
    rows,
    setRows,
    review,
    setReview,
    sessionId,
    setSessionId,
  };
}
