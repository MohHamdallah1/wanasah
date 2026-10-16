import { useCallback, useMemo, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { compareQuantity, validateVariantQuantity, type Quantity } from "../quantity";
import {
  adjustmentDelta,
  buildLedgerAdjustmentPayload,
  parseLedgerAdjustmentState,
  parseLedgerMutationResponse,
  type LedgerAdjustmentState,
  type LedgerEntry,
} from "./contracts";

export interface LedgerAdjustmentSubmitResult {
  message: string;
  recovered: boolean;
}

export interface LedgerAdjustmentController {
  entry: LedgerEntry | null;
  state: LedgerAdjustmentState | null;
  newTotal: string;
  setNewTotal: (value: string) => void;
  password: string;
  setPassword: (value: string) => void;
  delta: Quantity | null;
  loading: boolean;
  submitting: boolean;
  error: unknown | null;
  open: (entry: LedgerEntry) => void;
  retryState: () => void;
  submit: () => Promise<LedgerAdjustmentSubmitResult>;
  close: () => void;
}

export function useLedgerAdjustment(
  locationId: number,
): LedgerAdjustmentController {
  const authFetch = useAuthFetch();
  const [entry, setEntry] = useState<LedgerEntry | null>(null);
  const [state, setState] = useState<LedgerAdjustmentState | null>(null);
  const [newTotal, setNewTotal] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown | null>(null);
  const stateSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const loadState = useCallback(async (target: LedgerEntry) => {
    const sequence = ++stateSeq.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setState(null);

    try {
      const parsed = parseLedgerAdjustmentState(await authFetch(
        `/warehouse/ledger/${target.id}/adjustment-state`,
        { signal: controller.signal },
      ));
      if (sequence !== stateSeq.current) return;
      if (
        parsed.entry_id !== target.id
        || parsed.product_variant_id !== target.product_variant_id
        || parsed.warehouse_location_id !== locationId
        || parsed.base_uom_id !== target.base_uom_id
      ) {
        throw new Error("LEDGER_ADJUSTMENT_STATE_SCOPE_MISMATCH");
      }
      setState(parsed);
      setNewTotal(parsed.current_total_quantity);
    } catch (failure) {
      if (sequence !== stateSeq.current) return;
      if (failure instanceof Error && failure.name === "AbortError") return;
      setError(failure);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (sequence === stateSeq.current) setLoading(false);
    }
  }, [authFetch, locationId]);

  const open = useCallback((target: LedgerEntry) => {
    setEntry(target);
    setPassword("");
    setNewTotal("");
    void loadState(target);
  }, [loadState]);

  const retryState = useCallback(() => {
    if (entry) void loadState(entry);
  }, [entry, loadState]);

  const validatedTotal = useMemo<Quantity | null>(() => {
    if (!entry || !newTotal) return null;
    try {
      return validateVariantQuantity(
        newTotal,
        entry.quantity_scale,
        entry.quantity_step,
        "new_total_quantity",
        true,
      );
    } catch {
      return null;
    }
  }, [entry, newTotal]);

  const delta = useMemo<Quantity | null>(() => {
    if (!state || validatedTotal === null) return null;
    return adjustmentDelta(validatedTotal, state.current_total_quantity);
  }, [state, validatedTotal]);

  const submit = useCallback(async (): Promise<LedgerAdjustmentSubmitResult> => {
    if (!entry || !state) throw new Error("LEDGER_ADJUSTMENT_STATE_REQUIRED");
    const payload = buildLedgerAdjustmentPayload(newTotal, entry, password);
    setSubmitting(true);
    setError(null);
    try {
      const response = parseLedgerMutationResponse(await authFetch(
        `/warehouse/ledger/${entry.id}/adjust`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      ));
      return { message: response.message, recovered: false };
    } catch (failure) {
      // A response can be lost after the authoritative correction commits. Re-read
      // state before allowing a retry so the browser never invents another delta.
      try {
        const confirmed = parseLedgerAdjustmentState(await authFetch(
          `/warehouse/ledger/${entry.id}/adjustment-state`,
        ));
        if (
          confirmed.entry_id === entry.id
          && confirmed.warehouse_location_id === locationId
          && compareQuantity(confirmed.current_total_quantity, payload.new_total_quantity) === 0
        ) {
          setState(confirmed);
          return { message: "", recovered: true };
        }
      } catch {
        // Preserve the original failure; a failed recovery read is not proof that
        // the mutation did or did not commit.
      }
      setError(failure);
      throw failure;
    } finally {
      setSubmitting(false);
    }
  }, [authFetch, entry, locationId, newTotal, password, state]);

  const close = useCallback(() => {
    stateSeq.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setEntry(null);
    setState(null);
    setNewTotal("");
    setPassword("");
    setLoading(false);
    setSubmitting(false);
    setError(null);
  }, []);

  return {
    entry,
    state,
    newTotal,
    setNewTotal,
    password,
    setPassword,
    delta,
    loading,
    submitting,
    error,
    open,
    retryState,
    submit,
    close,
  };
}
