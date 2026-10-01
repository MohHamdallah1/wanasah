import { AlertCircle, LoaderCircle, RotateCcw, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ImportInlineCorrectionRow } from "@/pages/products/import/ImportInlineCorrectionRow";
import { useImportInlineCorrection } from "@/pages/products/import/useImportInlineCorrection";
import type { InlineCorrectionAck } from "@/pages/products/import/inlineCorrectionContracts";

type Props = {
  jobId: string;
  companyId: number | null;
  driverId: number | null;
  online: boolean;
  authFetch: (path: string, options?: RequestInit) => Promise<unknown>;
  onAccepted: (ack: InlineCorrectionAck) => void;
};

export function ImportInlineCorrectionPanel({
  jobId, companyId, driverId, online, authFetch, onAccepted,
}: Props) {
  const { t } = useTranslation();
  const review = useImportInlineCorrection({
    jobId, companyId, driverId, online, authFetch, onAccepted,
    loadFailedMessage: t("products.inlineCorrection.loadFailed"),
    saveFailedMessage: t("products.inlineCorrection.saveFailed"),
  });
  const busy = review.saving || review.pending !== null || review.staleDraft ||
    review.draftNeedsReload || !online;
  return (
    <section aria-label={t("products.inlineCorrection.title")} className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/30 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-black text-slate-950">{t("products.inlineCorrection.title")}</h3>
          <p className="mt-1 text-xs font-medium leading-5 text-slate-600">
            {t("products.inlineCorrection.hint")}
          </p>
        </div>
        <span className="rounded-full bg-white px-2 py-1 text-[11px] font-black text-amber-900">
          {t("products.inlineCorrection.smallLimit")}
        </span>
      </div>

      {!online ? (
        <p role="status" className="rounded-lg border border-slate-200 bg-white p-2 text-xs text-slate-700">
          {t("products.inlineCorrection.offline")}
        </p>
      ) : null}

      {review.loading && online ? (
        <p role="status" className="inline-flex items-center gap-2 text-xs font-semibold text-slate-600">
          <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
          {t("products.rejectedRows.loading")}
        </p>
      ) : null}

      {review.error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800">
          <AlertCircle aria-hidden className="h-4 w-4" />
          <p className="min-w-0 flex-1">{review.error}</p>
          {!review.pending ? (
            <button
              type="button"
              onClick={review.reload}
              disabled={!online || review.saving}
              className="min-h-9 rounded-lg border border-rose-200 bg-white px-3 font-black disabled:opacity-40"
            >
              {t("common.retry")}
            </button>
          ) : null}
        </div>
      ) : null}

      {review.pending ? (
        <div role="status" className="space-y-2 rounded-lg border border-amber-300 bg-white p-3 text-xs text-amber-950">
          <p className="font-bold">{t("products.inlineCorrection.unknownOutcome")}</p>
          <button
            type="button"
            onClick={review.retryPending}
            disabled={!online || review.saving}
            className="inline-flex min-h-9 items-center gap-1 rounded-lg bg-amber-900 px-3 font-black text-white disabled:opacity-40"
          >
            <RotateCcw aria-hidden className="h-4 w-4" />
            {t("products.inlineCorrection.retrySame")}
          </button>
        </div>
      ) : null}

      {(review.staleDraft || review.draftNeedsReload) ? (
        <div role="alert" className="space-y-2 rounded-lg border border-amber-300 bg-white p-3 text-xs text-amber-950">
          <p className="font-bold">{t(review.unreadableDraft
            ? "products.inlineCorrection.unreadableDraft"
            : review.draftNeedsReload
              ? "products.inlineCorrection.draftNeedsReload"
              : "products.inlineCorrection.staleDraft")}</p>
          <button
            type="button"
            disabled={review.saving || Boolean(review.pending)}
            onClick={() => {
              if (window.confirm(t("products.inlineCorrection.discardConfirm"))) review.discardDraft();
            }}
            className="min-h-9 rounded-lg border border-amber-300 px-3 font-bold disabled:opacity-40"
          >
            {t("products.inlineCorrection.discardDraft")}
          </button>
        </div>
      ) : null}

      {review.storageWarning ? (
        <p role="alert" className="text-xs font-bold text-rose-800">
          {t("products.inlineCorrection.storageWarning")}
        </p>
      ) : null}

      {review.page && !review.loading ? (
        <>
          {review.page.items.length === 0 ? (
            <p role="status" className="rounded-lg bg-white p-3 text-xs text-slate-600">
              {t("products.rejectedRows.empty")}
            </p>
          ) : (
            <ol className="max-h-[30rem] space-y-2 overflow-y-auto">
              {review.page.items.map((row, index) => (
                <ImportInlineCorrectionRow
                  key={row.row_identity}
                  row={row}
                  fields={review.page!.fields}
                  index={index}
                  edits={review.edits[row.row_identity] ?? {}}
                  disabled={busy || !row.editable}
                  onChange={review.change}
                />
              ))}
            </ol>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-amber-200 pt-3">
            <span className="text-xs font-semibold text-slate-600">
              {t("products.inlineCorrection.changedRows", { count: review.changedRows })}
            </span>
            {review.changedRows > 0 && !review.pending ? (
              <button
                type="button"
                disabled={review.saving}
                onClick={() => {
                  if (window.confirm(t("products.inlineCorrection.discardConfirm"))) review.discardDraft();
                }}
                className="min-h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 disabled:opacity-40"
              >
                {t("products.inlineCorrection.discardChanges")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={review.submit}
              disabled={busy || review.loading || review.changedRows === 0}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-slate-950 px-4 text-xs font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40"
            >
              {review.saving ? (
                <LoaderCircle aria-hidden className="h-4 w-4 animate-spin" />
              ) : (
                <Save aria-hidden className="h-4 w-4" />
              )}
              {t("products.inlineCorrection.submit")}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}
