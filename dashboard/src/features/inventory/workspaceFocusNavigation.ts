import { batchFocusIdentity, type BatchFocusIdentity } from "./batchFocusNavigation";
import { parseInventoryNavigationState } from "./navigation";

export type InventoryWorkspaceFocus =
  | (BatchFocusIdentity & { kind: "batch" })
  | { kind: "quality"; variantId: number; productName: string };

/** Route labels are context only; owning Inventory reads resolve state/access. */
export function inventoryWorkspaceFocus(raw: unknown): InventoryWorkspaceFocus | null {
  const batch = batchFocusIdentity(raw);
  if (batch) return { ...batch, kind: "batch" };
  const intent = parseInventoryNavigationState(raw);
  return intent?.kind === "quality-issue"
    ? { kind: "quality", variantId: intent.variantId, productName: intent.productName }
    : null;
}
