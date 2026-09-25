import type {
  RefObject,
} from "react";
import {
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  ProductImportState,
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { ProductTrackingFields } from "@/pages/products/tracking/ProductTrackingFields";

const importMappingFields = [
  "name",
  "family",
  "package_uom",
  "units_per_package",
  "package_price",
  "unit_price",
  "unit_barcode",
  "package_barcode",
  "lot_control_mode",
  "expiry_control_mode",
] as const;

const mappingLabelKey = (
  field:
    (typeof importMappingFields)[number],
) => {
  const keys = {
    name: "products.fields.name",
    family: "products.fields.family",
    package_uom:
      "products.fields.packageUom",
    units_per_package:
      "products.fields.unitsPerPackage",
    package_price:
      "products.fields.packagePrice",
    unit_price:
      "products.fields.unitPrice",
    unit_barcode:
      "products.fields.unitBarcode",
    package_barcode:
      "products.fields.packageBarcode",
    lot_control_mode:
      "products.fields.lotControlMode",
    expiry_control_mode:
      "products.fields.expiryControlMode",
  } as const;
  return keys[field];
};

type Props = {
  open: boolean;
  importing: boolean;
  online: boolean;
  jobId: string | null;
  status: ProductImportState | null;
  pollError: string | null;
  mapping: Record<string, string>;
  progress: number;
  file: File | null;
  dragging: boolean;
  lotControlMode: ProductTrackingMode | null;
  expiryControlMode: ProductTrackingMode | null;
  trackingDefaultsLoading: boolean;
  trackingDefaultsError: boolean;
  trackingUsesCompanyDefaults: boolean;
  trackingExpanded: boolean;
  mappingPending: boolean;
  retryPending: boolean;
  fileRef: RefObject<HTMLInputElement | null>;
  onClose: () => void;
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
  onRetryPoll: () => void;
  onMappingChange: (
    field:
      (typeof importMappingFields)[number],
    value: string,
  ) => void;
  onSubmitMapping: () => void;
  onDownloadErrorReport: () => void;
  onResetImport: () => void;
  onRetryImport: () => void;
  onCompletedClose: () => void;
};

export function ImportProductModal({
  open,
  importing,
  online,
  jobId,
  status,
  pollError,
  mapping,
  progress,
  file,
  dragging,
  lotControlMode,
  expiryControlMode,
  trackingDefaultsLoading,
  trackingDefaultsError,
  trackingUsesCompanyDefaults,
  trackingExpanded,
  mappingPending,
  retryPending,
  fileRef,
  onClose,
  onDownloadTemplate,
  onRetryTrackingDefaults,
  onExpandTracking,
  onLotControlModeChange,
  onExpiryControlModeChange,
  onResetTracking,
  onChooseFile,
  onDraggingChange,
  onStartImport,
  onRetryPoll,
  onMappingChange,
  onSubmitMapping,
  onDownloadErrorReport,
  onResetImport,
  onRetryImport,
  onCompletedClose,
}: Props) {
  const { t, i18n } =
    useTranslation();

  return (
    <Modal
        isOpen={open}
        onClose={onClose}
                title={t(
          "products.importTitle"
        )}
        maxWidth="max-w-2xl"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sky-50 p-3">
            <p className="text-xs font-bold leading-6 text-sky-900">
              {t(
                "products.importIntro"
              )}
            </p>
            <button
              type="button"
              onClick={onDownloadTemplate}
              className="rounded-xl bg-white px-3 py-2 text-xs font-black text-sky-900 shadow-sm"
            >
              {t(
                "products.downloadTemplate"
              )}
            </button>
          </div>

          {!jobId ? (
            <>
              <div className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="mb-3">
                  <h3 className="text-sm font-black text-slate-900">
                    {t(
                      "products.importTrackingTitle"
                    )}
                  </h3>
                  <p className="mt-1 text-xs leading-6 text-slate-500">
                    {t(
                      "products.importTrackingHint"
                    )}
                  </p>
                </div>

                {trackingDefaultsLoading ? (
                  <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                    {t(
                      "products.trackingDefaultsLoading"
                    )}
                  </div>
                ) : trackingDefaultsError ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
                    <span className="text-xs font-bold text-rose-800">
                      {t(
                        "products.errors.trackingDefaultsLoad"
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        onRetryTrackingDefaults()
                      }
                      className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                    >
                      {t(
                        "common.retry"
                      )}
                    </button>
                  </div>
                ) : lotControlMode &&
                  expiryControlMode ? (
                  <div className="space-y-3">
                    <div className="rounded-xl bg-slate-50 p-3">
                      <p className="text-xs font-black leading-6 text-slate-800">
                        {t(
                          "products.importTrackingSummary",
                          {
                            lot: t(
                              `products.tracking.lotModes.${lotControlMode}`
                            ),
                            expiry: t(
                              `products.tracking.expiryModes.${expiryControlMode}`
                            ),
                          }
                        )}
                      </p>
                      <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                        {t(
                          trackingUsesCompanyDefaults
                            ? "products.importTrackingCompanyScope"
                            : "products.importTrackingCustomScope"
                        )}
                      </p>
                    </div>

                    {!trackingExpanded ? (
                      <button
                        type="button"
                        onClick={onExpandTracking}
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                      >
                        {t(
                          "products.importTrackingChange"
                        )}
                      </button>
                    ) : (
                      <div className="space-y-3">
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

                        <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
                          {t(
                            "products.importTrackingOnlyThisImport"
                          )}
                        </p>

                        {!trackingUsesCompanyDefaults ? (
                          <button
                            type="button"
                            onClick={onResetTracking}
                            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                          >
                            {t(
                              "products.importTrackingReset"
                            )}
                          </button>
                        ) : null}

                        <p className="text-[11px] leading-5 text-slate-500">
                          {t(
                            "products.importTrackingOverrideHint"
                          )}
                        </p>
                        <p className="text-[11px] leading-5 text-slate-500">
                          {t(
                            "products.importTrackingValueHint",
                            {
                              none: t(
                                "products.tracking.importValues.NONE"
                              ),
                              optional: t(
                                "products.tracking.importValues.OPTIONAL"
                              ),
                              required: t(
                                "products.tracking.importValues.REQUIRED"
                              ),
                            }
                          )}
                        </p>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>

              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="hidden"
                onChange={(
                  event
                ) =>
                  onChooseFile(
                    event.target.files?.[0] ??
                      null
                  )
                }
              />

              <button
                type="button"
                onClick={() =>
                  fileRef.current?.click()
                }
                onDragEnter={(event) => {
                  event.preventDefault();
                  onDraggingChange(true);
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  onDraggingChange(true);
                }}
                onDragLeave={() =>
                  onDraggingChange(false)
                }
                onDrop={(
                  event
                ) => {
                  event.preventDefault();
                  onDraggingChange(false);
                  onChooseFile(
                    event.dataTransfer
                      .files?.[0] ??
                      null
                  );
                }}
                className={`flex min-h-48 w-full flex-col items-center justify-center rounded-[24px] border border-dashed text-center transition ${
                  dragging
                    ? "border-slate-950 bg-slate-100"
                    : "border-slate-300 bg-slate-50 hover:bg-white"
                }`}
              >
                <Upload className="mb-3 h-8 w-8 text-slate-400" />
                <strong className="text-sm text-slate-700">
                  {file?.name ??
                    t(
                      "products.dropFile"
                    )}
                </strong>
                <span className="mt-1 text-xs text-slate-400">
                  {t(
                    "products.importLimit"
                  )}
                </span>
              </button>

              <button
                type="button"
                disabled={
                  !file ||
                  !lotControlMode ||
                  !expiryControlMode ||
                  trackingDefaultsLoading ||
                  trackingDefaultsError ||
                  importing ||
                  !online
                }
                onClick={onStartImport}
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
              >
                {t(
                  "products.uploadAndStart"
                )}
              </button>
            </>
          ) : null}

          {jobId &&
          pollError ? (
            <div
              role="alert"
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-rose-50 p-4"
            >
              <span className="text-xs font-bold leading-6 text-rose-800">
                {pollError}
              </span>
              <button
                type="button"
                onClick={onRetryPoll}
                className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
              >
                {t(
                  "common.retry"
                )}
              </button>
            </div>
          ) : null}

          {jobId &&
          !status ? (
            <div className="rounded-2xl bg-slate-50 p-5 text-center text-sm font-black text-slate-600">
              {t(
                "products.queued"
              )}
            </div>
          ) : null}

          {status?.status ===
          "NEEDS_MAPPING" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
                {t(
                  "products.mappingIntro"
                )}
              </div>

              {importMappingFields.map(
                (field) => (
                  <label
                    key={field}
                    className="grid gap-2 text-xs font-black text-slate-600 sm:grid-cols-[180px_1fr] sm:items-center"
                  >
                    <span>
                      {t(
                        mappingLabelKey(
                          field
                        )
                      )}
                    </span>
                    <select
                      value={
                        mapping[
                          field
                        ] ?? ""
                      }
                      onChange={(event) =>
                        onMappingChange(
                          field,
                          event.target.value
                        )
                      }
                      className="rounded-xl border border-slate-200 bg-white p-2.5"
                    >
                      <option value="">
                        {t(
                          "products.unmapped"
                        )}
                      </option>
                      {status.detected_headers.map(
                        (
                          header
                        ) => (
                          <option
                            key={
                              header
                            }
                            value={
                              header
                            }
                          >
                            {
                              header
                            }
                          </option>
                        )
                      )}
                    </select>
                  </label>
                )
              )}

              <button
                type="button"
                disabled={
                  mappingPending ||
                  !online
                }
                onClick={onSubmitMapping}
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
              >
                {t(
                  "products.continueImport"
                )}
              </button>
            </div>
          ) : null}

          {status &&
          ![
            "NEEDS_MAPPING",
            "VALIDATION_FAILED",
            "FAILED",
            "COMPLETED",
          ].includes(
            status.status
          ) ? (
            <div className="rounded-[22px] border border-slate-200 p-4">
              <div className="flex items-center justify-between text-xs font-black">
                <span>
                  {status.status ===
                  "IMPORTING"
                    ? t(
                        "products.importingProducts"
                      )
                    : t(
                        "products.preparingImport"
                      )}
                </span>
                <span>
                  {
                    status.processed_rows
                  }{" "}
                  /{" "}
                  {status.valid_rows ||
                    status.total_rows}
                </span>
              </div>

              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-slate-950 transition-all"
                  style={{
                    width: `${progress}%`,
                  }}
                />
              </div>
              <p className="mt-3 text-[11px] text-slate-500">
                {t(
                  "products.backgroundHint"
                )}
              </p>
            </div>
          ) : null}

          {status?.status ===
          "VALIDATION_FAILED" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-900">
                {t(
                  "products.validationFailed",
                  {
                    count:
                      status.failed_rows,
                  }
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!online}
                  onClick={onDownloadErrorReport}
                  className="rounded-xl border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800 disabled:opacity-40"
                >
                  {t(
                    "products.downloadErrors"
                  )}
                </button>
                <button
                  type="button"
                  onClick={onResetImport}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                >
                  {t(
                    "products.newImport"
                  )}
                </button>
              </div>

              <div className="max-h-64 overflow-auto rounded-xl border">
                {status.errors.map(
                  (error) => {
                    const key =
                      error.code
                        ? `errors.codes.${error.code}`
                        : "";
                    const message =
                      key &&
                      i18n.exists(
                        key
                      )
                        ? t(key)
                        : t(
                            "network.serverError"
                          );
                    return (
                      <div
                        key={`${error.row_number}-${error.code}`}
                        className="border-b p-3 text-xs last:border-b-0"
                      >
                        <strong>
                          {t(
                            "products.rowNumber",
                            {
                              row:
                                error.row_number,
                            }
                          )}
                        </strong>
                        <span className="ms-2 text-rose-700">
                          {
                            message
                          }
                        </span>
                      </div>
                    );
                  }
                )}
              </div>
            </div>
          ) : null}

          {status?.status ===
          "FAILED" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-rose-50 p-4 text-xs font-bold leading-6 text-rose-900">
                {t(
                  "products.importFailed"
                )}
              </div>
              <div className="flex flex-wrap gap-2">
              {status.error_summary
                ?.retryable ===
              true ? (
                <button
                  type="button"
                  disabled={
                    retryPending ||
                    !online
                  }
                  onClick={onRetryImport}
                  className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
                >
                  {t(
                    "common.retry"
                  )}
                </button>
              ) : null}
                <button
                  type="button"
                  onClick={onResetImport}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-black text-slate-700"
                >
                  {t(
                    "products.newImport"
                  )}
                </button>
              </div>
            </div>
          ) : null}

          {status?.status ===
          "COMPLETED" ? (
            <div className="rounded-2xl bg-emerald-50 p-5 text-center">
              <strong className="text-sm text-emerald-900">
                {t(
                  "products.importCompleted",
                  {
                    count:
                      status.processed_rows,
                  }
                )}
              </strong>
              <button
                type="button"
                onClick={onCompletedClose}
                className="mt-4 block w-full rounded-xl bg-emerald-900 px-4 py-2.5 text-xs font-black text-white"
              >
                {t(
                  "common.close"
                )}
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
  );
}
