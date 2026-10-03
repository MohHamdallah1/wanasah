import type { SimpleProduct } from "@/pages/products/contracts";

type StatusTone = "available" | "retiring" | "archived" | "hold" | "recall";
type StatusBadge = { labelKey: string; tone: StatusTone };

/** Presentation only: expose both backend dimensions without deriving sale authority. */
export function productTableStatus(
  item: Pick<SimpleProduct, "lifecycle_status" | "operational_hold">,
): { primary: StatusBadge; secondary: StatusBadge | null } {
  const lifecycle: StatusBadge = {
    labelKey: `products.tableStatus.${item.lifecycle_status}`,
    tone: item.lifecycle_status === "ACTIVE" ? "available"
      : item.lifecycle_status === "RETIRING" ? "retiring" : "archived",
  };
  if (item.operational_hold === "NONE") {
    return { primary: lifecycle, secondary: null };
  }
  return {
    primary: {
      labelKey: `products.tableStatus.${item.operational_hold}`,
      tone: item.operational_hold === "RECALL" ? "recall" : "hold",
    },
    secondary: item.lifecycle_status === "ACTIVE"
      ? { ...lifecycle, labelKey: "products.tableStatus.activeLifecycle" }
      : lifecycle,
  };
}
