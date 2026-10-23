import {
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Download, FileSpreadsheet, Upload } from "lucide-react";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { currentLocale } from "@/i18n";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { DurableCommand } from "@/lib/durableOperations";
import {
  executeOpeningValuationFinalize,
  finalizePayloadFromPreview,
  parseOpeningValuationFinalizeResult,
  parseOpeningValuationPreview,
  parseOpeningValuationTemplateArtifact,
  readPendingOpeningValuation,
  saveOpeningValuationTemplate,
  type OpeningValuationFinalizePayload,
  type OpeningValuationFinalizeResult,
  type OpeningValuationPreview,
} from "./openingValuation";

const MAX_FILE_BYTES = 5 * 1024 * 1024;

interface Props {
  isOpen: boolean;
  onClose: () => void;
  companyId: number;
  actorId: number;
  authenticatedFetch: (
    url: string,
    opts?: RequestInit,
  ) => Promise<unknown>;
  onFinalized: (
    result: OpeningValuationFinalizeResult,
  ) => void | Promise<void>;
}

export function OpeningValuationModal({
  isOpen,
  onClose,
  companyId,
  actorId,
  authenticatedFetch,
  onFinalized,
}: Props) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<OpeningValuationPreview | null>(null);
  const [confirmZeroCosts, setConfirmZeroCosts] = useState(false);
  const [busy, setBusy] = useState<
    "download" | "preview" | "finalize" | "retry" | null
  >(null);
  const [recovery, setRecovery] = useState<
    DurableCommand<OpeningValuationFinalizePayload> | null
  >(null);

  const refreshRecovery = async () => {
    const pending = await readPendingOpeningValuation(companyId, actorId);
    setRecovery(pending);
    return pending;
  };

  useEffect(() => {
    if (!isOpen) return;
    let live = true;
    setFile(null);
    setPreview(null);
    setConfirmZeroCosts(false);
    void readPendingOpeningValuation(companyId, actorId)
      .then((pending) => {
        if (live) setRecovery(pending);
      })
      .catch((error) => {
        if (!live) return;
        toast.error(
          apiErrorMessage(
            error,
            t("inventoryInbound.openingValuation.recoveryLoadFailed"),
          ),
        );
      });
    return () => {
      live = false;
    };
  }, [actorId, companyId, isOpen, t]);

  const downloadTemplate = async () => {
    setBusy("download");
    try {
      const raw = await authenticatedFetch(
        "/warehouse/costing/opening-valuation/template?locale=" +
          encodeURIComponent(currentLocale()),
      );
      const artifact = parseOpeningValuationTemplateArtifact(raw);
      saveOpeningValuationTemplate(artifact);
      toast.success(
        t("inventoryInbound.openingValuation.templateDownloaded", {
          count: artifact.row_count,
        }),
      );
    } catch (error) {
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryInbound.openingValuation.downloadFailed"),
        ),
      );
    } finally {
      setBusy(null);
    }
  };

  const previewFile = async () => {
    if (!file) {
      toast.error(t("inventoryInbound.openingValuation.fileRequired"));
      return;
    }
    if (
      !file.name.toLowerCase().endsWith(".xlsx") ||
      file.size <= 0 ||
      file.size > MAX_FILE_BYTES
    ) {
      toast.error(t("inventoryInbound.openingValuation.fileInvalid"));
      return;
    }
    setBusy("preview");
    try {
      const form = new FormData();
      form.append("file", file);
      const result = parseOpeningValuationPreview(
        await authenticatedFetch(
          "/warehouse/costing/opening-valuation/preview-file",
          {
            method: "POST",
            body: form,
          },
        ),
      );
      setPreview(result);
      setConfirmZeroCosts(false);
      toast.success(t("inventoryInbound.openingValuation.previewReady"));
    } catch (error) {
      setPreview(null);
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryInbound.openingValuation.previewFailed"),
        ),
      );
    } finally {
      setBusy(null);
    }
  };

  const finish = async (payload?: OpeningValuationFinalizePayload) => {
    const mode = payload ? "finalize" : "retry";
    setBusy(mode);
    try {
      const raw = await executeOpeningValuationFinalize({
        companyId,
        actorId,
        payload,
        authenticatedFetch,
      });
      const result = parseOpeningValuationFinalizeResult(raw);
      setRecovery(null);
      toast.success(t("inventoryInbound.openingValuation.finalized"));
      await onFinalized(result);
      onClose();
    } catch (error) {
      await refreshRecovery().catch(() => undefined);
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryInbound.openingValuation.finalizeFailed"),
        ),
      );
    } finally {
      setBusy(null);
    }
  };

  const finalize = async () => {
    if (!preview) return;
    if (preview.zero_cost_count > 0 && !confirmZeroCosts) {
      toast.error(t("inventoryInbound.openingValuation.zeroConfirmRequired"));
      return;
    }
    await finish(
      finalizePayloadFromPreview(preview, confirmZeroCosts),
    );
  };

  const locked = busy !== null;
  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        if (!locked) onClose();
      }}
      title={t("inventoryInbound.openingValuation.title")}
      subtitle={t("inventoryInbound.openingValuation.subtitle")}
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4 text-sm">
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
          <p className="font-black">
            {t("inventoryInbound.openingValuation.whyTitle")}
          </p>
          <p className="mt-1 leading-6">
            {t("inventoryInbound.openingValuation.whyBody")}
          </p>
        </div>

        {recovery ? (
          <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950">
            <p className="font-black">
              {t("inventoryInbound.openingValuation.recoveryTitle")}
            </p>
            <p className="mt-1 leading-6">
              {t("inventoryInbound.openingValuation.recoveryBody")}
            </p>
            <button
              type="button"
              disabled={locked}
              onClick={() => void finish()}
              className="mt-3 rounded-lg bg-amber-700 px-4 py-2 font-black text-white disabled:opacity-50"
            >
              {busy === "retry"
                ? t("common.loading")
                : t("inventoryInbound.openingValuation.retrySame")}
            </button>
          </div>
        ) : (
          <>
            <section className="rounded-xl border p-4">
              <div className="flex items-start gap-3">
                <Download className="mt-0.5 h-5 w-5" />
                <div className="min-w-0 flex-1">
                  <h4 className="font-black">
                    {t("inventoryInbound.openingValuation.step1Title")}
                  </h4>
                  <p className="mt-1 text-slate-600">
                    {t("inventoryInbound.openingValuation.step1Body")}
                  </p>
                  <button
                    type="button"
                    disabled={locked}
                    onClick={() => void downloadTemplate()}
                    className="mt-3 rounded-lg border border-slate-300 bg-white px-4 py-2 font-black disabled:opacity-50"
                  >
                    {busy === "download"
                      ? t("common.loading")
                      : t("inventoryInbound.openingValuation.download")}
                  </button>
                </div>
              </div>
            </section>

            <section className="rounded-xl border p-4">
              <div className="flex items-start gap-3">
                <Upload className="mt-0.5 h-5 w-5" />
                <div className="min-w-0 flex-1">
                  <h4 className="font-black">
                    {t("inventoryInbound.openingValuation.step2Title")}
                  </h4>
                  <p className="mt-1 text-slate-600">
                    {t("inventoryInbound.openingValuation.step2Body")}
                  </p>
                  <input
                    ref={inputRef}
                    type="file"
                    accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    className="mt-3 block w-full text-sm"
                    disabled={locked}
                    onChange={(event) => {
                      setFile(event.target.files?.[0] ?? null);
                      setPreview(null);
                      setConfirmZeroCosts(false);
                    }}
                  />
                  <button
                    type="button"
                    disabled={locked || !file}
                    onClick={() => void previewFile()}
                    className="mt-3 rounded-lg bg-slate-900 px-4 py-2 font-black text-white disabled:opacity-50"
                  >
                    {busy === "preview"
                      ? t("common.loading")
                      : t("inventoryInbound.openingValuation.preview")}
                  </button>
                </div>
              </div>
            </section>

            {preview ? (
              <section className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
                <div className="flex items-start gap-3">
                  <FileSpreadsheet className="mt-0.5 h-5 w-5 text-emerald-700" />
                  <div className="min-w-0 flex-1">
                    <h4 className="font-black text-emerald-950">
                      {t("inventoryInbound.openingValuation.step3Title")}
                    </h4>
                    <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
                      <Summary
                        label={t("inventoryInbound.openingValuation.products")}
                        value={String(preview.line_count)}
                      />
                      <Summary
                        label={t("inventoryInbound.openingValuation.quantity")}
                        value={preview.total_quantity}
                      />
                      <Summary
                        label={t("inventoryInbound.openingValuation.value")}
                        value={preview.total_value + " " + preview.currency_code}
                      />
                      <Summary
                        label={t("inventoryInbound.openingValuation.zeroCosts")}
                        value={String(preview.zero_cost_count)}
                      />
                    </div>

                    {preview.zero_cost_count > 0 ? (
                      <label className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
                        <input
                          type="checkbox"
                          checked={confirmZeroCosts}
                          onChange={(event) =>
                            setConfirmZeroCosts(event.target.checked)
                          }
                        />
                        <span>
                          {t("inventoryInbound.openingValuation.zeroConfirm", {
                            count: preview.zero_cost_count,
                          })}
                        </span>
                      </label>
                    ) : null}

                    <p className="mt-4 text-xs font-bold text-slate-600">
                      {t("inventoryInbound.openingValuation.serverAuthorityNote")}
                    </p>
                    <button
                      type="button"
                      disabled={
                        locked ||
                        (preview.zero_cost_count > 0 && !confirmZeroCosts)
                      }
                      onClick={() => void finalize()}
                      className="mt-3 rounded-lg bg-emerald-700 px-5 py-2.5 font-black text-white disabled:opacity-50"
                    >
                      {busy === "finalize"
                        ? t("common.loading")
                        : t("inventoryInbound.openingValuation.finalize")}
                    </button>
                  </div>
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>
    </Modal>
  );
}

function Summary({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="text-[11px] font-bold text-slate-500">{label}</div>
      <div dir="ltr" className="mt-1 break-all text-sm font-black text-slate-900">
        {value}
      </div>
    </div>
  );
}
