import type { TFunction } from "i18next";
import { formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseBatchIndexItem } from "./batchIndexContracts";

export function formatBatchDate(value: string | null, locale: string, empty: string): string {
  if (!value) return empty;
  return new Intl.DateTimeFormat(locale, {
    year: "numeric", month: "2-digit", day: "2-digit",
    numberingSystem: "latn", timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

export function batchQuantityView(t: TFunction, item: WarehouseBatchIndexItem, value: string) {
  return formatCommercialQuantity(
    value,
    String(t(`uom.${item.display_uom_code}`, { defaultValue: item.display_uom_name || item.display_uom_code })),
    String(t(`uom.${item.base_uom_code}`, { defaultValue: item.base_uom_name || item.base_uom_code })),
    item.display_factor_to_base,
  );
}
