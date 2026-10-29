import type { TransferDraftItem, TransferLocationOption } from "./types";
import { parseSourceInventoryPage, parseTransferLocations } from "./parsers";
import { validateVariantQuantity, compareQuantity } from "../quantity";

export type TransferWarehouse = Omit<TransferLocationOption, "location_type" | "vehicle_id"> & { location_type: "WAREHOUSE"; vehicle_id: null };
export type TransferDraft = {
  schema_version: 3; source: TransferWarehouse | null; destination: TransferWarehouse | null;
  notes: string; items: TransferDraftItem[];
};
const key = (scope: string) => scope + ":draft";
export const isTransferWarehouse = (location: TransferLocationOption): location is TransferWarehouse =>
  location.location_type === "WAREHOUSE" && location.vehicle_id === null;
export function readTransferDraft(scope: string): TransferDraft | null {
  const raw = localStorage.getItem(key(scope));
  if (raw === null) return null;
  try {
    const draft = JSON.parse(raw) as TransferDraft;
    if (!draft || draft.schema_version !== 3 || typeof draft.notes !== "string" || draft.notes.length > 4000 ||
        !Array.isArray(draft.items) || draft.items.length > 5000) throw new Error();
    const warehouse = (value: unknown): TransferWarehouse | null => {
      if (value === null) return null;
      const [parsed] = parseTransferLocations([value]);
      if (!isTransferWarehouse(parsed)) throw new Error();
      return parsed;
    };
    const source = warehouse(draft.source), destination = warehouse(draft.destination);
    if ((source && destination && source.id === destination.id) || (draft.items.length && (!source || !destination))) throw new Error();
    parseSourceInventoryPage({ items: draft.items, has_more: false, next_cursor: null, total: null });
    for (const item of draft.items) {
      if (
        typeof item.draft_key !== "string" ||
        !item.draft_key ||
        typeof item.quantity !== "string" ||
        !["auto", "exact"].includes(item.batch_mode) ||
        !["auto", "override"].includes(item.fefo_mode) ||
        item.product_variant_id !== item.id ||
        (item.batch_mode === "auto" &&
          (item.batch_id !== null ||
            item.batch_available !== null)) ||
        (item.batch_mode === "exact" &&
          item.fefo_mode !== "auto") ||
        compareQuantity(
          validateVariantQuantity(
            item.quantity,
            item.quantity_scale,
            item.quantity_step,
          ),
          item.available_quantity,
        ) > 0
      ) throw new Error();
    }
    return { schema_version: 2, source, destination, notes: draft.notes, items: draft.items };
  } catch {
    // Old/incompatible form drafts are disposable, never durable in-flight commands.
    localStorage.removeItem(key(scope));
    return null;
  }
}
export const writeTransferDraft = (scope: string, draft: TransferDraft) => localStorage.setItem(key(scope), JSON.stringify(draft));
export const clearTransferDraft = (scope: string) => localStorage.removeItem(key(scope));
