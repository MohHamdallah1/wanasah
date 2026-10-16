import { useTranslation } from "react-i18next";

import { resolveI18nLocale } from "@/lib/locale";
import { formatMoneyDisplay, formatMoneyExact } from "@/lib/money";
import { compareQuantity, formatCommercialQuantity } from "@/lib/quantity";
import type { WarehouseProduct } from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";

type Props = {
  products: WarehouseProduct[];
  loading: boolean;
  onOpen: (product: WarehouseProduct) => void;
};

export function LiveStockTable({ products, loading, onOpen }: Props) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);

  return (
    <table
      className="live-stock-table hidden md:table"
      aria-label={t("inventoryShell.tabs.live")}
      aria-busy={loading}
    >
      <thead>
        <tr className="live-stock-columns">
          <th scope="col" className="live-stock-number-heading">#</th>
          <th scope="col" className="live-product-heading">{t("inventoryLive.product")}</th>
          <th scope="col" className="live-family-heading">{t("inventoryLive.family")}</th>
          <th scope="col">{t("inventoryLive.onHand")}</th>
          <th scope="col">{t("inventoryLive.reserved")}</th>
          <th scope="col">{t("inventoryLive.availableForSale")}</th>
          <th scope="col">{t("inventoryLive.unavailable")}</th>
          <th scope="col">{t("inventoryLive.withVehicles")}</th>
          <th scope="col">{t("inventoryLive.lastCompanyPurchase")}</th>
          <th scope="col">{t("inventoryLive.companyAverage")}</th>
        </tr>
      </thead>
      <tbody>
        {products.map((product, index) => {
          const isAlert =
            compareQuantity(product.minimum_quantity, "0") > 0 &&
            compareQuantity(
              product.available_for_sale_quantity,
              product.minimum_quantity,
            ) <= 0;
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
          const lastPurchaseUom = product.last_purchase_uom_code
            ? t(`uom.${product.last_purchase_uom_code}`, {
                defaultValue: product.last_purchase_uom_code,
              })
            : null;

          return (
            <tr
              key={product.id}
              className={`live-stock-row border-b border-slate-100/80 transition-colors ${
                isAlert ? "bg-amber-50/50" : ""
              }`}
            >
              <td className="px-3 py-3 text-center text-xs font-bold tabular-nums text-slate-400">
                {new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(index + 1)}
              </td>
              <td className="px-4 py-3">
                <button
                  type="button"
                  onClick={() => onOpen(product)}
                  className="max-w-[260px] text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                  aria-label={`${copy.openBatchDetails}: ${product.name}`}
                >
                  <span className="block truncate text-sm font-black text-slate-900 underline-offset-4 hover:underline">
                    {product.name}
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] font-semibold text-slate-500" dir="ltr">
                    {product.sku ?? "—"}
                  </span>
                </button>
              </td>
              <td className="px-4 py-3 text-start text-xs font-bold text-slate-600">
                {product.family_name}
              </td>
              {[product.on_hand_quantity, product.reserved_quantity, product.available_for_sale_quantity, product.unavailable_quantity, product.vehicle_quantity].map((value, quantityIndex) => (
                <td key={quantityIndex} className="px-4 py-3 text-center text-xs font-black tabular-nums text-slate-900" dir="ltr">
                  {quantity(value)}
                </td>
              ))}
              <td className="px-4 py-3 text-center text-xs">
                {product.last_purchase_cost && lastPurchaseUom ? (
                  <div
                    className="font-black tabular-nums text-slate-900"
                    title={`${formatMoneyExact(product.last_purchase_cost, product.currency_code, locale)} · ${lastPurchaseUom}`}
                  >
                    {formatMoneyDisplay(product.last_purchase_cost, product.currency_code, locale)}
                  </div>
                ) : "—"}
              </td>
              <td className="px-4 py-3 text-center text-xs">
                {product.average_cost_display ? (
                  <div
                    className="font-black tabular-nums text-slate-900"
                    title={formatMoneyExact(product.average_cost_display, product.currency_code, locale)}
                  >
                    {formatMoneyDisplay(product.average_cost_display, product.currency_code, locale)}
                  </div>
                ) : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
