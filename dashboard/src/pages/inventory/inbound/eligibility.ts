import type { CatalogVariant } from "@/features/catalog/contracts";

export const INBOUND_RECALL_BLOCK_CODE = "PRODUCT_RECALL_INBOUND_NEW_BLOCKED";

// Presentation/preflight only; backend lifecycle validation remains authoritative.
// SALES_HOLD restricts sales, not supplier inbound.
export const isInboundRecallBlocked = (
  variant: Pick<CatalogVariant, "operational_hold">,
): boolean => variant.operational_hold === "RECALL";
