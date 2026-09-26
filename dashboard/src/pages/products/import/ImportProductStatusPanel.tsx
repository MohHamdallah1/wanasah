import {
  AlertCircle,
  CheckCircle2,
  Download,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductImportState,
} from "@/pages/products/contracts";

type Props = {
  status: ProductImportState | null;
  pollError: string | null;
  progress: number;
  online: boolean;
  retryPending: boolean;
  onRetryPoll: () => void;
  onDownloadErrorReport: () => void;
  onResetImport: () => void;
  onRetryImport: () => void;
  onCompletedClose: () => void;
};

export function ImportProductStatusPanel({
  status,
  pollError,
  progress,
  online,
  retryPending,
  onRetryPoll,
  onDownloadErrorReport,
  onResetImport,
  onRetryImport,
  onCompletedClose,
}: Props) {
  const { t, i18n } =
    useTranslation();

  if (pollError) {
    return (
      <div
        role="alert"
        className="flex flex-col gap-2 rounded-xl border border-rose-200 bg-rose-50/70 p-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex min-w-0 items-start gap-2">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" />
          <span className="text-[10px] font-bold leading-4 text-rose-800">
            {pollError}
          </span>
        </div>
        <button
          type="button"
          onClick={onRetryPoll}
          className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-white px-2.5 text-[10px] font-black text-rose-800 ring-1 ring-rose-200"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t(
            "common.retry",
          )}
        </button>
      </div>
    );
  }

  if (!status) {
    return (
      <div
        aria-live="polite"
        className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3"
      >
        <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-slate-500" />
        <span className="text-xs font-black text-slate-600">
          {t(
            "products.queued",
          )}
        </span>
      </div>
    );
  }

  if (
    status.status ===
    "VALIDATION_FAILED"
  ) {
    return (
      <div className="space-y-3">
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50/70 px-3 py-2.5"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" />
          <p className="text-[10px] font-bold leading-4 text-rose-900">
            {t(
              "products.validationFailed",
              {
                count:
                  status.failed_rows,
              },
            )}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!online}
            onClick={
              onDownloadErrorReport
            }
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-rose-200 bg-white px-3 text-xs font-black text-rose-800 disabled:opacity-40"
          >
            <Download className="h-3.5 w-3.5" />
            {t(
              "products.downloadErrors",
            )}
          </button>
          <button
            type="button"
            onClick={onResetImport}
            className="min-h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700"
          >
            {t(
              "products.newImport",
            )}
          </button>
        </div>

        <div className="max-h-64 overflow-auto rounded-xl border border-slate-200 bg-white">
          {status.errors.map(
            (error) => {
              const key =
                error.code
                  ? "errors.codes." +
                    error.code
                  : "";
              const message =
                key &&
                i18n.exists(key)
                  ? t(key)
                  : t(
                      "network.serverError",
                    );

              return (
                <div
                  key={
                    String(
                      error.row_number,
                    ) +
                    "-" +
                    String(
                      error.code,
                    )
                  }
                  className="grid gap-1 border-b border-slate-100 px-3 py-2.5 text-[10px] last:border-b-0 sm:grid-cols-[100px_minmax(0,1fr)]"
                >
                  <strong className="font-black text-slate-600">
                    {t(
                      "products.rowNumber",
                      {
                        row:
                          error.row_number,
                      },
                    )}
                  </strong>
                  <span className="font-bold leading-4 text-rose-700">
                    {message}
                  </span>
                </div>
              );
            },
          )}
        </div>
      </div>
    );
  }

  if (status.status === "FAILED") {
    return (
      <div className="space-y-3">
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50/70 px-3 py-2.5"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" />
          <p className="text-[10px] font-bold leading-4 text-rose-900">
            {t(
              "products.importFailed",
            )}
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          {status.error_summary
            ?.retryable === true ? (
            <button
              type="button"
              disabled={
                retryPending ||
                !online
              }
              onClick={onRetryImport}
              className="min-h-10 flex-1 rounded-xl bg-slate-950 px-4 text-sm font-black text-white disabled:opacity-40"
            >
              {t(
                "common.retry",
              )}
            </button>
          ) : null}

          <button
            type="button"
            onClick={onResetImport}
            className="min-h-10 flex-1 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700"
          >
            {t(
              "products.newImport",
            )}
          </button>
        </div>
      </div>
    );
  }

  if (
    status.status ===
    "COMPLETED"
  ) {
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-emerald-700 ring-1 ring-emerald-200">
            <CheckCircle2 className="h-5 w-5" />
          </span>
          <strong className="text-sm font-black text-emerald-900">
            {t(
              "products.importCompleted",
              {
                count:
                  status.processed_rows,
              },
            )}
          </strong>
        </div>
        <button
          type="button"
          onClick={onCompletedClose}
          className="mt-3 w-full rounded-xl bg-emerald-900 px-4 py-2.5 text-xs font-black text-white"
        >
          {t(
            "common.close",
          )}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-3 text-[11px] font-black text-slate-700">
        <span className="flex min-w-0 items-center gap-2">
          <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-slate-500" />
          <span className="truncate">
            {status.status ===
            "IMPORTING"
              ? t(
                  "products.importingProducts",
                )
              : t(
                  "products.preparingImport",
                )}
          </span>
        </span>
        <span className="shrink-0 tabular-nums text-slate-500">
          {status.processed_rows} /{" "}
          {status.valid_rows ||
            status.total_rows}
        </span>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-slate-950 transition-all"
          style={{
            width:
              String(progress) + "%",
          }}
        />
      </div>

      <p className="mt-2 text-[10px] font-semibold leading-4 text-slate-400">
        {t(
          "products.backgroundHint",
        )}
      </p>
    </div>
  );
}
