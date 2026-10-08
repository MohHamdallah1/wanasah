import { AlertTriangle, ArrowRight, PackageCheck, Trash2, Truck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { formatCommercialQuantity } from "@/lib/quantity";
import {
  useProductQualityCommands,
  type WholeProductQualityAction,
} from "./useProductQualityCommands";
import { SupervisorPasswordField } from "./SupervisorPasswordField";
import { useWholeProductQualityDraft } from "./useWholeProductQualityDraft";
import { useWholeProductQualityPreview } from "./useWholeProductQualityPreview";
import type { WholeProductQualityPreview } from "./wholeProductQualityPreviewContract";

const previewSignature = (preview: WholeProductQualityPreview): string => JSON.stringify(preview);
type PostResolutionHold = "NONE" | "SALES_HOLD";

const formatMoneyDisplay = (value: string, currencyCode: string): string => {
  const [whole, fraction = ""] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimals = fraction.slice(0, 3).replace(/0+$/, "");
  return `${grouped}${decimals ? `.${decimals}` : ""} ${currencyCode}`;
};

export function WholeProductQualityActionsPanel({
  productVariantId,
  baseUomName,
  displayUomName,
  displayFactorToBase,
  onBack,
  onOpenBatches,
  onResolved,
}: {
  productVariantId: number;
  baseUomName: string;
  displayUomName: string;
  displayFactorToBase: string;
  onBack: () => void;
  onOpenBatches: () => void;
  onResolved: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const [activeAction, setActiveAction] = useState<WholeProductQualityAction | null>(null);
  const [reason, setReason] = useState("");
  const [finalConfirmOpen, setFinalConfirmOpen] = useState(false);
  const [supervisorPassword, setSupervisorPassword] = useState("");
  const [postResolutionHold, setPostResolutionHold] = useState<PostResolutionHold | null>(null);
  const [previewChanged, setPreviewChanged] = useState(false);

  const { read: readDraft, save: saveDraft, clear: clearDraft } = useWholeProductQualityDraft(
    access.data?.company_id,
    access.data?.driver_id,
    productVariantId,
  );
  const preview = useWholeProductQualityPreview(productVariantId, true);
  const resolvedSupplier = preview.data?.supplierResolution === "SINGLE"
    ? preview.data.supplierCandidates[0] ?? null
    : null;
  const commands = useProductQualityCommands({
    productVariantId,
    onSucceeded: async () => {
      clearDraft("DISPOSE");
      clearDraft("RETURN_TO_VENDOR");
      setActiveAction(null);
      setFinalConfirmOpen(false);
      setSupervisorPassword("");
      setPostResolutionHold(null);
      await onResolved();
    },
  });

  useEffect(() => {
    if (!preview.data || reason) return;
    setReason(preview.data.issueReason ?? "");
  }, [preview.data, reason]);

  useEffect(() => {
    if (!activeAction) return;
    saveDraft(activeAction, { reason, supplierId: resolvedSupplier?.supplierId ?? null });
  }, [activeAction, reason, resolvedSupplier?.supplierId, saveDraft]);

  const totalDisplay = useMemo(() => {
    if (!preview.data) return null;
    return formatCommercialQuantity(
      preview.data.totalQuantity,
      displayUomName,
      baseUomName,
      displayFactorToBase,
    );
  }, [baseUomName, displayFactorToBase, displayUomName, preview.data]);

  const reservedDisplay = useMemo(() => {
    if (!preview.data || preview.data.totalReservedQuantity === "0") return null;
    return formatCommercialQuantity(
      preview.data.totalReservedQuantity,
      displayUomName,
      baseUomName,
      displayFactorToBase,
    );
  }, [baseUomName, displayFactorToBase, displayUomName, preview.data]);

  const resetFinalConfirmation = () => {
    setFinalConfirmOpen(false);
    setSupervisorPassword("");
    setPostResolutionHold(null);
  };

  const resetAction = () => {
    resetFinalConfirmation();
    setActiveAction(null);
    setPreviewChanged(false);
  };

  const openAction = (action: WholeProductQualityAction) => {
    if (
      commands.busyKey !== null
      || commands.pending !== null
      || commands.recoveryBlocked
      || !commands.recoveryReady
      || !commands.isOnline
    ) return;

    const draft = readDraft(action);
    resetFinalConfirmation();
    setActiveAction(action);
    setReason(preview.data?.issueReason ?? draft?.reason ?? "");
    setPreviewChanged(false);
  };

  const previewBlocked = (preview.data?.blockerCodes.length ?? 0) > 0;
  const blockerText = useMemo(() => {
    const codes = preview.data?.blockerCodes ?? [];
    if (codes.includes("WHOLE_PRODUCT_QUALITY_RESERVED_STOCK")) {
      const reserved = reservedDisplay
        ? `${reservedDisplay.primary}${reservedDisplay.secondary ? ` — ${t("productQualityInline.totalBaseQuantity", { quantity: reservedDisplay.secondary })}` : ""}`
        : "";
      return t("productQualityInline.preview.blockers.reservedStock", { quantity: reserved });
    }
    if (codes.includes("WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER")) {
      return t("productQualityInline.preview.blockers.custody");
    }
    return codes.length > 0 ? t("productQualityInline.preview.blocked") : null;
  }, [preview.data?.blockerCodes, reservedDisplay, t]);
  const interactionBlocked = commands.busyKey !== null
    || commands.pending !== null
    || commands.recoveryBlocked
    || !commands.recoveryReady
    || !commands.isOnline;
  const canContinue = Boolean(
    activeAction
      && preview.data
      && !preview.isFetching
      && !preview.isError
      && !previewBlocked
      && !interactionBlocked
      && reason.trim()
      && (
        activeAction !== "RETURN_TO_VENDOR"
        || (resolvedSupplier !== null && access.can("supplier.read"))
      ),
  );

  const openFinalConfirmation = () => {
    if (!canContinue) return;
    setSupervisorPassword("");
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
      || previewBlocked
    ) return;
    if (activeAction === "RETURN_TO_VENDOR" && resolvedSupplier === null) return;

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
      supplierId: activeAction === "RETURN_TO_VENDOR" ? resolvedSupplier?.supplierId ?? null : null,
      confirmationPassword: supervisorPassword,
      postResolutionHold,
    });
    setSupervisorPassword("");
    if (ok) {
      setActiveAction(null);
      setFinalConfirmOpen(false);
    }
  };

  const quantityText = totalDisplay
    ? `${totalDisplay.primary}${totalDisplay.secondary ? ` (${t("productQualityInline.totalBaseQuantity", { quantity: totalDisplay.secondary })})` : ""}`
    : "?";
  const returnValueText = preview.data?.valuationAvailable && preview.data.totalBookValue
    ? formatMoneyDisplay(preview.data.totalBookValue, preview.data.currencyCode)
    : null;
  const averageUnitCostText = preview.data?.valuationAvailable && preview.data.averageUnitCost
    ? formatMoneyDisplay(preview.data.averageUnitCost, preview.data.currencyCode)
    : null;
  const supplierQuantityText = (value: string | null): string | null => {
    if (!value) return null;
    const display = formatCommercialQuantity(value, displayUomName, baseUomName, displayFactorToBase);
    return `${display.primary}${display.secondary ? ` · ${t("productQualityInline.totalBaseQuantity", { quantity: display.secondary })}` : ""}`;
  };
  const finalDisabled = interactionBlocked
    || preview.isFetching
    || !supervisorPassword
    || postResolutionHold === null;

  if (commands.pending || commands.recoveryBlocked) {
    return (
      <div className="space-y-3" dir={i18n.dir()}>
        <div role="alert" className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-black text-slate-900">{t("productQualityInline.pending")}</p>
          {commands.pending ? (
            <div className="mt-3 space-y-3">
              <SupervisorPasswordField
                value={supervisorPassword}
                onChange={setSupervisorPassword}
                disabled={commands.busyKey !== null || !commands.isOnline}
              />
              <button
                type="button"
                disabled={!supervisorPassword || commands.busyKey !== null || !commands.isOnline}
                onClick={() => {
                  const password = supervisorPassword;
                  setSupervisorPassword("");
                  void commands.retryPending(password);
                }}
                className="rounded-lg bg-slate-950 px-4 py-2 text-[10px] font-black text-white disabled:opacity-40"
              >
                {t("common.retry")}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (!commands.recoveryReady) {
    return (
      <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-500">
        {t("common.loading")}
      </p>
    );
  }

  if (finalConfirmOpen && activeAction) {
    return (
      <form
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
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
          <p className="text-xs font-semibold text-slate-900">
            {t(activeAction === "DISPOSE"
              ? "productQualityInline.final.disposeSummary"
              : "productQualityInline.final.returnSummary")}
          </p>
          <p className="mt-1 text-[11px] font-bold text-slate-600">
            {t("productQualityInline.final.quantity", { quantity: quantityText })}
          </p>
          {activeAction === "RETURN_TO_VENDOR" ? (
            <div className="mt-1 space-y-0.5 text-[11px] font-medium text-slate-600">
              {resolvedSupplier ? (
                <p>{t("productQualityInline.final.recipient", { recipient: resolvedSupplier.supplierName })}</p>
              ) : null}
              <p>
                {t("productQualityInline.confirm.averageUnitCost")}: {averageUnitCostText ? `${averageUnitCostText} / ${baseUomName}` : t("productQualityInline.confirm.valuationUnavailable")}
              </p>
              <p>
                {t("productQualityInline.confirm.returnValue")}: {returnValueText ?? t("productQualityInline.confirm.valuationUnavailable")}
              </p>
            </div>
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

        <SupervisorPasswordField
          value={supervisorPassword}
          onChange={setSupervisorPassword}
          disabled={commands.busyKey !== null || !commands.isOnline}
        />

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

      {!commands.isOnline ? (
        <p role="status" className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs font-bold text-slate-700">
          {t("suppliers.offline")}
        </p>
      ) : null}
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
          <div className="rounded-xl border border-slate-100 bg-white px-3 py-2.5">
            <p className="text-[10px] font-medium text-slate-500">{t("productQualityInline.currentQuantity")}</p>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 tabular-nums">
              <span className="text-base font-semibold text-slate-900">{totalDisplay?.primary ?? "?"}</span>
              {totalDisplay?.secondary ? (
                <span className="text-[10px] font-medium text-slate-500">
                  {t("productQualityInline.totalBaseQuantity", { quantity: totalDisplay.secondary })}
                </span>
              ) : null}
            </div>
          </div>

          {previewBlocked && blockerText ? (
            <div role="alert" className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-[10px] font-bold leading-5 text-slate-700">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{blockerText}</span>
              </div>
              {preview.data.blockerCodes.includes("WHOLE_PRODUCT_QUALITY_RESERVED_STOCK") ? (
                <button
                  type="button"
                  onClick={onOpenBatches}
                  className="mt-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-[10px] font-black text-slate-800 transition hover:bg-slate-100"
                >
                  {t("productQualityInline.preview.openLinkedOperation")}
                </button>
              ) : null}
            </div>
          ) : null}

          {!activeAction ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => openAction("DISPOSE")}
                disabled={interactionBlocked || previewBlocked}
                title={previewBlocked && blockerText ? blockerText : undefined}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
              >
                <Trash2 className="h-4 w-4" />{t("productQualityInline.actions.disposeAll")}
              </button>
              <button
                type="button"
                onClick={() => openAction("RETURN_TO_VENDOR")}
                disabled={interactionBlocked || previewBlocked}
                title={previewBlocked && blockerText ? blockerText : undefined}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
              >
                <Truck className="h-4 w-4" />{t("productQualityInline.actions.returnAll")}
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-100 bg-white p-3">
              <div className="flex items-center gap-2">
                <PackageCheck className="h-4 w-4 text-slate-500" />
                <p className="text-xs font-black text-slate-950">
                  {t(activeAction === "DISPOSE"
                    ? "productQualityInline.confirm.disposeTitle"
                    : "productQualityInline.confirm.returnTitle")}
                </p>
              </div>

              <p className="mt-3 text-[10px] font-medium text-slate-500">
                {t("productQualityInline.fields.reason")}
              </p>
              {reason ? (
                <p className="mt-1 text-xs font-medium text-slate-800">{reason}</p>
              ) : (
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  autoComplete="off"
                  name="quality-issue-reason"
                  maxLength={1000}
                  placeholder={t("productQualityInline.fields.reasonMissing")}
                  className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm"
                />
              )}

              {activeAction === "RETURN_TO_VENDOR" ? (
                <div className="mt-3 space-y-2">
                  <div className="grid gap-3 rounded-lg bg-slate-50/80 px-3 py-2.5 sm:grid-cols-2">
                    <div>
                      <p className="text-[10px] font-medium text-slate-500">
                        {t("productQualityInline.confirm.averageUnitCost")}
                      </p>
                      <p className="mt-0.5 text-sm font-semibold tabular-nums text-slate-900">
                        {averageUnitCostText ? `${averageUnitCostText} / ${baseUomName}` : t("productQualityInline.confirm.valuationUnavailable")}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] font-medium text-slate-500">
                        {t("productQualityInline.confirm.returnValue")}
                      </p>
                      <p className="mt-0.5 text-sm font-semibold tabular-nums text-slate-900">
                        {returnValueText ?? t("productQualityInline.confirm.valuationUnavailable")}
                      </p>
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-50/80 px-3 py-2.5">
                    <p className="text-[10px] font-medium text-slate-500">
                      {t("productQualityInline.confirm.supplier")}
                    </p>
                    {resolvedSupplier ? (
                      <>
                        <div className="mt-0.5 flex flex-wrap items-baseline gap-2">
                          <span className="text-sm font-semibold text-slate-900">{resolvedSupplier.supplierName}</span>
                          {resolvedSupplier.supplierCode ? (
                            <span className="text-[10px] font-medium text-slate-500">{resolvedSupplier.supplierCode}</span>
                          ) : null}
                        </div>
                        <p className="mt-0.5 text-[10px] font-medium text-slate-500">
                          {t("productQualityInline.confirm.supplierResolved")}
                        </p>
                      </>
                    ) : preview.data.supplierResolution === "MULTIPLE" ? (
                      <div className="mt-1 space-y-1.5">
                        <p className="text-[10px] font-medium leading-5 text-slate-600">
                          {t("productQualityInline.confirm.supplierMultiple")}
                        </p>
                        {preview.data.supplierCandidates.map((candidate) => (
                          <div key={candidate.supplierId} className="flex items-baseline justify-between gap-3 text-xs">
                            <span className="font-medium text-slate-800">{candidate.supplierName}</span>
                            {candidate.quantity ? (
                              <span className="shrink-0 text-[10px] tabular-nums text-slate-500">
                                {supplierQuantityText(candidate.quantity)}
                              </span>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="mt-1 text-[10px] font-medium leading-5 text-slate-600">
                        {t("productQualityInline.confirm.supplierUnknown")}
                      </p>
                    )}
                  </div>
                </div>
              ) : null}

              {previewChanged ? (
                <div role="alert" className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[10px] font-bold text-slate-700">
                  {t("productQualityInline.preview.changed")}
                </div>
              ) : null}
              {previewBlocked ? (
                <div role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[10px] font-bold text-slate-700">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{blockerText ?? t("productQualityInline.preview.blocked")}</span>
                </div>
              ) : null}

              <div className="mt-3 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={resetAction}
                  disabled={interactionBlocked}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black text-slate-700 disabled:opacity-40"
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
