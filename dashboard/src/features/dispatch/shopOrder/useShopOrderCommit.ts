import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { toast } from "sonner";
import type { Shop } from "@/types/dispatch";
import { getErrorMessage as formatError } from "./errors";
import { shopOrderText } from "./messages";
import { commitShopOrder, ShopOrderVerificationError } from "./persist";
import type { ShopOrderChange } from "./scope";

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
  const reset = useCallback((latest: Shop[]) => {
    setShops(latest);
    baseline.current = latest;
    setDirty(false);
    setEditMode(false);
    clearSelection();
  }, [baseline, setShops, setDirty, setEditMode, clearSelection]);

  const save = useCallback(async (): Promise<boolean> => {
    if (saving) return false;
    setSaving(true);
    try {
      const outcome = await commitShopOrder({
        original: baseline.current, draft, selectedZoneId: zoneId, send, read,
      });
      if (outcome.kind === "confirmed") {
        reset(outcome.shops);
        toast.success(shopOrderText(language, "saved"));
      } else {
        // No HTTP call, no success toast for a no-op.
        setDirty(false);
        setEditMode(false);
        clearSelection();
        toast.info(shopOrderText(language, "nothingChanged"));
      }
      return true;
    } catch (error: unknown) {
      toast.error(error instanceof ShopOrderVerificationError
        ? shopOrderText(language, "readbackFailed")
        : shopOrderText(language, "saveFailed") + " " + formatError(error));
      return false; // retain draft as dirty, including ambiguous 200 + GET failure
    } finally {
      setSaving(false);
    }
  }, [saving, setSaving, baseline, draft, zoneId, send, read,
    reset, language, setDirty, setEditMode, clearSelection]);

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

  return { save, cancel };
}
