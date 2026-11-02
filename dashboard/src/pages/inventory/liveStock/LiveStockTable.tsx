import { VehicleCustodyQuantity } from "./VehicleCustodyQuantity";
import { CommercialQuantityDisplay } from "./CommercialQuantityDisplay";
import { AlertTriangle, Info } from "lucide-react";
import * as Tooltip from "@radix-ui/react-tooltip";
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
  loading: boolean;
  onItemMeasure?: (productId: number, height: number) => void;
  onProductFocus?: (productId: number) => void;
  onProductBlur?: (nextTarget: EventTarget | null) => void;
  onOpen: (product: WarehouseProduct) => void;
  onOpenUnavailable?: (product: WarehouseProduct) => void;
};

function HeaderHelp({ text }: { text: string }) {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button type="button" className="live-header-help outline-none focus-visible:ring-2 focus-visible:ring-amber-400" aria-label={text}>
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={8}
            collisionPadding={16}
            className="live-help-content"
          >
            {text}
            <Tooltip.Arrow className="fill-slate-900" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function LiveStockTable({
  products,
  totalCount = products.length,
  startIndex = 0,
  topSpacerHeight = 0,
  bottomSpacerHeight = 0,
  loading,
  onItemMeasure = () => undefined,
  onProductFocus = () => undefined,
  onProductBlur = () => undefined,
  onOpen,
  onOpenUnavailable = onOpen,
}: Props) {
  const { t, i18n } = useTranslation();
  const measureRow = useCallback(
    (productId: number, node: HTMLTableRowElement | null) => {
      if (!node) return;
      const height = node.getBoundingClientRect().height;
      if (height > 0) onItemMeasure(productId, height);
    },
    [onItemMeasure],
  );
  const locale = resolveI18nLocale(i18n);
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);

  const formatDate = (value: string | null): string => {
    if (!value) return "—";
    try {
      return new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        numberingSystem: "latn",
        timeZone: "UTC",
      }).format(new Date(`${value}T00:00:00Z`));
    } catch {
      return value;
    }
  };

  const headers = [
    ["onHand", "onHandHint"],
    ["reserved", "reservedHint"],
    ["availableForSale", "availableForSaleHint"],
    ["unavailable", "unavailableHint"],
    ["withVehicles", "withVehiclesHint"],
    ["lastCompanyPurchase", "lastCompanyPurchaseHint"],
    ["companyAverage", "companyAverageHint"],
  ] as const;

  return (
    <table
      className="live-stock-table hidden md:table min-w-[1180px]"
      aria-label={t("inventoryShell.tabs.live")}
      aria-busy={loading}
      aria-rowcount={totalCount + 1}
      data-cp13-stock-table="compact"
    >
      <thead>
        <tr className="live-stock-columns">
          <th scope="col" className="live-stock-number-heading">#</th>
          <th scope="col" className="live-product-heading">{t("inventoryLive.product")}</th>
          <th scope="col" className="live-family-heading">{t("inventoryLive.family")}</th>
          {headers.map(([label, hint]) => (
            <th scope="col" key={label}>
              <div className="flex items-center justify-center gap-1.5">
                <span>{t(`inventoryLive.${label}`)}</span>
                <HeaderHelp text={t(`inventoryLive.${hint}`)} />
              </div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {topSpacerHeight > 0 ? (
          <tr aria-hidden="true" data-live-stock-window-spacer="top">
            <td colSpan={10} className="p-0" style={{ height: topSpacerHeight }} />
          </tr>
        ) : null}
        {products.map((product, index) => {
          const hasMinimum = compareQuantity(product.minimum_quantity, "0") > 0;
          const isAlert = product.is_low_stock;
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
          const values = [
            [product.on_hand_quantity, "text-slate-900", "on-hand"],
            [product.reserved_quantity, "text-amber-700", "reserved"],
            [product.available_for_sale_quantity, "text-emerald-700", "available"],
            [product.unavailable_quantity, "text-rose-700", "unavailable"],
          ] as const;

          const absolutePosition = startIndex + index + 1;

          return (
            <tr
              key={product.id}
              ref={(node) => measureRow(product.id, node)}
              aria-rowindex={startIndex + index + 2}
              className={`live-stock-row border-b border-slate-100/80 transition-colors ${
                isAlert ? "bg-red-50/45 hover:bg-red-50/75" : "bg-white hover:bg-slate-50/65"
              }`}
              data-cp13-stock-row="compact"
            >
              <td className="live-stock-number-cell px-3 py-2 text-center text-xs font-bold tabular-nums text-slate-400">
                <span
                  className="live-stock-row-number tabular-nums"
                  aria-label={t("inventoryLive.rowNumber", { number: absolutePosition })}
                >
                  {new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(absolutePosition)}
                </span>
              </td>
              <td className="live-product-cell px-3 py-2">
                <button
                  type="button"
                  onClick={() => onOpen(product)}
                  onFocus={(event) => {
                    onProductFocus(product.id);
                    event.currentTarget.scrollIntoView({ block: "nearest" });
                  }}
                  onBlur={(event) => onProductBlur(event.relatedTarget)}
                  data-live-stock-product-open={product.id}
                  className="w-full min-w-0 rounded-md text-start outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                  aria-label={`${copy.openBatchDetails}: ${product.name}`}
                >
                  <span className="flex items-center gap-2">
                    {isAlert ? (
                      <AlertTriangle
                        className="h-3.5 w-3.5 shrink-0 text-red-500"
                        aria-label={t("inventoryLive.atMinimum")}
                      />
                    ) : null}
                    <span className="live-stock-product-name-clamp block text-sm font-black text-slate-900 underline-offset-4 hover:underline">
                      {product.name}
                    </span>
                  </span>
                  <span className="live-stock-minimum-row mt-0.5 block text-[10px] font-semibold text-slate-500">
                    {t("inventoryLive.minimumStockLabel")}: {hasMinimum
                      ? <CommercialQuantityDisplay text={quantity(product.minimum_quantity).primary} direction={i18n.dir()} />
                      : t("inventoryLive.minimumStockUnset")}
                  </span>
                </button>
              </td>
              <td className="live-family-cell px-3 py-2 text-center text-xs font-bold text-slate-600">
                <div className="live-family-name" title={product.family_name}>{product.family_name}</div>
              </td>
              {values.map(([value, tone, metric], quantityIndex) => {
                const rendered = quantity(value);
                return (
                  <td
                    key={quantityIndex}
                    className={`px-3 py-2 text-center text-xs font-black tabular-nums ${tone}`}
                    dir={i18n.dir()}
                    title={rendered.secondary ?? undefined}
                    data-cp13-quantity={metric}
                  >
                    {metric === "unavailable" && compareQuantity(value, "0") > 0 ? (
                      <button
                        type="button"
                        onClick={() => onOpenUnavailable(product)}
                        aria-label={`${copy.unavailableBreakdown} — ${product.name}`}
                        title={copy.unavailableBreakdown}
                        className="rounded-md px-1 underline decoration-dotted underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                      >
                        <CommercialQuantityDisplay text={rendered.primary} direction={i18n.dir()} />
                      </button>
                    ) : <CommercialQuantityDisplay text={rendered.primary} direction={i18n.dir()} />}
                  </td>
                );
              })}
              <td className="px-3 py-2 text-center text-xs font-black text-blue-700" data-cp13-quantity="vehicle">
                <VehicleCustodyQuantity product={product} />
              </td>
              <td className="px-3 py-2 text-center text-xs">
                {product.last_purchase_cost && lastPurchaseUom ? (
                  <div
                    className="font-black tabular-nums text-slate-900"
                    title={`${formatMoneyExact(product.last_purchase_cost, product.currency_code, locale)} · ${t("inventoryLive.perUnit", { unit: lastPurchaseUom })}${product.last_purchase_date ? ` · ${formatDate(product.last_purchase_date)}` : ""}`}
                  >
                    {formatMoneyDisplay(product.last_purchase_cost, product.currency_code, locale)}
                  </div>
                ) : "—"}
              </td>
              <td className="px-3 py-2 text-center text-xs">
                {product.average_cost_display ? (
                  <div
                    className="font-black tabular-nums text-slate-900"
                    title={`${formatMoneyExact(product.average_cost_display, product.currency_code, locale)} · ${t("inventoryLive.perUnit", { unit: displayName })}`}
                  >
                    {formatMoneyDisplay(product.average_cost_display, product.currency_code, locale)}
                  </div>
                ) : "—"}
              </td>
            </tr>
          );
        })}
        {bottomSpacerHeight > 0 ? (
          <tr aria-hidden="true" data-live-stock-window-spacer="bottom">
            <td colSpan={10} className="p-0" style={{ height: bottomSpacerHeight }} />
          </tr>
        ) : null}
      </tbody>
    </table>
  );
}
