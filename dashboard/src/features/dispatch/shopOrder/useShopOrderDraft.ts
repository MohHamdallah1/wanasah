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
  /** Persist changed visual intent when an earlier PUT has uncertain readback. */
  recoveryScope?: string | null;
  uncertain?: boolean;
}

/** Only the local selected-zone ordering draft; no HTTP or server authority. */
export function useShopOrderDraft({
  shops, zoneId, baseline, setShops, setDirty, saving, recoveryScope, uncertain,
}: Params) {
  const apply = useCallback((next: Shop[]) => {
    if (next === shops) return;
    if (uncertain && recoveryScope) {
      // An auth expiry may unmount on any subsequent GET. Persist immediately
      // when the operator changes intent, not only after they press Save.
      stageShopOrderRecoveryDraft(recoveryScope, next);
    }
    setShops(next);
    setDirty(hasShopOrderChanges(baseline.current, next, zoneId));
  }, [shops, baseline, zoneId, setShops, setDirty, uncertain, recoveryScope]);

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
 * Store ONLY selected-zone IDs/order/archive, never names, credentials or PII.
 * The mutable latestDraft is distinct from immutable attempted before/intended.
 * This records visual intent, NEVER queues a browser-side write for replay.
 */
const recoveryKey = (scope: string): string => {
  if (!/^\d+:\d+$/.test(scope)) throw new Error("SHOP_ORDER_RECOVERY_SCOPE_REQUIRED");
  return `wanasah:dispatch:shop-order-recovery:v1:${scope}`;
};

export interface ShopOrderRecoveryRecord {
  command: UncertainShopOrderCommand;
  latestDraft: ShopOrderRow[];
}

const selectedZoneRows = (rows: readonly ShopOrderRow[], zoneId: string): ShopOrderRow[] =>
  rows.filter(row => row.zoneId === zoneId).map(({ id, zoneId, sequence, archived }) =>
    ({ id, zoneId, sequence, archived }));

export function storeShopOrderRecovery(scope: string, command: UncertainShopOrderCommand): void {
  sessionStorage.setItem(recoveryKey(scope), JSON.stringify({
    version: 1, scope, command,
    latestDraft: selectedZoneRows(command.intended, command.zoneId),
  }));
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

export function loadShopOrderRecoveryRecord(scope: string): ShopOrderRecoveryRecord | null {
  try {
    const raw = sessionStorage.getItem(recoveryKey(scope));
    if (!raw) return null;
    const envelope = JSON.parse(raw) as {
      version?: unknown; scope?: unknown; command?: Partial<UncertainShopOrderCommand>;
      latestDraft?: unknown;
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
    const latest = envelope.latestDraft === undefined ? command.intended : envelope.latestDraft;
    if (!Array.isArray(latest) || !latest.every(isOrderRow) ||
      latest.some(row => row.zoneId !== command.zoneId) ||
      !sameSelectedZoneMembership(command.before, latest, command.zoneId)) return null;
    return { command: command as UncertainShopOrderCommand, latestDraft: selectedZoneRows(latest, command.zoneId) };
  } catch {
    return null;
  }
}

export function loadShopOrderRecovery(scope: string): UncertainShopOrderCommand | null {
  return loadShopOrderRecoveryRecord(scope)?.command ?? null;
}

/** Write ONLY revised visual intent; leave the submitted command untouched. */
export function stageShopOrderRecoveryDraft(scope: string, draft: readonly ShopOrderRow[]): void {
  const record = loadShopOrderRecoveryRecord(scope);
  if (!record) throw new Error("SHOP_ORDER_RECOVERY_MISSING");
  const latestDraft = selectedZoneRows(draft, record.command.zoneId);
  if (!sameSelectedZoneMembership(record.command.before, latestDraft, record.command.zoneId)) {
    throw new Error("SHOP_ORDER_RECOVERY_MEMBERSHIP_CONFLICT");
  }
  sessionStorage.setItem(recoveryKey(scope), JSON.stringify({
    version: 1, scope, command: record.command, latestDraft,
  }));
}

/** Restore visual intent onto an authorized GET, never resurrect stale PII. */
export function restoreShopOrderDraft(
  fresh: readonly Shop[], command: UncertainShopOrderCommand,
  latestDraft: readonly ShopOrderRow[] = command.intended,
): Shop[] | null {
  if (!sameSelectedZoneMembership(command.before, fresh, command.zoneId) ||
    !sameSelectedZoneMembership(command.intended, fresh, command.zoneId) ||
    !sameSelectedZoneMembership(latestDraft, fresh, command.zoneId)) return null;
  const intended = new Map(latestDraft.map(row => [row.id, row]));
  return fresh.map(row => {
    if (row.zoneId !== command.zoneId) return row;
    const saved = intended.get(row.id);
    return saved ? { ...row, sequence: saved.sequence, archived: saved.archived } : row;
  });
}
