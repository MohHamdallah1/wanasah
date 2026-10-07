import { batchFocusIdentity, type BatchFocusIdentity } from "./batchFocusNavigation";

export type InventoryWorkspaceFocus = BatchFocusIdentity & { kind: "batch" };

/** Only an exact batch owns a standalone workspace. Product-level batch focus stays in Inventory/Batches. */
export function inventoryWorkspaceFocus(raw: unknown): InventoryWorkspaceFocus | null {
  const batch = batchFocusIdentity(raw);
  return batch ? { ...batch, kind: "batch" } : null;
}
