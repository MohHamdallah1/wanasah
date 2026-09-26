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
  canReassignFamily: boolean;
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
  onReassignFamily: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
};

type FactProps = {
  label: string;
  value: string;
  mono?: boolean;
};

function MobileFact({
  label,
  value,
  mono = false,
}: FactProps) {
  return (
    <div className="min-w-0">
      <dt className="text-[9px] font-black leading-4 text-slate-400">
        {label}
      </dt>
      <dd
        className={`mt-0.5 break-words text-[11px] font-black leading-5 text-slate-800 ${
          mono
            ? "break-all font-mono"
            : ""
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

export function ProductMobileCard({
  item,
  pricingVisible,
  canEditPrice,
  canReassignFamily,
  canEditTracking,
  columns,
  density =
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.density,
  onOpenDetails,
  onEditPrice,
  onReassignFamily,
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
      : "p-3.5";

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
    item.units_per_package === null
      ? "—"
      : formatLocaleDecimal(
          String(
            item.units_per_package,
          ),
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

  const packageLabel =
    item.package_uom_code
      ? t(
          `uom.${item.package_uom_code}`,
        )
      : t("uom.NONE");

  return (
    <article
      className={`border-b border-slate-100 bg-white last:border-b-0 ${cardSpacing}`}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() =>
            onOpenDetails(item)
          }
          aria-label={t(
            "products.details.open",
          )}
          className="min-w-0 flex-1 text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <h3 className="break-words text-[13px] font-black leading-5 text-slate-950">
            {item.name}
          </h3>

          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
            {item.family_name !==
            item.name ? (
              <span className="break-words text-[10px] font-bold leading-4 text-slate-500">
                {item.family_name}
              </span>
            ) : null}
            <span
              aria-hidden="true"
              className="text-slate-300"
            >
              ·
            </span>
            <span className="break-all font-mono text-[9px] font-semibold leading-4 text-slate-400">
              {item.sku}
            </span>
          </div>
        </button>

        <ProductRowActions
          item={item}
          canEditPrice={
            canEditPrice
          }
          canReassignFamily={
            canReassignFamily
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
          onReassignFamily={
            onReassignFamily
          }
          onEditTracking={
            onEditTracking
          }
        />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {visibleColumns.lifecycle ? (
          <span
            className={`inline-flex rounded-full px-2 py-1 text-[9px] font-black ring-1 ring-inset ${lifecycleTone}`}
          >
            {t(
              `products.details.lifecycleModes.${item.lifecycle_status}`,
            )}
          </span>
        ) : null}

        {visibleColumns.lifecycle &&
        item.operational_hold !==
          "NONE" ? (
          <span className="inline-flex rounded-full bg-rose-50 px-2 py-1 text-[9px] font-black text-rose-700 ring-1 ring-inset ring-rose-200">
            {t(
              `products.details.holdModes.${item.operational_hold}`,
            )}
          </span>
        ) : null}

        {visibleColumns.tracking ? (
          <>
            <span className="inline-flex rounded-md bg-slate-100 px-1.5 py-1 text-[9px] font-bold text-slate-600">
              {t(
                "products.tracking.shortLot",
              )}
              :{" "}
              {t(
                `products.tracking.shortModes.${item.lot_control_mode}`,
              )}
            </span>
            <span className="inline-flex rounded-md bg-slate-100 px-1.5 py-1 text-[9px] font-bold text-slate-600">
              {t(
                "products.tracking.shortExpiry",
              )}
              :{" "}
              {t(
                `products.tracking.shortModes.${item.expiry_control_mode}`,
              )}
            </span>
          </>
        ) : null}
      </div>

      {(visibleColumns.package ||
        visibleColumns.unitsPerPackage ||
        visibleColumns.unitBarcode ||
        visibleColumns.packageBarcode) ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-slate-100 pt-2.5">
          {visibleColumns.package ? (
            <MobileFact
              label={t(
                "products.columns.package",
              )}
              value={packageLabel}
            />
          ) : null}

          {visibleColumns.unitsPerPackage ? (
            <MobileFact
              label={t(
                "products.columns.unitsPerPackage",
              )}
              value={
                item.package_uom_code
                  ? units
                  : "—"
              }
            />
          ) : null}

          {visibleColumns.unitBarcode ? (
            <MobileFact
              label={t(
                "products.columns.unitBarcode",
              )}
              value={
                item.unit_barcode ??
                t(
                  "products.details.notSet",
                )
              }
              mono
            />
          ) : null}

          {visibleColumns.packageBarcode ? (
            <MobileFact
              label={t(
                "products.columns.packageBarcode",
              )}
              value={
                item.package_barcode ??
                t(
                  "products.details.notSet",
                )
              }
              mono
            />
          ) : null}
        </dl>
      ) : null}

      {pricingVisible &&
      (visibleColumns.packagePrice ||
        visibleColumns.unitPrice) ? (
        <dl className="mt-2.5 grid grid-cols-2 gap-x-4 border-t border-slate-100 pt-2.5">
          {visibleColumns.packagePrice ? (
            <MobileFact
              label={t(
                "products.columns.packagePrice",
              )}
              value={
                item.package_uom_code
                  ? `${money(
                      item.package_price,
                    )} ${item.currency_code}`
                  : "—"
              }
            />
          ) : null}

          {visibleColumns.unitPrice ? (
            <MobileFact
              label={t(
                "products.columns.unitPrice",
              )}
              value={`${money(
                item.unit_price,
              )} ${item.currency_code}`}
            />
          ) : null}
        </dl>
      ) : null}
    </article>
  );
}
