import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";

type Props = {
  lotControlMode: ProductTrackingMode;
  expiryControlMode: ProductTrackingMode;
  onLotControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode
  ) => void;
  disabled?: boolean;
};

const trackingModes: ProductTrackingMode[] = [
  "NONE",
  "OPTIONAL",
  "REQUIRED",
];

export function ProductTrackingFields({
  lotControlMode,
  expiryControlMode,
  onLotControlModeChange,
  onExpiryControlModeChange,
  disabled = false,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <span className="block text-xs font-black text-slate-700">
          {t("products.tracking.lotLabel")}
        </span>
        <span className="mt-1 block text-[11px] leading-5 text-slate-500">
          {t("products.tracking.lotHelp")}
        </span>
        <select
          value={lotControlMode}
          disabled={disabled}
          onChange={(event) =>
            onLotControlModeChange(
              event.target.value as ProductTrackingMode
            )
          }
          className="mt-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-800 outline-none disabled:opacity-60"
        >
          {trackingModes.map((mode) => (
            <option key={mode} value={mode}>
              {t(
                `products.tracking.lotModes.${mode}`
              )}
            </option>
          ))}
        </select>
        <span className="mt-2 block text-[11px] leading-5 text-slate-500">
          {t("products.tracking.lotExample")}
        </span>
      </label>

      <label className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <span className="block text-xs font-black text-slate-700">
          {t("products.tracking.expiryLabel")}
        </span>
        <span className="mt-1 block text-[11px] leading-5 text-slate-500">
          {t("products.tracking.expiryHelp")}
        </span>
        <select
          value={expiryControlMode}
          disabled={disabled}
          onChange={(event) =>
            onExpiryControlModeChange(
              event.target.value as ProductTrackingMode
            )
          }
          className="mt-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-800 outline-none disabled:opacity-60"
        >
          {trackingModes.map((mode) => (
            <option key={mode} value={mode}>
              {t(
                `products.tracking.expiryModes.${mode}`
              )}
            </option>
          ))}
        </select>
        <span className="mt-2 block text-[11px] leading-5 text-slate-500">
          {t("products.tracking.expiryExample")}
        </span>
      </label>
    </div>
  );
}
