import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { Shop } from "@/types/dispatch";
import { canReorderShop, hasShopOrderChanges, moveShopBeforeInSelectedZone, moveShopInSelectedZone } from "./scope";

interface Params {
  shops: Shop[];
  zoneId: string;
  baseline: MutableRefObject<Shop[]>;
  setShops: Dispatch<SetStateAction<Shop[]>>;
  setDirty: Dispatch<SetStateAction<boolean>>;
  saving: boolean;
}

/** Only the local selected-zone ordering draft; no HTTP or server authority. */
export function useShopOrderDraft({ shops, zoneId, baseline, setShops, setDirty, saving }: Params) {
  const apply = useCallback((next: Shop[]) => {
    if (next === shops) return;
    setShops(next);
    setDirty(hasShopOrderChanges(baseline.current, next, zoneId));
  }, [shops, baseline, zoneId, setShops, setDirty]);

  const changeSequence = useCallback((id: string, sequence: number) => {
    if (saving || !canReorderShop(shops.find(s => s.id === id) || ({} as Shop), zoneId)) return;
    apply(moveShopInSelectedZone(shops, zoneId, id, sequence - 1));
  }, [saving, shops, zoneId, apply]);

  const drop = useCallback((sourceId: string, targetId: string) => {
    if (saving) return;
    apply(moveShopBeforeInSelectedZone(shops, zoneId, sourceId, targetId));
  }, [saving, shops, zoneId, apply]);

  return { changeSequence, drop };
}
