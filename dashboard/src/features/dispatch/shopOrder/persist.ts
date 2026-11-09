import type { Shop } from "@/types/dispatch";
import {
  buildShopOrderChanges, verifyShopOrderReadback,
  type ShopOrderChange, type UncertainShopOrderCommand,
} from "./scope";

/** One mutation followed by one authoritative, no-store, authorized read. */
export interface ShopOrderCommitArgs {
  original: readonly Shop[];
  draft: readonly Shop[];
  selectedZoneId: string;
  send: (changes: readonly ShopOrderChange[]) => Promise<unknown>;
  read: () => Promise<Shop[]>;
}

export class ShopOrderVerificationError extends Error {
  constructor() { super("SHOP_ORDER_READBACK_MISMATCH"); this.name = "ShopOrderVerificationError"; }
}

/** HTTP rejection is definitive only when the server rejected this mutation. */
const definitelyRejectedBeforeMutation = (error: unknown): boolean => {
  if (!error || typeof error !== "object") return false;
  const failure = error as { status?: unknown; response?: { status?: unknown } };
  const status = failure.status ?? failure.response?.status;
  return typeof status === "number" && [400, 401, 403, 404, 409, 422].includes(status);
};

/**
 * A lost response, a successful PUT with failed GET, or mismatched full readback
 * leaves the write outcome UNKNOWN. The caller must reconcile before any retry.
 */
export class ShopOrderUncertainError extends ShopOrderVerificationError {
  readonly command: UncertainShopOrderCommand;
  constructor(zoneId: string, before: readonly Shop[], intended: readonly Shop[]) {
    super();
    this.name = "ShopOrderUncertainError";
    const inZone = (shops: readonly Shop[]) =>
      shops.filter(row => row.zoneId === zoneId).map(row => ({ ...row }));
    this.command = { zoneId, before: inZone(before), intended: inZone(intended) };
  }
}

export async function commitShopOrder({
  original, draft, selectedZoneId, send, read,
}: ShopOrderCommitArgs): Promise<{ kind: "no_changes" } | { kind: "confirmed"; shops: Shop[] }> {
  const changes = buildShopOrderChanges(original, draft, selectedZoneId);
  if (!changes.length) return { kind: "no_changes" };

  try {
    await send(changes);
  } catch (error) {
    if (definitelyRejectedBeforeMutation(error)) throw error;
    // Timeout/abort/5xx may have persisted the command despite lost response.
    throw new ShopOrderUncertainError(selectedZoneId, original, draft);
  }

  try {
    const latest = await read();
    if (!Array.isArray(latest) || !verifyShopOrderReadback(changes, latest, selectedZoneId, draft)) {
      throw new ShopOrderVerificationError();
    }
    return { kind: "confirmed", shops: latest };
  } catch {
    // Even a 401/403 from GET does not roll back an already successful PUT.
    throw new ShopOrderUncertainError(selectedZoneId, original, draft);
  }
}
