import type { TransferDraftItem, TransferSourceInventoryPage } from "./types";
import { compareQuantity } from "../quantity";

/** Reuse destination-aware discovery to refresh saved quantities; never trust cached availability. */
export async function restoreDraftItems(items: TransferDraftItem[], read: (search: string, cursor: string | null) => Promise<TransferSourceInventoryPage>, signal: AbortSignal) {
  const refreshed: TransferDraftItem[] = [];
  const groups = new Map<number, TransferDraftItem[]>();
  for (const item of items) groups.set(item.id, [...(groups.get(item.id) ?? []), item]);
  for (const lines of groups.values()) {
    const item = lines[0];
    const search = (item.sku && item.sku.length >= 2 ? item.sku : item.name).slice(0, 100);
    let cursor: string | null = null;
    const seen = new Set<string>();
    do {
      if (signal.aborted) return [];
      const page = await read(search, cursor);
      const fresh = page.items.find((candidate) => candidate.id === item.id);
      if (fresh) {
        if (compareQuantity(fresh.available_quantity, "0") > 0) refreshed.push(...lines.map((line) => ({ ...line, ...fresh })));
        break;
      }
      cursor = page.next_cursor;
      if (cursor && seen.has(cursor)) throw new Error("TRANSFER_RESPONSE_INVALID");
      if (cursor) seen.add(cursor);
    } while (cursor);
  }
  return refreshed;
}
