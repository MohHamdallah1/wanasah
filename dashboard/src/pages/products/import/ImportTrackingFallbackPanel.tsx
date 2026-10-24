import {
  AlertCircle,
  CheckCircle2,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import type {
  ProductImportTrackingFallbackAnalysis,
} from "@/pages/products/import/productImportFilePreflight";
import { ProductTrackingSimpleControls } from "@/pages/products/tracking/ProductTrackingSimpleControls";

type Props = {
  analysis: ProductImportTrackingFallbackAnalysis;
  loadingDefaults: boolean;
  defaultsError: boolean;
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  usesCompanyDefaults: boolean;
  onRetryDefaults: () => void;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onResetToCompanyDefaults: () => void;
};

export function ImportTrackingFallbackPanel({
  analysis,
  loadingDefaults,
  defaultsError,
  lotControlMode,
  expiryControlMode,
  usesCompanyDefaults,
  onRetryDefaults,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetToCompanyDefaults,
}: Props) {
  const { t } = useTranslation();

  if (
    analysis.status ===
    "NOT_NEEDED"
  ) {
    return (
      <div
        role="status"
        className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50/70 px-3 py-2.5"
      >
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
        <p className="text-[10px] font-bold leading-4 text-emerald-900">
          {t(
            "products.importTrackingNoFallback",
          )}
        </p>
      </div>
    );
  }

  const unknown =
    analysis.status ===
    "UNKNOWN";

  return (
    <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <div className="min-w-0">
          <p className="text-xs font-black text-amber-950">
            {t(
              unknown
                ? "products.importTrackingFallbackUnknownTitle"
                : "products.importTrackingFallbackNeededTitle",
            )}
          </p>
          <p className="mt-1 text-[10px] font-semibold leading-4 text-amber-900/80">
            {t(
              unknown
                ? "products.importTrackingFallbackUnknownBody"
                : "products.importTrackingFallbackNeededBody",
            )}
          </p>
          {!unknown ? (
            <p className="mt-1 text-[10px] font-black text-amber-900">
              {t(
                "products.importTrackingFallbackCounts",
                {
                  lot:
                    analysis.lotFallbackRows ??
                    0,
                  expiry:
                    analysis.expiryFallbackRows ??
                    0,
                },
              )}
            </p>
          ) : null}
        </div>
      </div>

      {loadingDefaults ? (
        <div
          aria-live="polite"
          className="h-16 animate-pulse rounded-lg bg-white/70"
        >
          <span className="sr-only">
            {t(
              "products.trackingDefaultsLoading",
            )}
          </span>
        </div>
      ) : defaultsError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-white px-3 py-2"
        >
          <span className="text-[10px] font-bold leading-4 text-rose-800">
            {t(
              "products.errors.trackingDefaultsLoad",
            )}
          </span>
          <button
            type="button"
            onClick={onRetryDefaults}
            className="text-[10px] font-black text-rose-800"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : lotControlMode &&
        expiryControlMode ? (
        <>
          <div className="rounded-lg border border-amber-100 bg-white p-3">
            <ProductTrackingSimpleControls
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
            />
          </div>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[10px] font-semibold leading-4 text-amber-950">
              {t(
                usesCompanyDefaults
                  ? "products.importTrackingFallbackUsingCompany"
                  : "products.importTrackingOnlyThisImport",
              )}
            </p>

            {!usesCompanyDefaults ? (
              <button
                type="button"
                onClick={
                  onResetToCompanyDefaults
                }
                className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-white px-2.5 text-[10px] font-black text-slate-700 ring-1 ring-slate-200"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t(
                  "products.importTrackingReset",
                )}
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}
