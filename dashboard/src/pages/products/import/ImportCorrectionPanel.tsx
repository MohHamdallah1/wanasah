import { Download, FileSpreadsheet, LoaderCircle, Upload } from "lucide-react";
import type { RefObject } from "react";
import { useTranslation } from "react-i18next";

type Props = {
  online: boolean;
  correctionFile: File | null;
  correctionFileRef: RefObject<HTMLInputElement | null>;
  downloadingCorrection: boolean;
  uploadingCorrection: boolean;
  onChooseCorrectionFile: (file: File | null) => void;
  onDownloadCorrection: () => void;
  onUploadCorrection: () => void;
};

/** File correction is a patch on this job, not a new Product Import. */
export function ImportCorrectionPanel({
  online,
  correctionFile,
  correctionFileRef,
  downloadingCorrection,
  uploadingCorrection,
  onChooseCorrectionFile,
  onDownloadCorrection,
  onUploadCorrection,
}: Props) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t("products.correction.title")}
      className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/50 p-3"
    >
      <div className="space-y-1">
        <h3 className="text-sm font-black text-slate-900">
          {t("products.correction.title")}
        </h3>
        <p className="text-xs font-medium leading-5 text-slate-700">
          {t("products.correction.hint")}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!online || downloadingCorrection || uploadingCorrection}
          onClick={onDownloadCorrection}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 text-xs font-black text-amber-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40"
        >
          {downloadingCorrection ? (
            <LoaderCircle className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          {t("products.correction.download")}
        </button>

        <input
          ref={correctionFileRef}
          type="file"
          accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
          className="sr-only"
          aria-label={t("products.correction.select")}
          disabled={!online || uploadingCorrection}
          onChange={(event) => {
            onChooseCorrectionFile(event.target.files?.[0] ?? null);
          }}
        />
        <button
          type="button"
          disabled={!online || uploadingCorrection}
          onClick={() => correctionFileRef.current?.click()}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40"
        >
          <FileSpreadsheet className="h-4 w-4" />
          {t("products.correction.select")}
        </button>
      </div>
      {correctionFile ? (
        <p className="break-all rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-700" aria-live="polite">
          {correctionFile.name}
        </p>
      ) : null}
      <button
        type="button"
        disabled={!online || !correctionFile || uploadingCorrection || downloadingCorrection}
        onClick={onUploadCorrection}
        className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40"
      >
        {uploadingCorrection ? (
          <LoaderCircle className="h-4 w-4 animate-spin" />
        ) : (
          <Upload className="h-4 w-4" />
        )}
        {t("products.correction.upload")}
      </button>
      <p className="text-xs leading-5 text-slate-600">
        {t("products.correction.keepSuccess")}
      </p>
    </section>
  );
}
