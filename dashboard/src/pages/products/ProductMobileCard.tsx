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

export function ProductMobileCard({
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
  const cardSpacing =
    density === "compact"
      ? "p-3"
      : "p-4";

  const money = (
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

  const units =
    item.units_per_package ===
    null
      ? "—"
      : formatLocaleDecimal(
          String(
            item.units_per_package,
          ),
          locale,
          0,
          0,
        );

  return (
    <article className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${cardSpacing}`}>
      <div className="min-w-0">
        <h3 className="break-words text-sm font-black text-slate-950">
          {item.name}
        </h3>
        {item.family_name !==
        item.name ? (
          <p className="mt-1 break-words text-[11px] font-bold text-slate-500">
            {item.family_name}
          </p>
        ) : null}
        <p className="mt-1 break-all font-mono text-[11px] font-bold text-slate-400">
          {t(
            "products.fields.sku",
          )}
          : {item.sku}
        </p>
      </div>

      <dl
        className={
          density === "compact"
            ? "mt-3 grid grid-cols-2 gap-x-3 gap-y-3"
            : "mt-4 grid grid-cols-2 gap-x-3 gap-y-4"
        }
      >
        {visibleColumns.package ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.package",
              )}
            </dt>
            <dd className="mt-1 break-words text-xs font-black text-slate-800">
              {item.package_uom_code
                ? t(
                    `uom.${item.package_uom_code}`,
                  )
                : t("uom.NONE")}
            </dd>
          </div>
        ) : null}

        {visibleColumns.unitsPerPackage ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.unitsPerPackage",
              )}
            </dt>
            <dd className="mt-1 text-xs font-black tabular-nums text-slate-800">
              {item.package_uom_code
                ? units
                : "—"}
            </dd>
          </div>
        ) : null}

        {visibleColumns.tracking ? (
          <div className="col-span-2 min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.tracking",
              )}
            </dt>
            <dd className="mt-1 grid grid-cols-1 gap-1 text-[11px] font-bold text-slate-600 min-[360px]:grid-cols-2">
              <span className="break-words">
                {t(
                  "products.tracking.shortLot",
                )}
                :{" "}
                {t(
                  `products.tracking.shortModes.${item.lot_control_mode}`,
                )}
              </span>
              <span className="break-words">
                {t(
                  "products.tracking.shortExpiry",
                )}
                :{" "}
                {t(
                  `products.tracking.shortModes.${item.expiry_control_mode}`,
                )}
              </span>
            </dd>
          </div>
        ) : null}

        {visibleColumns.lifecycle ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.lifecycle",
              )}
            </dt>
            <dd className="mt-1 flex flex-col gap-1 break-words text-xs font-black text-slate-800">
              <span>
                {t(
                  `products.details.lifecycleModes.${item.lifecycle_status}`,
                )}
              </span>
              {item.operational_hold !==
              "NONE" ? (
                <span className="text-[10px] text-rose-700">
                  {t(
                    `products.details.holdModes.${item.operational_hold}`,
                  )}
                </span>
              ) : null}
            </dd>
          </div>
        ) : null}

        {visibleColumns.unitBarcode ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.unitBarcode",
              )}
            </dt>
            <dd className="mt-1 break-all font-mono text-xs font-bold text-slate-700">
              {item.unit_barcode ??
                t(
                  "products.details.notSet",
                )}
            </dd>
          </div>
        ) : null}

        {visibleColumns.packageBarcode ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.packageBarcode",
              )}
            </dt>
            <dd className="mt-1 break-all font-mono text-xs font-bold text-slate-700">
              {item.package_barcode ??
                t(
                  "products.details.notSet",
                )}
            </dd>
          </div>
        ) : null}

        {pricingVisible &&
        visibleColumns.packagePrice ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.packagePrice",
              )}
            </dt>
            <dd className="mt-1 break-words text-xs font-black tabular-nums text-slate-800">
              {item.package_uom_code
                ? `${money(
                    item.package_price,
                  )} ${item.currency_code}`
                : "—"}
            </dd>
          </div>
        ) : null}

        {pricingVisible &&
        visibleColumns.unitPrice ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-black text-slate-400">
              {t(
                "products.columns.unitPrice",
              )}
            </dt>
            <dd className="mt-1 break-words text-xs font-black tabular-nums text-slate-800">
              {money(
                item.unit_price,
              )}{" "}
              {item.currency_code}
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-4 grid grid-cols-1 gap-2 min-[360px]:grid-cols-2">
        <button
          type="button"
          onClick={() =>
            onOpenDetails(item)
          }
          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-black text-slate-700 hover:bg-slate-50"
        >
          {t(
            "products.details.open",
          )}
        </button>

        {canEditPrice &&
        item.simple_compatible ? (
          <button
            type="button"
            onClick={() =>
              onEditPrice(item)
            }
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-black text-slate-700 hover:bg-slate-50"
          >
            {t(
              "products.editPrice",
            )}
          </button>
        ) : null}

        {canEditTracking ? (
          <button
            type="button"
            onClick={() =>
              onEditTracking(item)
            }
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-black text-slate-700 hover:bg-slate-50 min-[360px]:col-span-2"
          >
            {t(
              "products.trackingEditor.action",
            )}
          </button>
        ) : null}
      </div>
    </article>
  );
}
