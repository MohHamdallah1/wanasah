import {
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
} from "lucide-react";
import {
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

type Props = {
  lotControlMode: ProductTrackingMode;
  expiryControlMode: ProductTrackingMode;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  disabled?: boolean;
};

type RequirementToggleProps = {
  label: string;
  mode: ProductTrackingMode;
  disabled: boolean;
  onChange: (
    value: ProductTrackingMode,
  ) => void;
};

function RequirementToggle({
  label,
  mode,
  disabled,
  onChange,
}: RequirementToggleProps) {
  const { t } = useTranslation();
  const required =
    mode === "REQUIRED";

  const statusKey =
    mode === "NONE"
      ? "products.tracking.simple.notUsed"
      : required
        ? "products.tracking.simple.required"
        : "products.tracking.simple.optional";

  return (
    <div className="flex min-h-14 items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5">
      <div className="min-w-0">
        <p className="text-xs font-black text-slate-900">
          {label}
        </p>
        <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
          {t(statusKey)}
        </p>
      </div>

      <button
        type="button"
        role="switch"
        aria-checked={required}
        disabled={disabled}
        onClick={() =>
          onChange(
            required
              ? "OPTIONAL"
              : "REQUIRED",
          )
        }
        className={
          "flex h-7 w-12 shrink-0 items-center rounded-full p-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:cursor-not-allowed disabled:opacity-50 " +
          (
            required
              ? "justify-end bg-slate-950"
              : "justify-start bg-slate-200"
          )
        }
      >
        <span className="h-5 w-5 rounded-full bg-white shadow-sm transition-all" />
        <span className="sr-only">
          {label}
        </span>
      </button>
    </div>
  );
}

export function ProductTrackingSimpleControls({
  lotControlMode,
  expiryControlMode,
  onLotControlModeChange,
  onExpiryControlModeChange,
  disabled = false,
}: Props) {
  const { t } = useTranslation();
  const [
    advancedOpen,
    setAdvancedOpen,
  ] = useState(false);

  return (
    <div className="space-y-3">
      <div className="grid gap-2.5 lg:grid-cols-2">
        <RequirementToggle
          label={t(
            "products.tracking.simple.lotRequired",
          )}
          mode={lotControlMode}
          disabled={disabled}
          onChange={
            onLotControlModeChange
          }
        />

        <RequirementToggle
          label={t(
            "products.tracking.simple.expiryRequired",
          )}
          mode={expiryControlMode}
          disabled={disabled}
          onChange={
            onExpiryControlModeChange
          }
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-2.5">
        <button
          type="button"
          aria-expanded={advancedOpen}
          disabled={disabled}
          onClick={() =>
            setAdvancedOpen(
              (current) => !current,
            )
          }
          className="flex min-h-9 w-full items-center justify-between gap-3 rounded-lg px-2 text-start text-[11px] font-black text-slate-700 transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5 text-slate-400" />
            {t(
              "products.tracking.simple.advanced",
            )}
          </span>
          {advancedOpen ? (
            <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          )}
        </button>

        {advancedOpen ? (
          <div className="border-t border-slate-200 px-1 pt-3">
            <p className="mb-2.5 px-1 text-[10px] font-semibold leading-4 text-slate-500">
              {t(
                "products.tracking.simple.advancedHint",
              )}
            </p>
            <ProductTrackingFields
              lotControlMode={
                lotControlMode
              }
              expiryControlMode={
                expiryControlMode
              }
              onLotControlModeChange={
                onLotControlModeChange
              }
              onExpiryControlModeChange={
                onExpiryControlModeChange
              }
              disabled={disabled}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
