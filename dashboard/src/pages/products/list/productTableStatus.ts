import type { SimpleProduct } from "@/pages/products/contracts";
import {
  productCommercialStatus,
} from "@/features/catalog/status/productCommercialStatus";

type StatusTone =
  | "good"
  | "warning"
  | "muted"
  | "blocked";

export type ProductStatusLine = {
  valueKey: string;
  tone: StatusTone;
};

/** Presentation only: one commercial status, backend authority stays unchanged. */
export function productTableStatus(
  item: Pick<
    SimpleProduct,
    "lifecycle_status" | "operational_hold"
  >,
): {
  status: ProductStatusLine;
  reason: ProductStatusLine | null;
} {
  const commercial =
    productCommercialStatus(item);

  return {
    status: {
      valueKey: commercial.stateKey,
      tone: commercial.tone,
    },
    reason: commercial.reasonKey
      ? {
          valueKey:
            commercial.reasonKey,
          tone: "muted",
        }
      : null,
  };
}
