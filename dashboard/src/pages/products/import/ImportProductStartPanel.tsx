import {
  RotateCcw,
  Settings2,
  Upload,
} from "lucide-react";
import type {
  RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { ImportProductQuickGuide } from "@/pages/products/import/ImportProductQuickGuide";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

type Props = {
  importing: boolean;
  online: boolean;
  file: File | null;
  dragging: boolean;
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  trackingDefaultsLoading: boolean;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  trackingExpanded: boolean;
  fileRef: RefObject<HTMLInputElement | null>;
  onDownloadTemplate: () => void;
  onRetryTrackingDefaults: () => void;
  onExpandTracking: () => void;
  onLotControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onExpiryControlModeChange: (
    value: ProductTrackingMode,
  ) => void;
  onResetTracking: () => void;
  onChooseFile: (
    file: File | null,
  ) => void;
  onDraggingChange: (
    value: boolean,
  ) => void;
  onStartImport: () => void;
};

export function ImportProductStartPanel({
  importing,
  online,
  file,
  dragging,
  lotControlMode,
  expiryControlMode,
  trackingDefaultsLoading,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  trackingExpanded,
  fileRef,
  onDownloadTemplate,
  onRetryTrackingDefaults,
  onExpandTracking,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
  onChooseFile,
  onDraggingChange,
  onStartImport,
}: Props) {
  const { t } = useTranslation();

  const ready =
    Boolean(file) &&
    Boolean(lotControlMode) &&
    Boolean(expiryControlMode) &&
    !trackingDefaultsLoading &&
    !trackingDefaultsError &&
    !importing &&
    online;

  return (
    <div className="space-y-3">
      <ImportProductQuickGuide
        lotControlMode={
          lotControlMode
        }
        expiryControlMode={
          expiryControlMode
        }
        trackingUsesCompanyDefaults={
          trackingUsesCompanyDefaults
        }
        onDownloadTemplate={
          onDownloadTemplate
        }
      />

      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        className="hidden"
        disabled={importing}
        onChange={(event) =>
          onChooseFile(
            event.target.files?.[0] ??
              null,
          )
        }
      />

      <button
        type="button"
        disabled={importing}
        onClick={() => {
          if (!importing) fileRef.current?.click();
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!importing) onDraggingChange(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!importing) onDraggingChange(true);
        }}
        onDragLeave={() =>
          onDraggingChange(false)
        }
        onDrop={(event) => {
          event.preventDefault();
          onDraggingChange(false);
          if (!importing) {
            onChooseFile(event.dataTransfer.files?.[0] ?? null);
          }
        }}
        className={
          "flex min-h-28 w-full items-center gap-3 rounded-xl border border-dashed px-4 py-4 text-start transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:cursor-not-allowed disabled:opacity-50 " +
          (
            dragging
              ? "border-slate-950 bg-slate-100"
              : "border-slate-300 bg-slate-50/70 hover:border-slate-400 hover:bg-white"
          )
        }
      >
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-slate-500 shadow-sm ring-1 ring-slate-200">
          <Upload className="h-5 w-5" />
        </span>
        <span className="min-w-0 flex-1">
          <strong className="block truncate text-sm font-black text-slate-800">
            {file?.name ??
              t(
                "products.dropFile",
              )}
          </strong>
          <span className="mt-1 block text-[10px] font-semibold leading-4 text-slate-400">
            {t(
              "products.importLimit",
            )}
          </span>
        </span>
      </button>

      <section className="rounded-xl border border-slate-200 bg-white p-3">
        {trackingDefaultsLoading ? (
          <div
            aria-live="polite"
            className="h-16 animate-pulse rounded-lg bg-slate-100"
          >
            <span className="sr-only">
              {t(
                "products.trackingDefaultsLoading",
              )}
            </span>
          </div>
        ) : trackingDefaultsError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2"
          >
            <span className="text-[10px] font-bold leading-4 text-rose-800">
              {t(
                "products.errors.trackingDefaultsLoad",
              )}
            </span>
            <button
              type="button"
              onClick={
                onRetryTrackingDefaults
              }
              className="text-[10px] font-black text-rose-800"
            >
              {t(
                "common.retry",
              )}
            </button>
          </div>
        ) : lotControlMode &&
          expiryControlMode ? (
          <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-xs font-black text-slate-900">
                  {t(
                    "products.importTrackingTitle",
                  )}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
                  {t(
                    "products.importTrackingHint",
                  )}
                </p>

                <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-bold text-slate-600">
                  <span className="rounded-md bg-slate-100 px-2 py-1">
                    {t(
                      "products.tracking.shortLot",
                    )}
                    :{" "}
                    {t(
                      `products.tracking.shortModes.${lotControlMode}`,
                    )}
                  </span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">
                    {t(
                      "products.tracking.shortExpiry",
                    )}
                    :{" "}
                    {t(
                      `products.tracking.shortModes.${expiryControlMode}`,
                    )}
                  </span>
                  <span className="text-slate-400">
                    {t(
                      trackingUsesCompanyDefaults
                        ? "products.importTrackingCompanyScope"
                        : "products.importTrackingCustomScope",
                    )}
                  </span>
                </div>
              </div>

              {!trackingExpanded ? (
                <button
                  type="button"
                  onClick={
                    onExpandTracking
                  }
                  className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[10px] font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                >
                  <Settings2 className="h-3.5 w-3.5" />
                  {t(
                    "products.importTrackingChange",
                  )}
                </button>
              ) : null}
            </div>

            {trackingExpanded ? (
              <div className="space-y-2.5 border-t border-slate-100 pt-3">
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
                />

                <div className="flex flex-col gap-2 rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-[10px] font-semibold leading-4 text-amber-950">
                    {t(
                      "products.importTrackingOnlyThisImport",
                    )}
                  </p>

                  {!trackingUsesCompanyDefaults ? (
                    <button
                      type="button"
                      onClick={
                        onResetTracking
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

                <p className="text-[10px] font-semibold leading-4 text-slate-400">
                  {t(
                    "products.importTrackingValueHint",
                    {
                      defaultValue:
                        t(
                          "products.importGuideUseDefault",
                        ),
                      none: t(
                        "products.tracking.importValues.NONE",
                      ),
                      optional: t(
                        "products.tracking.importValues.OPTIONAL",
                      ),
                      required: t(
                        "products.tracking.importValues.REQUIRED",
                      ),
                    },
                  )}
                </p>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <button
        type="button"
        disabled={!ready}
        onClick={onStartImport}
        className="w-full rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-black text-white shadow-sm disabled:cursor-not-allowed disabled:opacity-40"
      >
        {t(
          "products.uploadAndStart",
        )}
      </button>
    </div>
  );
}
