import { AlertTriangle, PackageOpen } from "lucide-react";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { resolveI18nLocale } from "@/lib/locale";
import { formatMoneyDisplay, formatMoneyExact } from "@/lib/money";
import { compareQuantity, formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseProduct } from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";

type Props = {
  products: WarehouseProduct[];
  totalCount?: number;
  startIndex?: number;
  topSpacerHeight?: number;
  bottomSpacerHeight?: number;
  onItemMeasure?: (productId: number, height: number) => void;
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
  onItemMeasure = () => undefined,
  onProductFocus = () => undefined,
  onProductBlur = () => undefined,
  onOpen,
}: Props) {
  const { t, i18n } = useTranslation();
  const measureCard = useCallback(
    (productId: number, node: HTMLElement | null) => {
      if (!node) return;
      const height = node.getBoundingClientRect().height;
      if (height > 0) onItemMeasure(productId, height + 6);
    },
    [onItemMeasure],
  );
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);
  const locale = resolveI18nLocale(i18n);

  return (
    <div
      className="space-y-1.5 p-2 md:hidden"
      data-testid="live-stock-mobile-cards"
      data-cp13-phone-list="true"
      role="list"
    >
      <p
        className="rounded-lg border border-blue-100 bg-blue-50/60 px-2 py-1.5 text-[9px] font-semibold leading-relaxed text-slate-600"
        data-live-stock-vehicle-attribution-note="mobile"
        role="note"
      >
        {t("inventoryLive.withVehiclesMobileDisclosure")}
      </p>
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
        const lastPurchaseUom = product.last_purchase_uom_code
          ? t(`uom.${product.last_purchase_uom_code}`, {
              defaultValue: t("inventoryCommon.unit"),
            })
          : null;
        const costs = [
          ["lastCompanyPurchase", product.last_purchase_cost, lastPurchaseUom, "last-purchase"],
          ["companyAverage", product.average_cost_display, displayName, "average"],
        ] as const;
        const hasMinimum = compareQuantity(product.minimum_quantity, "0") > 0;
        const isAlert = product.is_low_stock;
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
            ref={(node) => measureCard(product.id, node)}
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
                  <h3 className="live-stock-product-name-clamp text-sm font-black text-slate-900">{product.name}</h3>
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
                    <dt className={metric === "vehicle" ? "font-bold text-slate-500" : "truncate font-bold text-slate-500"}>
                      <span className="block truncate">{t(`inventoryLive.${label}`)}</span>
                      {metric === "vehicle" ? (
                        <span className="mt-0.5 block text-[8px] font-semibold leading-tight text-slate-400">
                          {t("inventoryLive.withVehiclesVisibleNote")}
                        </span>
                      ) : null}
                    </dt>
                    <dd
                      className={`mt-0.5 truncate font-black tabular-nums ${tone}`}
                      dir="ltr"
                      title={rendered.secondary ?? undefined}
                      aria-label={
                        metric === "vehicle"
                          ? t("inventoryLive.withVehiclesValueA11y", { quantity: rendered.primary })
                          : undefined
                      }
                    >
                      {rendered.primary}
                    </dd>
                  </div>
                );
              })}
            </dl>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 border-t border-slate-100 pt-2 text-[10px]">
              {costs.map(([label, value, unit, metric]) => {
                const known = value !== null && unit !== null;
                const perUnit = known ? t("inventoryLive.perUnit", { unit }) : null;
                const exact = known ? formatMoneyExact(value, product.currency_code, locale) : null;
                return (
                  <div key={label} className="min-w-0">
                    <dt className="truncate font-bold text-slate-500" title={t(`inventoryLive.${label}Hint`)}>
                      {t(`inventoryLive.${label}`)}
                    </dt>
                    <dd className="mt-0.5 min-w-0" data-live-stock-mobile-cost={metric}>
                      {known ? (
                        <>
                          <span
                            className="block truncate font-black tabular-nums text-slate-900"
                            dir="auto"
                            title={`${exact} · ${perUnit}`}
                            aria-hidden="true"
                          >
                            {formatMoneyDisplay(value, product.currency_code, locale)}
                          </span>
                          <span className="block truncate text-[9px] font-semibold text-slate-500" title={perUnit ?? undefined} aria-hidden="true">
                            {perUnit}
                          </span>
                          <span className="sr-only">{exact} · {perUnit}</span>
                        </>
                      ) : (
                        <span className="font-black text-slate-400">—</span>
                      )}
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
