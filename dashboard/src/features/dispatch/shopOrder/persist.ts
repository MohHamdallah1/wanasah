import type { Shop } from "@/types/dispatch";
import {
  buildShopOrderChanges, verifyShopOrderReadback,
  type ShopOrderChange, type ShopOrderWriteOutcome, type UncertainShopOrderCommand,
} from "./scope";

/** One mutation followed by one authoritative, no-store, authorized read. */
export interface ShopOrderCommitArgs {
  original: readonly Shop[];
  draft: readonly Shop[];
  selectedZoneId: string;
  send: (changes: readonly ShopOrderChange[]) => Promise<unknown>;
  read: () => Promise<Shop[]>;
  /** Durable draft before any transport is attempted (must throw on failure). */
  beforeSend?: (command: UncertainShopOrderCommand) => void;
  /** Durable completion of PUT before even attempting readback. */
  putConfirmed?: (command: UncertainShopOrderCommand) => void;
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

const attemptedCommand = (
  zoneId: string, before: readonly Shop[], intended: readonly Shop[],
  outcome: ShopOrderWriteOutcome,
): UncertainShopOrderCommand => {
  const inZone = (shops: readonly Shop[]) =>
    shops.filter(row => row.zoneId === zoneId).map(({ id, zoneId, sequence, archived }) =>
      ({ id, zoneId, sequence, archived }));
  return { zoneId, before: inZone(before), intended: inZone(intended), outcome };
};

/**
 * Transport timeout does NOT imply server completion. Only a confirmed PUT
 * response makes a later readback reconciliation safe to use for new writes.
 */
export class ShopOrderUncertainError extends ShopOrderVerificationError {
  readonly command: UncertainShopOrderCommand;
  constructor(command: UncertainShopOrderCommand) {
    super();
    this.name = "ShopOrderUncertainError";
    this.command = command;
  }
}

export async function commitShopOrder({
  original, draft, selectedZoneId, send, read, beforeSend, putConfirmed,
}: ShopOrderCommitArgs): Promise<{ kind: "no_changes" } | { kind: "confirmed"; shops: Shop[] }> {
  const changes = buildShopOrderChanges(original, draft, selectedZoneId);
  if (!changes.length) return { kind: "no_changes" };
  const unknown = attemptedCommand(selectedZoneId, original, draft, "transport_unknown");
  const completed = attemptedCommand(selectedZoneId, original, draft, "put_confirmed");

  // If the browser cannot safely retain recovery evidence, make NO mutation.
  beforeSend?.(unknown);
  try {
    await send(changes);
  } catch (error) {
    if (definitelyRejectedBeforeMutation(error)) throw error;
    // A timed-out PUT can STILL be running: never allow a later stale-diff PUT.
    throw new ShopOrderUncertainError(unknown);
  }

  try {
    // Called before GET: logout caused by a failed read must not lose the draft.
    putConfirmed?.(completed);
  } catch {
    throw new ShopOrderUncertainError(unknown); // durable completion marker failed
  }

  try {
    const latest = await read();
    if (!Array.isArray(latest) || !verifyShopOrderReadback(changes, latest, selectedZoneId, draft)) {
      throw new ShopOrderVerificationError();
    }
    return { kind: "confirmed", shops: latest };
  } catch {
    // A GET 401/403 cannot undo a PUT that already returned success.
    throw new ShopOrderUncertainError(completed);
  }
}
