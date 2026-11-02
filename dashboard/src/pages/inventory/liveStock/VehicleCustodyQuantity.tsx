import { useTranslation } from "react-i18next";
import { CommercialQuantityDisplay } from "./CommercialQuantityDisplay";
import { formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseProduct } from "./contracts";

type Props = {
  product: Pick<WarehouseProduct, "vehicle_quantity" | "vehicle_quantity_scope" |
    "display_uom_code" | "base_uom_code" | "display_factor_to_base">;
};

/** Cross-location disclosure; never added to the selected warehouse quantity. */
export function VehicleCustodyQuantity({ product }: Props) {
  const { t, i18n } = useTranslation();
  const scope = t(`inventoryLive.vehicleScopes.${product.vehicle_quantity_scope}`);
  if (product.vehicle_quantity === null) {
    return <span dir={i18n.dir()} className="block text-xs font-semibold text-slate-500"
      data-vehicle-scope={product.vehicle_quantity_scope}>{scope}</span>;
  }
  const value = formatCommercialQuantity(
    product.vehicle_quantity,
    t(`uom.${product.display_uom_code}`, { defaultValue: t("inventoryCommon.unit") }),
    t(`uom.${product.base_uom_code}`, { defaultValue: t("inventoryCommon.unit") }),
    product.display_factor_to_base,
  );
  return <span className="block" data-vehicle-scope={product.vehicle_quantity_scope}>
    <span title={value.secondary ?? undefined}><CommercialQuantityDisplay text={value.primary} direction={i18n.dir()} /></span>
    <small dir={i18n.dir()} className="mt-0.5 block text-[10px] font-medium text-slate-500">{scope}</small>
  </span>;
}
