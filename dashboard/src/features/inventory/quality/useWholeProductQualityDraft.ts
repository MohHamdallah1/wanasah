import { useCallback } from "react";
import type { WholeProductQualityAction } from "./wholeProductQualityResolveContract";

type Draft = { reason: string; reasonTouched: boolean; supplierId: number | null };
export function useWholeProductQualityDraft(companyId: number | undefined, actorId: number | undefined, productId: number) {
  const prefix = companyId && actorId ? `wanasah:whole-quality-draft:${companyId}:${actorId}:${productId}` : null;
  const read = useCallback((action: WholeProductQualityAction): Draft | null => {
    if (!prefix) return null;
    try {
      const value = JSON.parse(localStorage.getItem(`${prefix}:${action}`) ?? "null");
      if (!value || typeof value.reason !== "string" || value.reason.length > 1000 || typeof value.reasonTouched !== "boolean"
        || (value.supplierId !== null && (!Number.isSafeInteger(value.supplierId) || value.supplierId <= 0))) return null;
      return value;
    } catch { return null; }
  }, [prefix]);
  const save = useCallback((action: WholeProductQualityAction, draft: Draft) => {
    if (prefix) localStorage.setItem(`${prefix}:${action}`, JSON.stringify(draft));
  }, [prefix]);
  const clear = useCallback((action: WholeProductQualityAction) => {
    if (prefix) localStorage.removeItem(`${prefix}:${action}`);
  }, [prefix]);
  return { read, save, clear };
}
