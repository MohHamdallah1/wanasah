import {
  ChevronDown,
  ChevronUp,
  Copy,
  Settings2,
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
  onUnitBarcodeChange: (value: string) => void;
  onCopyBarcode: () => void;
  onPackageBarcodeChange: (value: string) => void;
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
  onUnitBarcodeChange,
  onCopyBarcode,
  onPackageBarcodeChange,
}: Props) {
  const { t } = useTranslation();

  const trackingReady =
    Boolean(
      draft.lot_control_mode &&
        draft.expiry_control_mode,
    );

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-black uppercase tracking-[0.16em] text-slate-400">
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
            <>
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
              </p>
              <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
                {t(
                  trackingUsesCompanyDefaults
                    ? "products.tracking.createCompanyScope"
                    : "products.tracking.createCustomScope"
                )}
              </p>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={onToggleAdvanced}
          aria-expanded={
            createAdvancedExpanded
          }
          className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <Settings2 className="h-3.5 w-3.5" />
          {t(
            "products.quickCreate.advancedTitle"
          )}
          {createAdvancedExpanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          )}
        </button>
      </div>

      {createAdvancedExpanded ? (
        <div className="grid gap-5 px-4 py-4 lg:grid-cols-2">
          <div className="min-w-0">
            <div className="mb-3">
              <h4 className="text-xs font-black text-slate-900">
                {t(
                  "products.tracking.createTitle"
                )}
              </h4>
              <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
                {t(
                  "products.tracking.createOnlyThisProduct"
                )}
              </p>
            </div>

            {!createTrackingExpanded ? (
              <button
                type="button"
                onClick={onExpandTracking}
                disabled={!trackingReady}
                className="inline-flex min-h-9 items-center rounded-xl border border-slate-200 bg-slate-50 px-3 text-[11px] font-black text-slate-700 transition hover:bg-white disabled:opacity-40"
              >
                {t(
                  "products.tracking.createChange"
                )}
              </button>
            ) : (
              <div className="space-y-3">
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
                    className="text-[11px] font-black text-slate-600 underline decoration-slate-300 underline-offset-4"
                  >
                    {t(
                      "products.tracking.createReset"
                    )}
                  </button>
                ) : null}
              </div>
            )}
          </div>

          <div className="min-w-0 border-t border-slate-100 pt-4 lg:border-s lg:border-t-0 lg:ps-5 lg:pt-0">
            <div className="mb-3">
              <h4 className="text-xs font-black text-slate-900">
                {t(
                  "products.barcodeSection"
                )}
              </h4>
              <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
                {t(
                  "products.quickCreate.advancedHint"
                )}
              </p>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-bold text-slate-500">
                {t(
                  "products.unitBarcode"
                )}
                <input
                  value={
                    draft.unit_barcode
                  }
                  onChange={(event) =>
                    onUnitBarcodeChange(
                      event.target.value
                    )
                  }
                  className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                />
              </label>

              {draft.has_package ? (
                <label className="block text-xs font-bold text-slate-500">
                  <span className="flex items-center justify-between gap-2">
                    <span>
                      {t(
                        "products.packageBarcode"
                      )}
                    </span>
                    <button
                      type="button"
                      disabled={
                        !draft.unit_barcode.trim()
                      }
                      onClick={onCopyBarcode}
                      title={t(
                        "products.copyBarcode"
                      )}
                      className="inline-flex items-center gap-1 text-[10px] font-black text-slate-500 transition hover:text-slate-900 disabled:opacity-30"
                    >
                      <Copy className="h-3 w-3" />
                      {t(
                        "products.copyBarcode"
                      )}
                    </button>
                  </span>
                  <input
                    value={
                      draft.package_barcode
                    }
                    onChange={(event) =>
                      onPackageBarcodeChange(
                        event.target.value
                      )
                    }
                    className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                  />
                </label>
              ) : null}
            </div>
          </div>

          <p className="lg:col-span-2 border-t border-slate-100 pt-3 text-[10px] font-semibold leading-4 text-slate-400">
            {t(
              "products.quickCreate.systemManagedHint"
            )}
          </p>
        </div>
      ) : null}
    </section>
  );
}
