import type { TransferCreateDirection, TransferDraftItem, TransferLocationOption } from "./types";
import { parseSourceInventoryPage, parseTransferLocations } from "./parsers";

export type TransferDraft = {
  direction: TransferCreateDirection; counterpart: number | null; notes: string;
  purpose: "REPLENISHMENT" | "WAREHOUSE_BALANCING"; items: TransferDraftItem[]; locations: TransferLocationOption[];
};
const key = (scope: string) => scope + ":draft";
export function readTransferDraft(scope: string): TransferDraft | null {
  const raw = localStorage.getItem(key(scope));
  if (raw === null) return null;
  const draft = JSON.parse(raw) as TransferDraft;
  if (!draft || !["outgoing", "incoming"].includes(draft.direction) || typeof draft.notes !== "string" ||
      !["REPLENISHMENT", "WAREHOUSE_BALANCING"].includes(draft.purpose) || !Array.isArray(draft.items) || draft.items.length > 5000 ||
      (draft.counterpart !== null && (!Number.isSafeInteger(draft.counterpart) || draft.counterpart <= 0))) {
    throw Object.assign(new Error(), { code: "DURABLE_OPERATION_CORRUPT" });
  }
  parseSourceInventoryPage({ items: draft.items, has_more: false, next_cursor: null, total: null });
  for (const item of draft.items) {
    if (typeof item.draft_key !== "string" || typeof item.quantity !== "string" || !["auto", "override"].includes(item.fefo_mode) || item.product_variant_id !== item.id) {
      throw Object.assign(new Error(), { code: "DURABLE_OPERATION_CORRUPT" });
    }
  }
  return { ...draft, locations: parseTransferLocations(draft.locations) };
}
export const writeTransferDraft = (scope: string, draft: TransferDraft) => localStorage.setItem(key(scope), JSON.stringify(draft));
export const clearTransferDraft = (scope: string) => localStorage.removeItem(key(scope));
