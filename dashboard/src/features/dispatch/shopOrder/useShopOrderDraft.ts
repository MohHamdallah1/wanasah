import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { Shop } from "@/types/dispatch";
import {
  canReorderShop, hasShopOrderChanges, moveShopBeforeInSelectedZone, moveShopInSelectedZone,
  sameSelectedZoneMembership, type ShopOrderRow, type UncertainShopOrderCommand,
} from "./scope";

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
    const row = shops.find(s => s.id === id);
    if (saving || !row || !canReorderShop(row, zoneId)) return;
    apply(moveShopInSelectedZone(shops, zoneId, id, sequence - 1));
  }, [saving, shops, zoneId, apply]);

  const drop = useCallback((sourceId: string, targetId: string) => {
    if (saving) return;
    apply(moveShopBeforeInSelectedZone(shops, zoneId, sourceId, targetId));
  }, [saving, shops, zoneId, apply]);

  return { changeSequence, drop };
}

/**
 * Session-tab recovery for a write that can outlive dashboard logout.
 * Store ONLY selected-zone ids/order/archive, never names, credentials or PII.
 * Identity comes from authorized company + principal discovery, not zone UI.
 * This records a draft, not a queued browser command: no automatic replay.
 */
const recoveryKey = (scope: string): string => {
  if (!/^\d+:\d+$/.test(scope)) throw new Error("SHOP_ORDER_RECOVERY_SCOPE_REQUIRED");
  return `wanasah:dispatch:shop-order-recovery:v1:${scope}`;
};

export function storeShopOrderRecovery(scope: string, command: UncertainShopOrderCommand): void {
  sessionStorage.setItem(recoveryKey(scope), JSON.stringify({ version: 1, scope, command }));
}

export function clearShopOrderRecovery(scope: string): void {
  sessionStorage.removeItem(recoveryKey(scope));
}

const isOrderRow = (value: unknown): value is ShopOrderRow => {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<ShopOrderRow>;
  return typeof row.id === "string" && !!row.id &&
    typeof row.zoneId === "string" && !!row.zoneId &&
    typeof row.sequence === "number" && Number.isFinite(row.sequence) &&
    typeof row.archived === "boolean";
};

export function loadShopOrderRecovery(scope: string): UncertainShopOrderCommand | null {
  try {
    const raw = sessionStorage.getItem(recoveryKey(scope));
    if (!raw) return null;
    const envelope = JSON.parse(raw) as {
      version?: unknown; scope?: unknown; command?: Partial<UncertainShopOrderCommand>;
    };
    const command = envelope.command;
    if (envelope.version !== 1 || envelope.scope !== scope ||
      !command || typeof command.zoneId !== "string" || !command.zoneId ||
      !["put_confirmed", "transport_unknown"].includes(String(command.outcome)) ||
      !Array.isArray(command.before) || !Array.isArray(command.intended) ||
      !command.before.every(isOrderRow) || !command.intended.every(isOrderRow) ||
      command.before.some(row => row.zoneId !== command.zoneId) ||
      command.intended.some(row => row.zoneId !== command.zoneId) ||
      !sameSelectedZoneMembership(command.before, command.intended, command.zoneId)) {
      return null;
    }
    return command as UncertainShopOrderCommand;
  } catch {
    return null;
  }
}

/** Restore visual intent onto an authorized GET, never resurrect stale PII. */
export function restoreShopOrderDraft(
  fresh: readonly Shop[], command: UncertainShopOrderCommand,
): Shop[] | null {
  if (!sameSelectedZoneMembership(command.before, fresh, command.zoneId) ||
    !sameSelectedZoneMembership(command.intended, fresh, command.zoneId)) return null;
  const intended = new Map(command.intended.map(row => [row.id, row]));
  return fresh.map(row => {
    if (row.zoneId !== command.zoneId) return row;
    const saved = intended.get(row.id);
    return saved ? { ...row, sequence: saved.sequence, archived: saved.archived } : row;
  });
}
