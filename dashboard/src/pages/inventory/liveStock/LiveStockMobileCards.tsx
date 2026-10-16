import { PackageOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseProduct } from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";

type Props = {
  products: WarehouseProduct[];
  onOpen: (product: WarehouseProduct) => void;
};

export function LiveStockMobileCards({ products, onOpen }: Props) {
  const { t, i18n } = useTranslation();
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);

  return (
    <div className="space-y-2 p-2 md:hidden" data-testid="live-stock-mobile-cards">
      {products.map((product) => {
        const displayName = t(`uom.${product.display_uom_code}`, {
          defaultValue: product.display_uom_code,
        });
        const baseName = t(`uom.${product.base_uom_code}`, {
          defaultValue: product.base_uom_code,
        });
        const quantity = (value: typeof product.on_hand_quantity) =>
          formatCommercialQuantity(
            value,
            displayName,
            baseName,
            product.display_factor_to_base,
          );
        return (
          <article key={product.id} className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-black text-slate-900">{product.name}</h3>
                <p className="mt-0.5 truncate text-[11px] font-semibold text-slate-500">
                  {product.family_name}{product.sku ? ` · ${product.sku}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onOpen(product)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] font-black text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                aria-label={`${copy.openBatchDetails}: ${product.name}`}
              >
                <PackageOpen className="h-4 w-4" aria-hidden="true" />
                {copy.mobileOpen}
              </button>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-xl bg-slate-50 px-3 py-2">
                <dt className="text-[10px] font-bold text-slate-500">{t("inventoryLive.onHand")}</dt>
                <dd className="mt-1 font-black tabular-nums text-slate-900" dir="ltr">
                  {quantity(product.on_hand_quantity)}
                </dd>
              </div>
              <div className="rounded-xl bg-slate-50 px-3 py-2">
                <dt className="text-[10px] font-bold text-slate-500">{t("inventoryLive.availableForSale")}</dt>
                <dd className="mt-1 font-black tabular-nums text-slate-900" dir="ltr">
                  {quantity(product.available_for_sale_quantity)}
                </dd>
              </div>
              <div className="rounded-xl bg-slate-50 px-3 py-2">
                <dt className="text-[10px] font-bold text-slate-500">{t("inventoryLive.reserved")}</dt>
                <dd className="mt-1 font-black tabular-nums text-slate-900" dir="ltr">
                  {quantity(product.reserved_quantity)}
                </dd>
              </div>
              <div className="rounded-xl bg-slate-50 px-3 py-2">
                <dt className="text-[10px] font-bold text-slate-500">{t("inventoryLive.unavailable")}</dt>
                <dd className="mt-1 font-black tabular-nums text-slate-900" dir="ltr">
                  {quantity(product.unavailable_quantity)}
                </dd>
              </div>
            </dl>
          </article>
        );
      })}
    </div>
  );
}
