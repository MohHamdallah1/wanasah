import type { CatalogVariant } from "@/features/catalog/contracts";
import type { InboundDraftMap } from "./contracts";

export const INBOUND_RECALL_BLOCK_CODE = "PRODUCT_RECALL_INBOUND_NEW_BLOCKED";

// Presentation/preflight only; backend lifecycle validation remains authoritative.
// SALES_HOLD restricts sales, not supplier inbound.
export const isInboundRecallBlocked = (
  variant: Pick<CatalogVariant, "operational_hold">,
): boolean => variant.operational_hold === "RECALL";

// Partition the accumulated loaded table, never individual server pages.
// The source order stays intact so a released hold needs no stored ranking.
export function orderInboundCatalog<T extends Pick<CatalogVariant, "operational_hold">>(
  variants: readonly T[],
): T[] {
  const eligible: T[] = [];
  const recalled: T[] = [];
  for (const variant of variants) {
    (isInboundRecallBlocked(variant) ? recalled : eligible).push(variant);
  }
  return [...eligible, ...recalled];
}

// Local editable drafts only. Durable commands/pending receipts are separate
// evidence and must never be rewritten by catalog presentation changes.
export function withoutRecalledInboundDrafts(
  drafts: InboundDraftMap,
  variants: readonly Pick<CatalogVariant, "id" | "operational_hold">[],
): InboundDraftMap {
  let next = drafts;
  for (const variant of variants) {
    const key = String(variant.id);
    if (!isInboundRecallBlocked(variant) || !(key in next)) continue;
    if (next === drafts) next = { ...drafts };
    delete next[key];
  }
  return next;
}
