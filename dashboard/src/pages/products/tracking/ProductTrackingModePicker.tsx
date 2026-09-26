import type {
  LucideIcon,
} from "lucide-react";
import {
  Boxes,
  CalendarClock,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";

type TrackingKind = "lot" | "expiry";

type Props = {
  kind: TrackingKind;
  value: ProductTrackingMode;
  disabled?: boolean;
  onChange: (
    value: ProductTrackingMode,
  ) => void;
};

const trackingModes: ProductTrackingMode[] = [
  "NONE",
  "OPTIONAL",
  "REQUIRED",
];

const trackingIcon: Record<
  TrackingKind,
  LucideIcon
> = {
  lot: Boxes,
  expiry: CalendarClock,
};

export function ProductTrackingModePicker({
  kind,
  value,
  disabled = false,
  onChange,
}: Props) {
  const { t } = useTranslation();
  const Icon = trackingIcon[kind];
  const labelKey =
    kind === "lot"
      ? "products.tracking.lotLabel"
      : "products.tracking.expiryLabel";
  const helpKey =
    kind === "lot"
      ? "products.tracking.lotHelp"
      : "products.tracking.expiryHelp";
  const exampleKey =
    kind === "lot"
      ? "products.tracking.lotExample"
      : "products.tracking.expiryExample";
  const modeFamily =
    kind === "lot"
      ? "products.tracking.lotModes"
      : "products.tracking.expiryModes";

  return (
    <fieldset
      disabled={disabled}
      className="min-w-0 rounded-xl border border-slate-200 bg-white p-3"
    >
      <legend className="sr-only">
        {t(labelKey)}
      </legend>

      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-black leading-5 text-slate-900">
            {t(labelKey)}
          </p>
          <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
            {t(helpKey)}
          </p>
        </div>
      </div>

      <div
        role="radiogroup"
        aria-label={t(labelKey)}
        className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1"
      >
        {trackingModes.map((mode) => {
          const selected =
            value === mode;

          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() =>
                onChange(mode)
              }
              className={`min-h-9 rounded-md px-2 text-[10px] font-black leading-4 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:cursor-not-allowed disabled:opacity-60 ${
                selected
                  ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200"
                  : "text-slate-500 hover:bg-white/70 hover:text-slate-800"
              }`}
            >
              {t(
                `products.tracking.shortModes.${mode}`,
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-2.5 rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-2">
        <p className="text-[10px] font-bold leading-4 text-slate-700">
          {t(
            `${modeFamily}.${value}`,
          )}
        </p>
        <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-400">
          {t(exampleKey)}
        </p>
      </div>
    </fieldset>
  );
}
