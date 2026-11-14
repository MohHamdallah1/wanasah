import { formatCommercialQuantity, formatQuantity } from "@/lib/quantity";
import type { StockLine } from "./contract";

/** Presentation only: canonical on_hand_base and snapshot remain untouched. */
export function formatCustodyStockQuantity(
  line: Pick<StockLine, "on_hand_base" | "base_uom" | "base_uom_name" |
    "display_uom_name" | "display_factor_to_base">,
): string {
  const baseName = line.base_uom_name || line.base_uom;
  if (line.display_uom_name && line.display_factor_to_base) {
    return formatCommercialQuantity(
      line.on_hand_base, line.display_uom_name, baseName,
      line.display_factor_to_base,
    ).primary;
  }
  return formatQuantity(line.on_hand_base, baseName);
}
