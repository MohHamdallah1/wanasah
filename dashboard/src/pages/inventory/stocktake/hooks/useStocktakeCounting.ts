import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import { toTotalPacks } from "../../inventoryUtils";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
} from "../types";
import {
  getErrorMessage,
  parseCountSheet,
  rowKey,
} from "../parsers";

interface UseStocktakeCountingArgs {
  locationId: number;
  companyScope: string;
  phaseKey: string;
  phase: StocktakePhase;
  sessionId: string | null;
  draftKey: string | null;
  authenticatedFetch: StocktakeAuthFetch;
  rows: StocktakeRow[];
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
  onSubmitted: (sessionId: string) => Promise<void>;
}

export function useStocktakeCounting({
  locationId,
  companyScope,
  phaseKey,
  phase,
  sessionId,
  draftKey,
  authenticatedFetch,
  rows,
  setRows,
  setReview,
  setSessionId,
  setPhase,
  onSubmitted,
}: UseStocktakeCountingArgs) {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadCountSheet = useCallback(async (sid: string) => {
    const raw = await authenticatedFetch(
      `/warehouse/unified/stocktake/${sid}/count-sheet`
    );
    const data = parseCountSheet(raw);

    const baseRows: StocktakeRow[] = data.map((item) => ({
      row_key: rowKey(
        item.product_variant_id,
        item.batch_id,
        item.stock_status
      ),
      product_variant_id: item.product_variant_id,
      batch_id: item.batch_id,
      stock_status: item.stock_status,
      product_name: item.product_name,
      batch_number: item.batch_number,
      expiry_date: item.expiry_date,
      packs_per_carton: item.packs_per_carton || 1,
      actual_cartons: 0,
      actual_loose_packs: 0,
      counted: false,
    }));

    const key =
      `wanasah_audit_draft:${companyScope}:${locationId}:${sid}`;
    const saved = localStorage.getItem(key);

    if (saved) {
      try {
        const parsed = JSON.parse(saved) as StocktakeRow[];
        const savedMap = new Map(
          parsed
            .filter((row) => typeof row?.row_key === "string")
            .map((row) => [row.row_key, row])
        );

        for (const row of baseRows) {
          const old = savedMap.get(row.row_key);
          if (!old) continue;

          row.actual_cartons = Math.max(
            0,
            Number(old.actual_cartons) || 0
          );
          row.actual_loose_packs = Math.max(
            0,
            Number(old.actual_loose_packs) || 0
          );
          row.counted = old.counted === true;
        }
      } catch {
        localStorage.removeItem(key);
      }
    }

    setSessionId(sid);
    setRows(baseRows);
    setReview(null);
    setPhase("COUNTING");
    localStorage.setItem(phaseKey, "COUNTING");
  }, [
    authenticatedFetch,
    companyScope,
    locationId,
    phaseKey,
    setPhase,
    setReview,
    setRows,
    setSessionId,
  ]);

  useEffect(() => {
    if (
      phase === "COUNTING" &&
      draftKey &&
      rows.length > 0
    ) {
      const timeoutId = window.setTimeout(() => {
        localStorage.setItem(
          draftKey,
          JSON.stringify(rows)
        );
      }, 800);

      return () => window.clearTimeout(timeoutId);
    }
  }, [draftKey, phase, rows]);

  const updateRow = useCallback((
    key: string,
    field: "actual_cartons" | "actual_loose_packs",
    val: number
  ) => {
    setRows((prev) => prev.map((row) => {
      if (row.row_key !== key) return row;

      const updated = {
        ...row,
        [field]: val,
        counted: true,
      };

      const ppc = updated.packs_per_carton || 1;

      if (updated.actual_loose_packs >= ppc) {
        updated.actual_cartons += Math.floor(
          updated.actual_loose_packs / ppc
        );
        updated.actual_loose_packs %= ppc;
      } else if (updated.actual_loose_packs < 0) {
        if (updated.actual_cartons > 0) {
          updated.actual_cartons -= 1;
          updated.actual_loose_packs = ppc - 1;
        } else {
          updated.actual_loose_packs = 0;
        }
      }

      return updated;
    }));
  }, [setRows]);

  const confirmZeroCount = useCallback((key: string) => {
    setRows((prev) => prev.map((row) => (
      row.row_key === key
        ? {
            ...row,
            actual_cartons: 0,
            actual_loose_packs: 0,
            counted: true,
          }
        : row
    )));
  }, [setRows]);

  const countProgress = useMemo(() => {
    const counted = rows.filter(
      (row) => row.counted
    ).length;

    return {
      total: rows.length,
      counted,
      remaining: rows.length - counted,
    };
  }, [rows]);

  const handleSubmit = useCallback(async () => {
    if (!sessionId) {
      toast.error(
        "خطأ حرج: جلسة الجرد غير موجودة."
      );
      return false;
    }

    const uncounted = rows.filter(
      (row) => !row.counted
    );
    if (uncounted.length > 0) {
      toast.error(
        `لا يمكن إنهاء الجرد: بقي ${uncounted.length} سطر لم يتم عده فعلياً.`
      );
      return false;
    }

    const items = rows.map((row) => ({
      product_variant_id: row.product_variant_id,
      batch_id: row.batch_id,
      stock_status: row.stock_status,
      actual_quantity: toTotalPacks(
        row.actual_cartons,
        row.actual_loose_packs,
        row.packs_per_carton
      ),
    }));

    setSubmitting(true);

    try {
      await authenticatedFetch(
        `/warehouse/unified/stocktake/${sessionId}/count`,
        {
          method: "POST",
          body: JSON.stringify({
            items,
            notes,
          }),
        }
      );

      if (draftKey) {
        localStorage.removeItem(draftKey);
      }
      setNotes("");
      await onSubmitted(sessionId);
      toast.success(
        "تم تثبيت محاولة العد. الأرقام أصبحت غير قابلة للتعديل وظهرت المقارنة للمراجعة."
      );
      return true;
    } catch (error: unknown) {
      toast.error(
        getErrorMessage(
          error,
          "فشل تثبيت محاولة الجرد."
        )
      );
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [
    authenticatedFetch,
    draftKey,
    notes,
    onSubmitted,
    rows,
    sessionId,
  ]);

  return {
    notes,
    setNotes,
    submitting,
    loadCountSheet,
    updateRow,
    confirmZeroCount,
    countProgress,
    handleSubmit,
  };
}
