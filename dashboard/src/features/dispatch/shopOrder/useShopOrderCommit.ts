import { useCallback, useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { toast } from "sonner";
import type { Shop } from "@/types/dispatch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { shopOrderText } from "./messages";
import { commitShopOrder, ShopOrderUncertainError, ShopOrderVerificationError } from "./persist";
import {
  canReconcileUncertainShopOrder, hasShopOrderChanges, sameSelectedZoneState,
  type ShopOrderChange, type UncertainShopOrderCommand,
} from "./scope";
import {
  clearShopOrderRecovery, loadShopOrderRecovery, restoreShopOrderDraft, storeShopOrderRecovery,
} from "./useShopOrderDraft";

interface Params {
  draft: Shop[];
  baseline: MutableRefObject<Shop[]>;
  zoneId: string;
  language: string;
  saving: boolean;
  setSaving: Dispatch<SetStateAction<boolean>>;
  setShops: Dispatch<SetStateAction<Shop[]>>;
  setDirty: Dispatch<SetStateAction<boolean>>;
  setEditMode: Dispatch<SetStateAction<boolean>>;
  clearSelection: () => void;
  send: (changes: readonly ShopOrderChange[]) => Promise<unknown>;
  read: () => Promise<Shop[]>;
  /** Authorized discovery identity, "company_id:principal_id", not UI zone. */
  recoveryScope?: string | null;
  setZoneId?: Dispatch<SetStateAction<string>>;
}

class ShopOrderReconciliationConflictError extends Error {
  constructor() { super("SHOP_ORDER_CONCURRENT_CHANGE"); this.name = "ShopOrderReconciliationConflictError"; }
}
class ShopOrderUnresolvedTransportError extends Error {
  constructor() { super("SHOP_ORDER_PUT_STILL_MAY_BE_RUNNING"); this.name = "ShopOrderUnresolvedTransportError"; }
}

/** One ordering workflow UI coordinator; data diff and transport remain separate. */
export function useShopOrderCommit({
  draft, baseline, zoneId, language, saving, setSaving, setShops,
  setDirty, setEditMode, clearSelection, send, read, recoveryScope, setZoneId,
}: Params) {
  const inFlight = useRef(false);
  const restoredScope = useRef<string | null>(null);
  const [pendingCommand, setPendingCommand] = useState<UncertainShopOrderCommand | null>(null);
  const needsReconciliation = pendingCommand !== null;

  const reset = useCallback((latest: Shop[]) => {
    setShops(latest);
    baseline.current = latest;
    setPendingCommand(null);
    if (recoveryScope) clearShopOrderRecovery(recoveryScope);
    setDirty(false);
    setEditMode(false);
    clearSelection();
  }, [baseline, setShops, setDirty, setEditMode, clearSelection, recoveryScope]);

  useEffect(() => {
    // A prior GET 401 may have caused forceLogout/unmount. Restore intent
    // only after a NEW authenticated principal-specific discovery and GET.
    if (!recoveryScope || !setZoneId || !draft.length ||
      restoredScope.current === recoveryScope) return;
    restoredScope.current = recoveryScope;
    const pending = loadShopOrderRecovery(recoveryScope);
    if (!pending) return;
    let active = true;
    let settled = false;
    setSaving(true);
    void read().then(fresh => {
      if (!active) return;
      const restored = Array.isArray(fresh) ? restoreShopOrderDraft(fresh, pending) : null;
      if (!restored) {
        toast.error(shopOrderText(language, "reconcileConflict"));
        return; // Keep durable draft; never apply an unauthorized/stale snapshot.
      }
      baseline.current = fresh;
      setZoneId(pending.zoneId);
      setShops(restored);
      setPendingCommand(pending);
      setDirty(true);
      setEditMode(true);
      toast.info(shopOrderText(language, "recoveredDraft"));
    }).catch(() => {
      if (active) toast.error(shopOrderText(language, "recoveryFailed"));
    }).finally(() => {
      settled = true;
      if (active) setSaving(false);
    });
    return () => {
      active = false;
      // Language changes or another initial fetch can invalidate recovery.
      // Do not leave Saving stuck or silently abandon a stored draft.
      if (!settled) {
        restoredScope.current = null;
        setSaving(false);
      }
    };
  }, [recoveryScope, setZoneId, draft.length, baseline, read, language,
    setSaving, setShops, setDirty, setEditMode]);

  const save = useCallback(async (): Promise<boolean> => {
    if (saving || inFlight.current) return false;
    if (recoveryScope === null) {
      toast.error(shopOrderText(language, "recoveryIdentityUnavailable"));
      return false; // Never mutate while the authoritative principal is unknown.
    }
    inFlight.current = true;
    setSaving(true);
    try {
      let reconciled: Shop[] | null = null;
      if (pendingCommand) {
        // A transport timeout can hide an IN-FLIGHT server transaction. Even
        // an unchanged GET cannot prove completion without backend operation
        // identity/fence. No retry, cancellation, or auto-resend is safe.
        if (pendingCommand.outcome === "transport_unknown") {
          await read(); // check authorization only; this is NOT completion proof
          throw new ShopOrderUnresolvedTransportError();
        }
        // Confirmed PUT completed before GET failed: now safe to reconcile
        // all selected-zone rows, then explicitly apply a revised local draft.
        reconciled = await read();
        if (!Array.isArray(reconciled) ||
          !canReconcileUncertainShopOrder(pendingCommand, reconciled, zoneId)) {
          throw new ShopOrderReconciliationConflictError();
        }
        baseline.current = reconciled;
        setPendingCommand(null);
        if (recoveryScope) clearShopOrderRecovery(recoveryScope);
        setDirty(hasShopOrderChanges(reconciled, draft, zoneId));
      }

      const outcome = await commitShopOrder({
        original: baseline.current, draft, selectedZoneId: zoneId, send, read,
        beforeSend: command => {
          if (recoveryScope) storeShopOrderRecovery(recoveryScope, command);
        },
        putConfirmed: command => {
          if (recoveryScope) storeShopOrderRecovery(recoveryScope, command);
        },
      });
      if (outcome.kind === "confirmed") {
        reset(outcome.shops);
        toast.success(shopOrderText(language, "saved"));
      } else {
        if (reconciled && !sameSelectedZoneState(draft, reconciled, zoneId)) {
          throw new ShopOrderReconciliationConflictError();
        }
        if (reconciled) reset(reconciled);
        else {
          setDirty(false);
          setEditMode(false);
          clearSelection();
        }
        toast.info(shopOrderText(language, reconciled ? "verifiedNoChange" : "nothingChanged"));
      }
      return true;
    } catch (error: unknown) {
      if (error instanceof ShopOrderUncertainError) {
        // Both kinds retain their attempted draft. Only a completed PUT may
        // be rebased; a still-running PUT requires new server-side evidence.
        setPendingCommand(error.command);
      } else if (error instanceof ShopOrderReconciliationConflictError ||
        error instanceof ShopOrderUnresolvedTransportError) {
        // Keep the exact pending command/draft, even after a fresh GET.
      } else if (!pendingCommand && recoveryScope) {
        // Definitely denied PUT, or storage failure BEFORE any mutation.
        clearShopOrderRecovery(recoveryScope);
      }
      toast.error(error instanceof ShopOrderUnresolvedTransportError
        ? shopOrderText(language, "unresolvedTransport")
        : error instanceof ShopOrderReconciliationConflictError
          ? shopOrderText(language, "reconcileConflict")
          : error instanceof ShopOrderVerificationError
            ? shopOrderText(language, "readbackFailed")
            : apiErrorMessage(error, shopOrderText(language, "saveFailed")));
      return false;
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [saving, setSaving, baseline, draft, zoneId, send, read, pendingCommand,
    reset, language, setDirty, setEditMode, clearSelection, recoveryScope]);

  const cancel = useCallback(async (): Promise<boolean> => {
    if (saving || inFlight.current) return false;
    if (pendingCommand?.outcome === "transport_unknown") {
      toast.error(shopOrderText(language, "unresolvedTransport"));
      return false; // A later server commit could still overwrite this GET.
    }
    inFlight.current = true;
    setSaving(true);
    try {
      reset(await read()); // authorized GET; never resurrect stale local snapshot
      return true;
    } catch {
      toast.error(shopOrderText(language, "cancelFailed"));
      return false; // retain draft and its pending uncertain command
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [saving, setSaving, read, reset, language, pendingCommand]);

  return { save, cancel, needsReconciliation };
}
