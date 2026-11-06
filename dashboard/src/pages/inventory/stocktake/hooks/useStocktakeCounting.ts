import { parseInventoryCapabilities, hasInventoryPermission } from "@/hooks/useInventoryAccess";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { executeStocktakeDurableCommand, type StocktakeDurableIdentity } from "../durableCommand";
import { useStocktakeCopy } from "../copy";
import type { Dispatch, SetStateAction } from "react";
import type { StocktakeRow } from "../../inventoryUtils";
import type { StocktakeAuthFetch, StocktakePhase, StocktakeReview } from "../types";
import { getErrorMessage, parseCountSheet, rowKey } from "../parsers";
import { isDiscoveredRow, parseDiscoveredBatches, restoreDiscoveredRows, type DiscoveredRow } from "../discoveredContract";
import { calculateCount, countOuterFactor, restoreCountParts, splitCountForDisplay, validBaseCount } from "../countEntry";

interface UseStocktakeCountingArgs {
  durableIdentity: StocktakeDurableIdentity | null;
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
  onSubmitted: (sessionId: string, sessionLocationId: number) => Promise<void>;
}

export function useStocktakeCounting({
  durableIdentity,
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
  const { copy } = useStocktakeCopy();
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pendingDraftRef = useRef<{ key: string; snapshot: string } | null>(null);

  const loadCountSheet = useCallback(async (
    sid: string,
    targetLocationId?: number,
    isCurrent: () => boolean = () => true,
  ) => {
    const effectiveLocationId = targetLocationId ?? sessionLocationId;
    if (effectiveLocationId === null || !Number.isInteger(effectiveLocationId) || effectiveLocationId <= 0) {
      throw new Error(copy.lifecycle.unknownLocation);
    }

    const capabilities = parseInventoryCapabilities(await authenticatedFetch(
      `/inventory/access/me?location_id=${effectiveLocationId}`
    ));
    if (!isCurrent()) return;
    if (capabilities.location_id !== effectiveLocationId) throw new Error(copy.count.scopeMismatch);
    if (!hasInventoryPermission(capabilities, "stocktake.count")) {
      setSessionLocationId(effectiveLocationId);
      setSessionId(sid);
      setReview(null);
      setRows([]);
      setPhase("COUNTING");
      return;
    }

    const raw = await authenticatedFetch(`/warehouse/unified/stocktake/${sid}/count-sheet`);
    if (!isCurrent()) return;
    const data = parseCountSheet(raw);
    const baseRows: StocktakeRow[] = data.map((item) => ({
      row_key: rowKey(item.product_variant_id, item.batch_id, item.stock_status),
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
      ...(item.count_outer_uom_id ? {
        count_outer_uom_id: item.count_outer_uom_id,
        count_outer_uom_name: item.count_outer_uom_name,
        count_outer_uom_code: item.count_outer_uom_code,
        count_outer_factor_numerator: item.count_outer_factor_numerator,
        count_outer_factor_denominator: item.count_outer_factor_denominator,
      } : {}),
      actual_quantity: "",
      counted: false,
    }));

    const key = `wanasah_audit_draft:${companyScope}:${effectiveLocationId}:${sid}`;
    const saved = pendingDraftRef.current?.key === key
      ? pendingDraftRef.current.snapshot
      : localStorage.getItem(key);
    if (saved) {
      let parsed: StocktakeRow[] = [];
      try {
        const decoded: unknown = JSON.parse(saved);
        if (!Array.isArray(decoded)) throw new Error("Invalid stocktake draft");
        parsed = decoded as StocktakeRow[];
      } catch {
        localStorage.removeItem(key);
      }
      const savedMap = new Map(
        parsed.filter((row) => typeof row?.row_key === "string").map((row) => [row.row_key, row]),
      );
      for (const row of baseRows) {
        const old = savedMap.get(row.row_key);
        if (!old) continue;
        const actual = typeof old.actual_quantity === "string" ? old.actual_quantity : "";
        const canonical = validBaseCount(row, actual);
        row.counted = old.counted === true && canonical !== null;
        // Legacy "0"/counted:false was only a placeholder, never a physical count.
        row.actual_quantity = !row.counted && actual === "0" ? "" : (row.counted ? canonical! : actual);
        const parts = restoreCountParts(row, old);
        row.count_outer_quantity = !row.counted && actual === "0" ? "" : parts.outer;
        row.count_base_quantity = !row.counted && actual === "0" ? "" : parts.base;
      }
      const discovered = parsed.filter(isDiscoveredRow);
      if (discovered.length > 0) {
        const ids = [...new Set(discovered.map((row) => row.batch_id))];
        if (ids.length > 100 || ids.some((id) => id === null || !Number.isSafeInteger(id) || id <= 0)) {
          throw new Error(copy.count.scopeMismatch);
        }
        const params = new URLSearchParams({ batch_ids: ids.join(",") });
        const fresh = await authenticatedFetch(
          `/warehouse/unified/stocktake/${sid}/discovery-options?${params.toString()}`,
        );
        if (!isCurrent()) return;
        const authoritative = parseDiscoveredBatches(fresh).items;
        if (authoritative.length !== ids.length) throw new Error(copy.count.scopeMismatch);
        baseRows.push(...restoreDiscoveredRows(parsed, authoritative, baseRows));
      }
    }
    if (!isCurrent()) return;
    if (pendingDraftRef.current?.key === key) pendingDraftRef.current = null;

    setSessionLocationId(effectiveLocationId);
    setSessionId(sid);
    setRows(baseRows);
    setReview(null);
    setPhase("COUNTING");
    localStorage.setItem(phaseKey, "COUNTING");
  }, [authenticatedFetch, companyScope, copy.count.scopeMismatch, copy.lifecycle.unknownLocation, phaseKey, sessionLocationId, setPhase, setReview, setRows, setSessionId, setSessionLocationId]);

  useEffect(() => {
    if (phase !== "COUNTING" || !draftKey || rows.length === 0) return;
    const pending = { key: draftKey, snapshot: JSON.stringify(rows) };
    pendingDraftRef.current = pending;
    const timeoutId = window.setTimeout(() => {
      // Successful submission invalidates this pending write. Do not
      // resurrect an obsolete count draft after the server has accepted it.
      if (pendingDraftRef.current !== pending) return;
      localStorage.setItem(pending.key, pending.snapshot);
      pendingDraftRef.current = null;
    }, 800);
    return () => window.clearTimeout(timeoutId);
  }, [draftKey, phase, rows]);

  // Losing the component or switching sessions before the debounce fires
  // must not discard the last physical count. Only the current scoped draft
  // is flushed, never a different company/user/location's data.
  useEffect(() => {
    const flush = () => {
      const pending = pendingDraftRef.current;
      if (pending && pending.key === draftKey) {
        localStorage.setItem(pending.key, pending.snapshot);
        pendingDraftRef.current = null;
      }
    };
    window.addEventListener("pagehide", flush);
    return () => {
      window.removeEventListener("pagehide", flush);
      flush();
    };
  }, [draftKey]);

  const updateRow = useCallback((key: string, value: string) => {
    setRows((prev) => prev.map((row) => {
      if (row.row_key !== key) return row;
      const canonical = validBaseCount(row, value);
      // An implicit typed zero is not confirmation of zero physical stock.
      const counted = canonical !== null && canonical !== "0";
      return {
        ...row,
        actual_quantity: counted ? canonical : value,
        count_outer_quantity: "",
        count_base_quantity: value,
        counted,
      };
    }));
  }, [setRows]);

  const updateCountPart = useCallback((key: string, part: "outer" | "base", value: string) => {
    setRows((prev) => prev.map((row) => {
      if (row.row_key !== key || countOuterFactor(row) === null) return row;
      const existing = row.count_outer_quantity !== undefined && row.count_base_quantity !== undefined
        ? { outer: row.count_outer_quantity, base: row.count_base_quantity }
        : splitCountForDisplay(row, row.actual_quantity);
      const outer = part === "outer" ? value : existing.outer;
      const base = part === "base" ? value : existing.base;
      const canonical = calculateCount(row, outer, base);
      return {
        ...row,
        count_outer_quantity: outer,
        count_base_quantity: base,
        actual_quantity: canonical ?? "",
        counted: canonical !== null,
      };
    }));
  }, [setRows]);

  const confirmZeroCount = useCallback((key: string) => {
    setRows((prev) => prev.map((row) => row.row_key === key
      ? {
          ...row, actual_quantity: "0", counted: true,
          count_outer_quantity: "", count_base_quantity: "0",
        }
      : row));
  }, [setRows]);

  const undoRowCount = useCallback((key: string) => {
    setRows((prev) => prev.map((row) => row.row_key === key
      ? { ...row, actual_quantity: "", counted: false, count_outer_quantity: "", count_base_quantity: "" }
      : row));
  }, [setRows]);

  const rowIsCounted = (row: StocktakeRow): boolean => {
    if (!row.counted || validBaseCount(row, row.actual_quantity) === null) return false;
    if (row.actual_quantity === "0") return true; // Only Confirm Zero can mark this true.
    if (countOuterFactor(row) !== null && row.count_outer_quantity !== undefined &&
        row.count_base_quantity !== undefined) {
      return calculateCount(row, row.count_outer_quantity, row.count_base_quantity) === row.actual_quantity;
    }
    return true;
  };

  const addDiscoveredRow = useCallback((row: DiscoveredRow): boolean => {
    if (rows.length >= 10_000 || rows.some((existing) => existing.row_key === row.row_key) ||
        rows.filter(isDiscoveredRow).length >= 100) return false;
    setRows((prev) => prev.some((existing) => existing.row_key === row.row_key)
      ? prev : [...prev, row]);
    return true;
  }, [rows, setRows]);

  const removeDiscoveredRow = useCallback((key: string) => {
    setRows((prev) => prev.filter((row) => row.row_key !== key || !isDiscoveredRow(row)));
  }, [setRows]);

  const countProgress = useMemo(() => {
    const counted = rows.filter(rowIsCounted).length;
    return { total: rows.length, counted, remaining: rows.length - counted };
  }, [rows]);

  const handleSubmit = useCallback(async () => {
    if (!sessionId) {
      toast.error(copy.count.missingSession);
      return false;
    }
    if (!sessionLocationId) {
      toast.error(copy.count.missingLocation);
      return false;
    }
    const uncounted = rows.filter((row) => !rowIsCounted(row));
    // The empty-sheet case must never silently create a count attempt.
    if (rows.length === 0 || uncounted.length > 0) {
      toast.error(copy.count.remaining(uncounted.length || 1));
      return false;
    }
    if (!durableIdentity) {
      toast.error(copy.generic.identityNotReady);
      return false;
    }

    const items = rows.map((row) => ({
      product_variant_id: row.product_variant_id,
      batch_id: row.batch_id,
      stock_status: row.stock_status,
      // One normalized exact base quantity; never post outer/display components.
      actual_quantity: validBaseCount(row, row.actual_quantity)!,
      uom_id: row.base_uom_id,
    }));

    setSubmitting(true);
    try {
      await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "count",
        target: `${sessionLocationId}:${sessionId}`,
        payload: { items, notes },
        send: (body) => authenticatedFetch(
          `/warehouse/unified/stocktake/${sessionId}/count`,
          { method: "POST", body: JSON.stringify(body) },
        ),
      });

      if (draftKey) {
        if (pendingDraftRef.current?.key === draftKey) pendingDraftRef.current = null;
        localStorage.removeItem(draftKey);
      }
      setNotes("");
      await onSubmitted(sessionId, sessionLocationId);
      toast.success(copy.count.submitted);
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.countFailed));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [authenticatedFetch, copy.count, copy.generic.countFailed, copy.generic.identityNotReady, durableIdentity, draftKey, notes, onSubmitted, rows, sessionId, sessionLocationId]);

  return {
    notes,
    setNotes,
    submitting,
    loadCountSheet,
    updateRow,
    confirmZeroCount,
    undoRowCount,
    updateCountPart,
    addDiscoveredRow,
    removeDiscoveredRow,
    countProgress,
    handleSubmit,
  };
}
