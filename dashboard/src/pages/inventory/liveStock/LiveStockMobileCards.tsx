import { AlertTriangle, PackageOpen } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { compareQuantity, formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseProduct } from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";

type Props = {
  products: WarehouseProduct[];
  totalCount?: number;
  startIndex?: number;
  topSpacerHeight?: number;
  bottomSpacerHeight?: number;
  onItemExtentChange?: (height: number) => void;
  onProductFocus?: (productId: number) => void;
  onProductBlur?: (nextTarget: EventTarget | null) => void;
  onOpen: (product: WarehouseProduct) => void;
};

export function LiveStockMobileCards({
  products,
  totalCount = products.length,
  startIndex = 0,
  topSpacerHeight = 0,
  bottomSpacerHeight = 0,
  onItemExtentChange = () => undefined,
  onProductFocus = () => undefined,
  onProductBlur = () => undefined,
  onOpen,
}: Props) {
  const { t, i18n } = useTranslation();
  const measureFirstCard = useCallback(
    (node: HTMLElement | null) => {
      if (!node) return;
      const height = node.getBoundingClientRect().height;
      if (height > 0) onItemExtentChange(height + 6);
    },
    [onItemExtentChange],
  );
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);

  return (
    <div
      className="space-y-1.5 p-2 md:hidden"
      data-testid="live-stock-mobile-cards"
      data-cp13-phone-list="true"
      role="list"
    >
      {topSpacerHeight > 0 ? (
        <div aria-hidden="true" data-live-stock-window-spacer="top" style={{ height: topSpacerHeight }} />
      ) : null}
      {products.map((product, index) => {
        const displayName = t(`uom.${product.display_uom_code}`, {
          defaultValue: t("inventoryCommon.unit"),
        });
        const baseName = t(`uom.${product.base_uom_code}`, {
          defaultValue: t("inventoryCommon.unit"),
        });
        const quantity = (value: typeof product.on_hand_quantity) =>
          formatCommercialQuantity(
            value,
            displayName,
            baseName,
            product.display_factor_to_base,
          );
        const hasMinimum = compareQuantity(product.minimum_quantity, "0") > 0;
        const isAlert = hasMinimum && compareQuantity(
          product.available_for_sale_quantity,
          product.minimum_quantity,
        ) <= 0;
        const minimum = hasMinimum
          ? quantity(product.minimum_quantity).primary
          : t("inventoryLive.minimumStockUnset");
        const metrics = [
          ["onHand", product.on_hand_quantity, "text-slate-900", "on-hand"],
          ["availableForSale", product.available_for_sale_quantity, "text-emerald-700", "available"],
          ["reserved", product.reserved_quantity, "text-amber-700", "reserved"],
          ["unavailable", product.unavailable_quantity, "text-rose-700", "unavailable"],
          ["withVehicles", product.vehicle_quantity, "text-blue-700", "vehicle"],
        ] as const;

        return (
          <article
            key={product.id}
            ref={index === 0 ? measureFirstCard : undefined}
            className={`rounded-xl border bg-white p-2.5 shadow-sm ${isAlert ? "border-red-200" : "border-slate-200"}`}
            data-cp13-stock-card="compact"
            role="listitem"
            aria-setsize={totalCount}
            aria-posinset={startIndex + index + 1}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1.5">
                  {isAlert ? <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" aria-label={t("inventoryLive.atMinimum")} /> : null}
                  <h3 className="truncate text-sm font-black text-slate-900">{product.name}</h3>
                </div>
                <p className="mt-0.5 truncate text-[10px] font-semibold text-slate-500">
                  {product.family_name}{product.sku ? ` · ${product.sku}` : ""}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold text-slate-500">
                  {t("inventoryLive.minimumStockLabel")}: <span dir="ltr">{minimum}</span>
                </p>
              </div>
              <button
                type="button"
                onClick={() => onOpen(product)}
                onFocus={(event) => {
                  onProductFocus(product.id);
                  event.currentTarget.scrollIntoView({ block: "nearest" });
                }}
                onBlur={(event) => onProductBlur(event.relatedTarget)}
                data-live-stock-product-open={product.id}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] font-black text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                aria-label={`${copy.openBatchDetails}: ${product.name}`}
              >
                <PackageOpen className="h-3.5 w-3.5" aria-hidden="true" />
                {copy.mobileOpen}
              </button>
            </div>
            <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2 border-t border-slate-100 pt-2 text-[10px]">
              {metrics.map(([label, value, tone, metric]) => {
                const rendered = quantity(value);
                return (
                  <div key={label} className="min-w-0" data-cp13-quantity={metric}>
                    <dt className="truncate font-bold text-slate-500">{t(`inventoryLive.${label}`)}</dt>
                    <dd
                      className={`mt-0.5 truncate font-black tabular-nums ${tone}`}
                      dir="ltr"
                      title={rendered.secondary ?? undefined}
                    >
                      {rendered.primary}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </article>
        );
      })}
      {bottomSpacerHeight > 0 ? (
        <div aria-hidden="true" data-live-stock-window-spacer="bottom" style={{ height: bottomSpacerHeight }} />
      ) : null}
    </div>
  );
}
