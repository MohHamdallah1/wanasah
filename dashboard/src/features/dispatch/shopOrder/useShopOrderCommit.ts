import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { toast } from "sonner";
import type { Shop } from "@/types/dispatch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { shopOrderText } from "./messages";
import { commitShopOrder, ShopOrderUncertainError, ShopOrderVerificationError } from "./persist";
import {
  canReconcileUncertainShopOrder, hasShopOrderChanges, sameSelectedZoneState,
  type ShopOrderChange, type UncertainShopOrderCommand,
} from "./scope";

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
}

class ShopOrderReconciliationConflictError extends Error {
  constructor() { super("SHOP_ORDER_CONCURRENT_CHANGE"); this.name = "ShopOrderReconciliationConflictError"; }
}

/** One ordering workflow UI coordinator; data diff and transport remain separate. */
export function useShopOrderCommit({
  draft, baseline, zoneId, language, saving, setSaving, setShops,
  setDirty, setEditMode, clearSelection, send, read,
}: Params) {
  const inFlight = useRef(false);
  const [pendingCommand, setPendingCommand] = useState<UncertainShopOrderCommand | null>(null);
  const needsReconciliation = pendingCommand !== null;

  const reset = useCallback((latest: Shop[]) => {
    setShops(latest);
    baseline.current = latest;
    setPendingCommand(null);
    setDirty(false);
    setEditMode(false);
    clearSelection();
  }, [baseline, setShops, setDirty, setEditMode, clearSelection]);

  const save = useCallback(async (): Promise<boolean> => {
    if (saving || inFlight.current) return false;
    inFlight.current = true;
    setSaving(true);
    try {
      let reconciled: Shop[] | null = null;
      if (pendingCommand) {
        // An earlier command might have committed. Never diff against its
        // pre-write baseline, and never overwrite another operator's order.
        reconciled = await read();
        if (!Array.isArray(reconciled) ||
          !canReconcileUncertainShopOrder(pendingCommand, reconciled, zoneId)) {
          throw new ShopOrderReconciliationConflictError();
        }
        // Only the two safe outcomes (all applied / none applied) permit
        // rebasing the still-intended local draft and one explicit retry.
        baseline.current = reconciled;
        setPendingCommand(null);
        setDirty(hasShopOrderChanges(reconciled, draft, zoneId));
      }

      const outcome = await commitShopOrder({
        original: baseline.current, draft, selectedZoneId: zoneId, send, read,
      });
      if (outcome.kind === "confirmed") {
        reset(outcome.shops);
        toast.success(shopOrderText(language, "saved"));
      } else {
        // A no-op after reconciliation is verified, not evidence of a new PUT.
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
        // Covers PUT timeout and PUT 200 + failed/unauthorized/mismatched GET.
        // Keep the exact attempted snapshot until an authorized reconciliation.
        setPendingCommand(error.command);
      }
      // Definitive PUT 403/409 must not be mislabeled as committed or unknown.
      // A failed recovery GET leaves pendingCommand and the draft untouched.
      toast.error(error instanceof ShopOrderReconciliationConflictError
        ? shopOrderText(language, "reconcileConflict")
        : error instanceof ShopOrderVerificationError
          ? shopOrderText(language, "readbackFailed")
          : apiErrorMessage(error, shopOrderText(language, "saveFailed")));
      return false;
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [saving, setSaving, baseline, draft, zoneId, send, read,
    pendingCommand, reset, language, setDirty, setEditMode, clearSelection]);

  const cancel = useCallback(async (): Promise<boolean> => {
    if (saving || inFlight.current) return false;
    inFlight.current = true;
    setSaving(true);
    try {
      reset(await read()); // authorized GET; never resurrect stale local snapshot
      return true;
    } catch {
      toast.error(shopOrderText(language, "cancelFailed"));
      return false; // retain the draft AND its pending uncertain command
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [saving, setSaving, read, reset, language]);

  return { save, cancel, needsReconciliation };
}
