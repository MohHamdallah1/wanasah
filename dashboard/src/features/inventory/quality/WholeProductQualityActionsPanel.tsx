import { AlertTriangle, ArrowRight, PackageCheck, Trash2, Truck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiErrorMessage } from "@/lib/apiErrors";
import { formatCommercialQuantity } from "@/lib/quantity";
import {
  useProductQualityCommands,
  type WholeProductQualityAction,
} from "./useProductQualityCommands";
import { useWholeProductQualityPreview } from "./useWholeProductQualityPreview";
import type { WholeProductQualityPreview } from "./wholeProductQualityPreviewContract";

const previewSignature = (preview: WholeProductQualityPreview): string => JSON.stringify(preview);

type PostResolutionHold = "NONE" | "SALES_HOLD";

export function WholeProductQualityActionsPanel({
  productVariantId,
  baseUomName,
  onBack,
  onResolved,
}: {
  productVariantId: number;
  baseUomName: string;
  onBack: () => void;
  onResolved: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const [activeAction, setActiveAction] = useState<WholeProductQualityAction | null>(null);
  const [reason, setReason] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [finalConfirmOpen, setFinalConfirmOpen] = useState(false);
  const [supervisorPassword, setSupervisorPassword] = useState("");
  const [passwordEditable, setPasswordEditable] = useState(false);
  const [postResolutionHold, setPostResolutionHold] = useState<PostResolutionHold | null>(null);
  const [previewChanged, setPreviewChanged] = useState(false);

  const preview = useWholeProductQualityPreview(productVariantId, true);
  const commands = useProductQualityCommands({
    productVariantId,
    onSucceeded: onResolved,
  });

  useEffect(() => {
    if (!preview.data || reason) return;
    setReason(preview.data.issueReason ?? "");
  }, [preview.data, reason]);

  const totalDisplay = useMemo(() => {
    if (!preview.data) return null;
    return formatCommercialQuantity(
      preview.data.totalQuantity,
      baseUomName,
      baseUomName,
      "1",
    );
  }, [baseUomName, preview.data]);

  const resetFinalConfirmation = () => {
    setFinalConfirmOpen(false);
    setSupervisorPassword("");
    setPasswordEditable(false);
    setPostResolutionHold(null);
  };

  const resetAction = () => {
    resetFinalConfirmation();
    setActiveAction(null);
    setRecipientName("");
    setPreviewChanged(false);
  };

  const openAction = (action: WholeProductQualityAction) => {
    resetFinalConfirmation();
    setActiveAction(action);
    setRecipientName("");
    setPreviewChanged(false);
  };

  const canContinue = Boolean(
    activeAction
      && preview.data
      && !preview.isFetching
      && !preview.isError
      && preview.data.blockerCodes.length === 0
      && reason.trim()
      && (activeAction !== "RETURN_TO_VENDOR" || recipientName.trim()),
  );

  const openFinalConfirmation = () => {
    if (!canContinue) return;
    setSupervisorPassword("");
    setPasswordEditable(false);
    setPostResolutionHold(null);
    setFinalConfirmOpen(true);
  };

  const submit = async () => {
    if (
      !activeAction
      || !reason.trim()
      || !supervisorPassword
      || !postResolutionHold
      || !preview.data
      || preview.data.blockerCodes.length > 0
    ) return;
    if (activeAction === "RETURN_TO_VENDOR" && !recipientName.trim()) return;

    const shownSignature = previewSignature(preview.data);
    const refreshed = await preview.refetch();
    if (!refreshed.data || refreshed.isError) return;
    if (previewSignature(refreshed.data) !== shownSignature) {
      setPreviewChanged(true);
      resetFinalConfirmation();
      return;
    }

    const ok = await commands.resolveAll({
      action: activeAction,
      reason,
      recipientName,
      confirmationPassword: supervisorPassword,
      postResolutionHold,
    });
    if (ok) {
      setSupervisorPassword("");
      setActiveAction(null);
      setFinalConfirmOpen(false);
    }
  };

  const quantityText = totalDisplay
    ? `${totalDisplay.primary}${totalDisplay.secondary ? ` (${totalDisplay.secondary})` : ""}`
    : "?";
  const previewBlocked = (preview.data?.blockerCodes.length ?? 0) > 0;
  const finalDisabled = commands.busyKey !== null
    || preview.isFetching
    || !supervisorPassword
    || postResolutionHold === null;

  if (finalConfirmOpen && activeAction) {
    return (
      <form
        autoComplete="off"
        onSubmit={(event) => { event.preventDefault(); void submit(); }}
        className="space-y-4"
        dir={i18n.dir()}
      >
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={resetFinalConfirmation}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700"
          >
            <ArrowRight className="h-4 w-4" />{t("common.back")}
          </button>
          <h3 className="text-sm font-black text-slate-950">
            {t("productQualityInline.final.title")}
          </h3>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-black text-slate-950">
            {t(activeAction === "DISPOSE"
              ? "productQualityInline.final.disposeSummary"
              : "productQualityInline.final.returnSummary")}
          </p>
          <p className="mt-1 text-[11px] font-bold text-slate-600">
            {t("productQualityInline.final.quantity", { quantity: quantityText })}
          </p>
          {activeAction === "RETURN_TO_VENDOR" ? (
            <p className="mt-1 text-[11px] font-bold text-slate-600">
              {t("productQualityInline.final.recipient", { recipient: recipientName.trim() })}
            </p>
          ) : null}
        </div>

        <fieldset className="space-y-2">
          <legend className="text-xs font-black text-slate-900">
            {t("productQualityInline.final.afterAction")}
          </legend>
          <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 bg-white p-3">
            <input
              type="radio"
              name="post-resolution-hold"
              checked={postResolutionHold === "NONE"}
              onChange={() => setPostResolutionHold("NONE")}
            />
            <span className="text-xs font-black text-slate-800">
              {t("productQualityInline.final.reactivate")}
            </span>
          </label>
          <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 bg-white p-3">
            <input
              type="radio"
              name="post-resolution-hold"
              checked={postResolutionHold === "SALES_HOLD"}
              onChange={() => setPostResolutionHold("SALES_HOLD")}
            />
            <span className="text-xs font-black text-slate-800">
              {t("productQualityInline.final.keepStopped")}
            </span>
          </label>
        </fieldset>

        <label className="block text-xs font-black text-slate-800">
          {t("productQualityInline.fields.supervisorPassword")}
          <input
            type="password"
            name="quality-confirmation-secret"
            autoComplete="off"
            readOnly={!passwordEditable}
            data-lpignore="true"
            data-1p-ignore="true"
            data-form-type="other"
            maxLength={256}
            value={supervisorPassword}
            onFocus={() => setPasswordEditable(true)}
            onChange={(event) => setSupervisorPassword(event.target.value)}
            placeholder={t("productQualityInline.fields.supervisorPasswordPlaceholder")}
            className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          />
        </label>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={resetFinalConfirmation}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black text-slate-700"
          >
            {t("common.cancel")}
          </button>
          <button
            type="submit"
            disabled={finalDisabled}
            className={`rounded-lg px-4 py-2 text-[10px] font-black text-white disabled:opacity-40 ${activeAction === "DISPOSE" ? "bg-rose-700" : "bg-sky-700"}`}
          >
            {t(activeAction === "DISPOSE"
              ? "productQualityInline.final.confirmDispose"
              : "productQualityInline.final.confirmReturn")}
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="space-y-3" dir={i18n.dir()}>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-black text-slate-700"
        >
          <ArrowRight className="h-4 w-4" />{t("common.back")}
        </button>
        <h3 className="text-sm font-black text-slate-950">{t("productQualityInline.title")}</h3>
      </div>

      {preview.isLoading ? (
        <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">
          {t("common.loading")}
        </p>
      ) : null}
      {preview.isError ? (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-bold text-rose-800">
          {apiErrorMessage(preview.error, t("productQualityInline.errors.preview"))}
        </div>
      ) : null}

      {preview.data ? (
        <>
          <div className="rounded-xl border border-slate-200 bg-white p-3">
            <p className="text-[10px] font-black text-slate-500">{t("productQualityInline.currentQuantity")}</p>
            <p className="mt-1 text-lg font-black tabular-nums text-slate-950">{quantityText}</p>
          </div>

          {!activeAction ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => openAction("DISPOSE")}
                disabled={commands.busyKey !== null || previewBlocked}
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-rose-200 bg-white px-4 text-xs font-black text-rose-800 transition hover:bg-rose-50 disabled:opacity-40"
              >
                <Trash2 className="h-4 w-4" />{t("productQualityInline.actions.disposeAll")}
              </button>
              <button
                type="button"
                onClick={() => openAction("RETURN_TO_VENDOR")}
                disabled={commands.busyKey !== null || previewBlocked}
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl border border-sky-200 bg-white px-4 text-xs font-black text-sky-900 transition hover:bg-sky-50 disabled:opacity-40"
              >
                <Truck className="h-4 w-4" />{t("productQualityInline.actions.returnAll")}
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center gap-2">
                <PackageCheck className="h-4 w-4 text-slate-500" />
                <p className="text-xs font-black text-slate-950">
                  {t(activeAction === "DISPOSE"
                    ? "productQualityInline.confirm.disposeTitle"
                    : "productQualityInline.confirm.returnTitle")}
                </p>
              </div>

              <p className="mt-3 text-[10px] font-black text-slate-500">
                {t("productQualityInline.fields.reason")}
              </p>
              {reason ? (
                <p className="mt-1 text-xs font-bold text-slate-900">{reason}</p>
              ) : (
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  autoComplete="off"
                  name="quality-issue-reason"
                  placeholder={t("productQualityInline.fields.reasonMissing")}
                  className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm"
                />
              )}

              {activeAction === "RETURN_TO_VENDOR" ? (
                <label className="mt-3 block text-[10px] font-black text-slate-700">
                  {t("productQualityInline.fields.recipientName")}
                  <input
                    value={recipientName}
                    onChange={(event) => setRecipientName(event.target.value)}
                    autoComplete="off"
                    name="quality-return-recipient"
                    className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
                  />
                </label>
              ) : null}

              {previewChanged ? (
                <div role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] font-bold text-amber-900">
                  {t("productQualityInline.preview.changed")}
                </div>
              ) : null}
              {previewBlocked ? (
                <div role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-[10px] font-bold text-amber-900">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{t("productQualityInline.preview.blocked")}</span>
                </div>
              ) : null}

              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={resetAction}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black text-slate-700"
                >
                  {t("common.back")}
                </button>
                <button
                  type="button"
                  disabled={!canContinue}
                  onClick={openFinalConfirmation}
                  className="rounded-lg bg-slate-950 px-4 py-2 text-[10px] font-black text-white disabled:opacity-40"
                >
                  {t("productQualityInline.confirm.continue")}
                </button>
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
