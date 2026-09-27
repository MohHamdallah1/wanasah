import {
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
} from "@/pages/products/create/types";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

type Props = {
  draft: ProductDraft;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  createAdvancedExpanded: boolean;
  createTrackingExpanded: boolean;
  onRetryTrackingDefaults: () => void;
  onToggleAdvanced: () => void;
  onExpandTracking: () => void;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onResetTracking: () => void;
};

export function CreateProductAdvancedSection({
  draft,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  createAdvancedExpanded,
  createTrackingExpanded,
  onRetryTrackingDefaults,
  onToggleAdvanced,
  onExpandTracking,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
}: Props) {
  const { t } = useTranslation();

  const trackingReady =
    Boolean(
      draft.lot_control_mode &&
        draft.expiry_control_mode,
    );

  const handleToggle = () => {
    if (
      !createAdvancedExpanded &&
      trackingReady &&
      !createTrackingExpanded
    ) {
      onExpandTracking();
    }
    onToggleAdvanced();
  };

  return (
    <section className="bg-white">
      <div className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="min-w-0">
          <p className="text-[10px] font-black text-slate-400">
            {t(
              "products.tracking.createTitle"
            )}
          </p>

          {!trackingReady ? (
            trackingDefaultsError ? (
              <button
                type="button"
                onClick={() =>
                  onRetryTrackingDefaults()
                }
                className="mt-1 text-start text-xs font-black text-rose-700"
              >
                {t(
                  "products.errors.trackingDefaultsLoad"
                )}
                {" · "}
                {t("common.retry")}
              </button>
            ) : (
              <p className="mt-1 text-xs font-bold text-slate-500">
                {t(
                  "products.trackingDefaultsLoading"
                )}
              </p>
            )
          ) : (
            <p className="mt-1 text-xs font-black leading-5 text-slate-800">
              {t(
                "products.tracking.createSummary",
                {
                  lot: t(
                    `products.tracking.lotModes.${draft.lot_control_mode}`
                  ),
                  expiry: t(
                    `products.tracking.expiryModes.${draft.expiry_control_mode}`
                  ),
                }
              )}
              <span className="mx-2 text-slate-300">
                ·
              </span>
              <span className="font-semibold text-slate-500">
                {t(
                  trackingUsesCompanyDefaults
                    ? "products.tracking.createCompanyScope"
                    : "products.tracking.createCustomScope"
                )}
              </span>
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={handleToggle}
          aria-expanded={
            createAdvancedExpanded
          }
          disabled={!trackingReady}
          className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 text-[11px] font-black text-slate-700 transition hover:border-slate-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-40"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          {t(
            "products.tracking.createChange"
          )}
          {createAdvancedExpanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          )}
        </button>
      </div>

      {createAdvancedExpanded ? (
        <div className="border-t border-slate-200 bg-slate-50/60 px-4 py-4 sm:px-6">
          <ProductTrackingFields
            lotControlMode={
              draft.lot_control_mode
            }
            expiryControlMode={
              draft.expiry_control_mode
            }
            onLotControlModeChange={
              onLotControlModeChange
            }
            onExpiryControlModeChange={
              onExpiryControlModeChange
            }
          />

          {!trackingUsesCompanyDefaults ? (
            <button
              type="button"
              onClick={onResetTracking}
              className="mt-3 text-[11px] font-black text-slate-600 underline decoration-slate-300 underline-offset-4"
            >
              {t(
                "products.tracking.createReset"
              )}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
