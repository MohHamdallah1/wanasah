import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { toast } from "sonner";
import type { Shop } from "@/types/dispatch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { shopOrderText } from "./messages";
import { commitShopOrder, ShopOrderVerificationError } from "./persist";
import type { ShopOrderChange } from "./scope";
import { sameSelectedZoneMembership, sameSelectedZoneState } from "./scope";

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

/** One ordering workflow UI coordinator; data diff and transport remain separate. */
export function useShopOrderCommit({
  draft, baseline, zoneId, language, saving, setSaving, setShops,
  setDirty, setEditMode, clearSelection, send, read,
}: Params) {
  const inFlight = useRef(false);
  const [needsReconciliation, setNeedsReconciliation] = useState(false);
  const reset = useCallback((latest: Shop[]) => {
    setShops(latest);
    baseline.current = latest;
    setNeedsReconciliation(false);
    setDirty(false);
    setEditMode(false);
    clearSelection();
  }, [baseline, setShops, setDirty, setEditMode, clearSelection]);

  const save = useCallback(async (): Promise<boolean> => {
    if (saving || inFlight.current) return false;
    inFlight.current = true;
    setSaving(true);
    try {
      // An earlier PUT may have committed despite a lost/failed readback.
      // First reconcile against a fresh authorized snapshot, THEN diff again.
      let reconciled: Shop[] | null = null;
      if (needsReconciliation) {
        reconciled = await read();
        if (!sameSelectedZoneMembership(draft, reconciled, zoneId)) {
          throw new ShopOrderVerificationError();
        }
        baseline.current = reconciled;
      }
      const outcome = await commitShopOrder({
        original: baseline.current, draft, selectedZoneId: zoneId, send, read,
      });
      if (outcome.kind === "confirmed") {
        reset(outcome.shops);
        toast.success(shopOrderText(language, "saved"));
      } else {
        // No HTTP call, no success toast for a no-op.
        if (reconciled && !sameSelectedZoneState(draft, reconciled, zoneId)) {
          throw new ShopOrderVerificationError();
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
      // Even network/timeout after PUT can mean committed; the next Save
      // must read current server order before deriving any new delta.
      setNeedsReconciliation(true);
      toast.error(error instanceof ShopOrderVerificationError
        ? shopOrderText(language, "readbackFailed")
        : apiErrorMessage(error, shopOrderText(language, "saveFailed")));
      return false; // retain draft as dirty, including ambiguous 200 + GET failure
    } finally {
      inFlight.current = false;
      setSaving(false);
    }
  }, [saving, setSaving, baseline, draft, zoneId, send, read,
    needsReconciliation, reset, language, setDirty, setEditMode, clearSelection]);

  const cancel = useCallback(async (): Promise<boolean> => {
    if (saving) return false;
    setSaving(true);
    try {
      reset(await read()); // authorized GET, never restore stale local snapshot
      return true;
    } catch {
      toast.error(shopOrderText(language, "cancelFailed"));
      return false;
    } finally {
      setSaving(false);
    }
  }, [saving, setSaving, read, reset, language]);

  return { save, cancel, needsReconciliation };
}
