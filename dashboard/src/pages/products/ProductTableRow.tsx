import { useTranslation } from "react-i18next";

import {
  resolveI18nLocale,
} from "@/lib/locale";
import {
  formatLocaleDecimal,
} from "@/lib/localeNumbers";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  item: SimpleProduct;
  pricingVisible: boolean;
  canEditPrice: boolean;
  canEditTracking: boolean;
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
  onOpenDetails,
  onEditPrice,
  onEditTracking,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const locale =
    resolveI18nLocale(i18n);

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

  return (
    <tr className="bg-white hover:bg-slate-50/70">
      <td className="px-5 py-4">
        <div className="font-black text-slate-900">
          {item.name}
        </div>
        {item.family_name !==
        item.name ? (
          <div className="mt-1 text-[10px] font-bold text-slate-400">
            {item.family_name}
          </div>
        ) : null}
        <div className="mt-1 text-[10px] font-bold text-slate-400">
          {t(
            "products.fields.sku",
          )}
          : {item.sku}
        </div>
      </td>

      <td className="px-5 py-4 font-bold">
        {item.package_uom_code
          ? t(
              `uom.${item.package_uom_code}`,
            )
          : t("uom.NONE")}
      </td>

      <td className="px-5 py-4 font-black tabular-nums">
        {item.package_uom_code
          ? formatPackageUnits(
              item.units_per_package,
            )
          : "—"}
      </td>

      <td className="px-5 py-4">
        <div className="flex flex-col gap-1 text-[10px] font-bold text-slate-500">
          <span>
            {t(
              "products.tracking.shortLot",
            )}
            :{" "}
            {t(
              `products.tracking.shortModes.${item.lot_control_mode}`,
            )}
          </span>
          <span>
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

      {pricingVisible ? (
        <>
          <td className="px-5 py-4 font-black tabular-nums">
            {item.package_uom_code
              ? `${formatMoney(
                  item.package_price,
                )} ${item.currency_code}`
              : "—"}
          </td>

          <td className="px-5 py-4 font-black tabular-nums">
            {formatMoney(
              item.unit_price,
            )}{" "}
            {item.currency_code}
          </td>
        </>
      ) : null}

      <td className="px-5 py-4">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() =>
              onOpenDetails(item)
            }
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50"
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
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50"
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
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50"
            >
              {t(
                "products.trackingEditor.action",
              )}
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}
