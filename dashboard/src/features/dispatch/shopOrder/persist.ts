import type { Shop } from "@/types/dispatch";
import { buildShopOrderChanges, verifyShopOrderReadback, type ShopOrderChange } from "./scope";

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

export async function commitShopOrder({
  original, draft, selectedZoneId, send, read,
}: ShopOrderCommitArgs): Promise<{ kind: "no_changes" } | { kind: "confirmed"; shops: Shop[] }> {
  const changes = buildShopOrderChanges(original, draft, selectedZoneId);
  if (!changes.length) return { kind: "no_changes" };
  await send(changes);
  const latest = await read();
  if (!Array.isArray(latest) || !verifyShopOrderReadback(changes, latest, selectedZoneId, draft)) {
    throw new ShopOrderVerificationError();
  }
  return { kind: "confirmed", shops: latest };
}
