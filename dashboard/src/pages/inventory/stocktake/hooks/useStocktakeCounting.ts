import { parseInventoryCapabilities, hasInventoryPermission } from "@/hooks/useInventoryAccess";
import { useCallback, useEffect, useMemo, useState } from "react";
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
  parseCountSheet,
  rowKey,
} from "../parsers";

interface UseStocktakeCountingArgs {
  companyScope: string;
  phaseKey: string;
  phase: StocktakePhase;
  sessionId: string | null;
  sessionLocationId: number | null;
  draftKey: string | null;
  authenticatedFetch: StocktakeAuthFetch;
  rows: StocktakeRow[];
  setRows: Dispatch<SetStateAction<StocktakeRow[]>>;
  setReview: Dispatch<SetStateAction<StocktakeReview | null>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setSessionLocationId: Dispatch<SetStateAction<number | null>>;
  setPhase: Dispatch<SetStateAction<StocktakePhase>>;
  onSubmitted: (
    sessionId: string,
    sessionLocationId: number
  ) => Promise<void>;
}

export function useStocktakeCounting({
  companyScope,
  phaseKey,
  phase,
  sessionId,
  sessionLocationId,
  draftKey,
  authenticatedFetch,
  rows,
  setRows,
  setReview,
  setSessionId,
  setSessionLocationId,
  setPhase,
  onSubmitted,
}: UseStocktakeCountingArgs) {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadCountSheet = useCallback(
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
      if (!hasInventoryPermission(capabilities, 'stocktake.count')) {
        setSessionLocationId(effectiveLocationId);
        setSessionId(sid);
        setReview(null);
        setRows([]);
        setPhase("COUNTING");
        return;
      }

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
        base_uom_id: item.base_uom_id,
        base_uom_code: item.base_uom_code,
        base_uom_name: item.base_uom_name,
        quantity_scale: item.quantity_scale,
        quantity_step: item.quantity_step,
        actual_quantity: "0",
        counted: false,
      }));

      const key =
        `wanasah_audit_draft:${companyScope}:${effectiveLocationId}:${sid}`;
      const saved = localStorage.getItem(key);

      if (saved) {
        try {
          const parsed =
            JSON.parse(saved) as StocktakeRow[];
          const savedMap = new Map(
            parsed
              .filter(
                (row) =>
                  typeof row?.row_key === "string"
              )
              .map((row) => [row.row_key, row])
          );

          for (const row of baseRows) {
            const old =
              savedMap.get(row.row_key);
            if (!old) continue;

            row.actual_quantity = typeof old.actual_quantity === "string" ? old.actual_quantity : "0";
            row.counted =
              old.counted === true;
          }
        } catch {
          localStorage.removeItem(key);
        }
      }

      setSessionLocationId(effectiveLocationId);
      setSessionId(sid);
      setRows(baseRows);
      setReview(null);
      setPhase("COUNTING");
      localStorage.setItem(
        phaseKey,
        "COUNTING"
      );
    },
    [
      authenticatedFetch,
      companyScope,
      phaseKey,
      sessionLocationId,
      setPhase,
      setReview,
      setRows,
      setSessionId,
      setSessionLocationId,
    ]
  );

  useEffect(() => {
    if (
      phase === "COUNTING" &&
      draftKey &&
      rows.length > 0
    ) {
      const timeoutId =
        window.setTimeout(() => {
          localStorage.setItem(
            draftKey,
            JSON.stringify(rows)
          );
        }, 800);

      return () =>
        window.clearTimeout(timeoutId);
    }
  }, [draftKey, phase, rows]);

  const updateRow = useCallback((
    key: string,
    value: string
  ) => {
    setRows((prev) => prev.map((row) => {
      if (row.row_key !== key) return row;

      return { ...row, actual_quantity: value.replace(/[^0-9.]/g, ""), counted: true };
    }));
  }, [setRows]);

  const confirmZeroCount =
    useCallback((key: string) => {
      setRows((prev) =>
        prev.map((row) =>
          row.row_key === key
            ? {
                ...row,
                actual_quantity: "0",
                counted: true,
              }
            : row
        )
      );
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

  const handleSubmit =
    useCallback(async () => {
      if (!sessionId) {
        toast.error(
          "خطأ حرج: جلسة الجرد غير موجودة."
        );
        return false;
      }

      if (!sessionLocationId) {
        toast.error(
          "خطأ حرج: موقع جلسة الجرد غير معروف."
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
        product_variant_id:
          row.product_variant_id,
        batch_id: row.batch_id,
        stock_status: row.stock_status,
        actual_quantity: row.actual_quantity,
        uom_id: row.base_uom_id,
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
        await onSubmitted(
          sessionId,
          sessionLocationId
        );
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
      sessionLocationId,
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
