import type { SimpleProduct } from "@/pages/products/contracts";

type StatusTone =
  | "good"
  | "warning"
  | "muted"
  | "blocked";

export type ProductStatusLine = {
  labelKey: string;
  valueKey: string;
  tone: StatusTone;
};

/** Presentation only: keep product state and sales state visibly separate. */
export function productTableStatus(
  item: Pick<
    SimpleProduct,
    "lifecycle_status" | "operational_hold"
  >,
): {
  product: ProductStatusLine;
  sales: ProductStatusLine;
} {
  const productTone: StatusTone =
    item.lifecycle_status === "ACTIVE"
      ? "good"
      : item.lifecycle_status === "RETIRING"
        ? "warning"
        : "muted";

  const salesTone: StatusTone =
    item.operational_hold === "NONE"
      ? "good"
      : item.operational_hold === "SALES_HOLD"
        ? "warning"
        : "blocked";

  return {
    product: {
      labelKey:
        "products.tableStatus.productLabel",
      valueKey: `products.tableStatus.lifecycle.${item.lifecycle_status}`,
      tone: productTone,
    },
    sales: {
      labelKey:
        "products.tableStatus.salesLabel",
      valueKey: `products.tableStatus.sales.${item.operational_hold}`,
      tone: salesTone,
    },
  };
}
