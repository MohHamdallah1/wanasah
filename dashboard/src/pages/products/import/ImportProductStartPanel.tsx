import {
  LoaderCircle,
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
import { ImportTrackingFallbackPanel } from "@/pages/products/import/ImportTrackingFallbackPanel";
import type {
  ProductImportTrackingFallbackAnalysis,
} from "@/pages/products/import/productImportFilePreflight";

type Props = {
  importing: boolean;
  online: boolean;
  file: File | null;
  dragging: boolean;
  filePreflightLoading: boolean;
  trackingAnalysis: ProductImportTrackingFallbackAnalysis | null;
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  trackingDefaultsLoading: boolean;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  fileRef: RefObject<HTMLInputElement | null>;
  onDownloadTemplate: () => void;
  onRetryTrackingDefaults: () => void;
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
  filePreflightLoading,
  trackingAnalysis,
  lotControlMode,
  expiryControlMode,
  trackingDefaultsLoading,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  fileRef,
  onDownloadTemplate,
  onRetryTrackingDefaults,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
  onChooseFile,
  onDraggingChange,
  onStartImport,
}: Props) {
  const { t } = useTranslation();

  const fallbackRequired =
    Boolean(file) &&
    Boolean(
      trackingAnalysis &&
        trackingAnalysis.status !==
          "NOT_NEEDED",
    );

  const trackingReady =
    !fallbackRequired ||
    (
      Boolean(lotControlMode) &&
      Boolean(expiryControlMode) &&
      !trackingDefaultsLoading &&
      !trackingDefaultsError
    );

  const ready =
    Boolean(file) &&
    !filePreflightLoading &&
    trackingReady &&
    !importing &&
    online;

  return (
    <div className="space-y-3">
      <ImportProductQuickGuide
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
          if (!importing) {
            fileRef.current?.click();
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!importing) {
            onDraggingChange(true);
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!importing) {
            onDraggingChange(true);
          }
        }}
        onDragLeave={() =>
          onDraggingChange(false)
        }
        onDrop={(event) => {
          event.preventDefault();
          onDraggingChange(false);
          if (!importing) {
            onChooseFile(
              event.dataTransfer
                .files?.[0] ?? null,
            );
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

      {file &&
      filePreflightLoading ? (
        <div
          aria-live="polite"
          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5"
        >
          <LoaderCircle className="h-4 w-4 animate-spin text-slate-500" />
          <p className="text-[10px] font-bold text-slate-600">
            {t(
              "products.importTrackingInspectingFile",
            )}
          </p>
        </div>
      ) : file &&
        trackingAnalysis ? (
        <ImportTrackingFallbackPanel
          analysis={
            trackingAnalysis
          }
          loadingDefaults={
            trackingDefaultsLoading
          }
          defaultsError={
            trackingDefaultsError
          }
          lotControlMode={
            lotControlMode
          }
          expiryControlMode={
            expiryControlMode
          }
          usesCompanyDefaults={
            trackingUsesCompanyDefaults
          }
          onRetryDefaults={
            onRetryTrackingDefaults
          }
          onLotControlModeChange={
            onLotControlModeChange
          }
          onExpiryControlModeChange={
            onExpiryControlModeChange
          }
          onResetToCompanyDefaults={
            onResetTracking
          }
        />
      ) : null}

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
