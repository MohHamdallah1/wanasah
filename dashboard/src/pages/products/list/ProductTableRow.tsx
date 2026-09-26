import { useTranslation } from "react-i18next";

import {
  resolveI18nLocale,
} from "@/lib/locale";
import {
  formatLocaleDecimal,
} from "@/lib/localeNumbers";
import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
  type ProductDisplayColumn,
  type ProductDisplayDensity,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductRowActions } from "@/pages/products/list/ProductRowActions";

type Props = {
  item: SimpleProduct;
  pricingVisible: boolean;
  canEditPrice: boolean;
  canEditTracking: boolean;
  columns?: Record<
    ProductDisplayColumn,
    boolean
  >;
  density?: ProductDisplayDensity;
  onOpenDetails: (
    item: SimpleProduct,
  ) => void;
  onEditPrice: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
};

export function ProductTableRow({
  item,
  pricingVisible,
  canEditPrice,
  canEditTracking,
  columns,
  density =
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.density,
  onOpenDetails,
  onEditPrice,
  onEditTracking,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const locale =
    resolveI18nLocale(i18n);
  const visibleColumns =
    columns ??
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.columns;
  const cellSpacing =
    density === "compact"
      ? "px-4 py-2.5"
      : "px-4 py-3";

  const formatMoney = (
    value: string | null,
  ) =>
    value === null
      ? "—"
      : formatLocaleDecimal(
          value,
          locale,
          3,
          6,
        );

  const formatPackageUnits = (
    value: number | null,
  ) =>
    value === null
      ? "—"
      : formatLocaleDecimal(
          String(value),
          locale,
          0,
          0,
        );

  const lifecycleTone =
    item.lifecycle_status === "ACTIVE"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : item.lifecycle_status ===
          "RETIRING"
        ? "bg-amber-50 text-amber-800 ring-amber-200"
        : "bg-slate-100 text-slate-600 ring-slate-200";

  return (
    <tr className="group bg-white transition-colors hover:bg-slate-50/80">
      <td className={cellSpacing}>
        <button
          type="button"
          onClick={() =>
            onOpenDetails(item)
          }
          title={t(
            "products.details.open",
          )}
          className="max-w-[320px] text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <span className="block break-words text-[13px] font-black leading-5 text-slate-950 transition group-hover:text-slate-700">
            {item.name}
          </span>
          {item.family_name !==
          item.name ? (
            <span className="mt-0.5 block break-words text-[10px] font-bold leading-4 text-slate-500">
              {item.family_name}
            </span>
          ) : null}
          <span className="mt-0.5 block break-all font-mono text-[10px] font-semibold leading-4 text-slate-400">
            {t(
              "products.fields.sku",
            )}
            : {item.sku}
          </span>
        </button>
      </td>

      {visibleColumns.package ? (
        <td className={`${cellSpacing} text-xs font-bold text-slate-700`}>
          {item.package_uom_code
            ? t(
                `uom.${item.package_uom_code}`,
              )
            : t("uom.NONE")}
        </td>
      ) : null}

      {visibleColumns.unitsPerPackage ? (
        <td className={`${cellSpacing} text-xs font-black tabular-nums text-slate-800`}>
          {item.package_uom_code
            ? formatPackageUnits(
                item.units_per_package,
              )
            : "—"}
        </td>
      ) : null}

      {visibleColumns.tracking ? (
        <td className={cellSpacing}>
          <div className="flex max-w-[220px] flex-wrap gap-1">
            <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-1 text-[10px] font-bold leading-4 text-slate-600">
              {t(
                "products.tracking.shortLot",
              )}
              :{" "}
              {t(
                `products.tracking.shortModes.${item.lot_control_mode}`,
              )}
            </span>
            <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-1 text-[10px] font-bold leading-4 text-slate-600">
              {t(
                "products.tracking.shortExpiry",
              )}
              :{" "}
              {t(
                `products.tracking.shortModes.${item.expiry_control_mode}`,
              )}
            </span>
          </div>
        </td>
      ) : null}

      {visibleColumns.lifecycle ? (
        <td className={cellSpacing}>
          <div className="flex flex-col items-start gap-1.5">
            <span
              className={`inline-flex rounded-full px-2 py-1 text-[10px] font-black ring-1 ring-inset ${lifecycleTone}`}
            >
              {t(
                `products.details.lifecycleModes.${item.lifecycle_status}`,
              )}
            </span>
            {item.operational_hold !==
            "NONE" ? (
              <span className="text-[10px] font-black leading-4 text-rose-700">
                {t(
                  `products.details.holdModes.${item.operational_hold}`,
                )}
              </span>
            ) : null}
          </div>
        </td>
      ) : null}

      {visibleColumns.unitBarcode ? (
        <td className={`${cellSpacing} max-w-[180px] break-all font-mono text-[11px] font-bold text-slate-600`}>
          {item.unit_barcode ??
            t(
              "products.details.notSet",
            )}
        </td>
      ) : null}

      {visibleColumns.packageBarcode ? (
        <td className={`${cellSpacing} max-w-[180px] break-all font-mono text-[11px] font-bold text-slate-600`}>
          {item.package_barcode ??
            t(
              "products.details.notSet",
            )}
        </td>
      ) : null}

      {pricingVisible &&
      visibleColumns.packagePrice ? (
        <td className={`${cellSpacing} text-xs font-black tabular-nums text-slate-900`}>
          {item.package_uom_code
            ? `${formatMoney(
                item.package_price,
              )} ${item.currency_code}`
            : "—"}
        </td>
      ) : null}

      {pricingVisible &&
      visibleColumns.unitPrice ? (
        <td className={`${cellSpacing} text-xs font-black tabular-nums text-slate-900`}>
          {formatMoney(
            item.unit_price,
          )}{" "}
          {item.currency_code}
        </td>
      ) : null}

      <td className={`${cellSpacing} w-12 text-center`}>
        <ProductRowActions
          item={item}
          canEditPrice={
            canEditPrice
          }
          canEditTracking={
            canEditTracking
          }
          onOpenDetails={
            onOpenDetails
          }
          onEditPrice={
            onEditPrice
          }
          onEditTracking={
            onEditTracking
          }
        />
      </td>
    </tr>
  );
}
