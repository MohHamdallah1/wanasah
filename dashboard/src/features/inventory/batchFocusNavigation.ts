import { parseInventoryNavigationState } from "./navigation";

export type BatchFocusIdentity = { batchId: number; variantId: number };

/** Strip warehouse/name hints; the owning read resolves the batch itself. */
export function batchFocusIdentity(raw: unknown): BatchFocusIdentity | null {
  const intent = parseInventoryNavigationState(raw);
  if (intent?.kind === "batch-focus" && intent.batchId !== null) {
    return { batchId: intent.batchId, variantId: intent.variantId };
  }
  if (intent?.kind === "owner-focus" && intent.flow === "batch") {
    return { batchId: intent.operationId, variantId: intent.variantId };
  }
  return null;
}
