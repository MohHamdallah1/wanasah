import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  FlaskConical,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { ReasonPresetField } from "@/components/forms/ReasonPresetField";
import { Modal } from "@/components/ui/modal";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";

import { BatchQuantityActions } from "./BatchQuantityActions";
import { allowedBatchDispositionTargets } from "./batchDispositionRules";
import type { BatchActionSnapshot, BatchDisposition } from "./contracts";
import { useBatchDispositionCommand } from "./useBatchDispositionCommand";

type Props = {
  batch: BatchActionSnapshot | null;
  productVariantId: number | null;
  baseUomCode: string;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
  onOpenTransfers: () => void;
};

const targetIcon = (
  target: BatchDisposition,
) => {
  if (target === "QUARANTINED") {
    return <FlaskConical className="h-4 w-4" />;
  }
  if (target === "BLOCKED") {
    return <Ban className="h-4 w-4" />;
  }
  if (target === "RECALLED") {
    return <ShieldAlert className="h-4 w-4" />;
  }
  return <RotateCcw className="h-4 w-4" />;
};

const reasonPresetKeys: Record<
  BatchDisposition,
  readonly string[]
> = {
  RELEASED: [
    "inspectionPassed",
    "issueNotConfirmed",
    "dataCorrected",
  ],
  QUARANTINED: [
    "expiryConcern",
    "qualityConcern",
    "packagingDamage",
    "verificationRequired",
  ],
  BLOCKED: [
    "confirmedQualityIssue",
    "supplierInstruction",
    "regulatoryHold",
    "operationalBlock",
  ],
  RECALLED: [
    "confirmedSafetyIssue",
    "confirmedQualityIssue",
    "supplierRecall",
    "regulatoryRecall",
  ],
};

export function BatchDispositionManager({
  batch,
  productVariantId,
  baseUomCode,
  onClose,
  onChanged,
  onOpenTransfers,
}: Props) {
  const { t } = useTranslation();
  const access = useInventoryAccess();
  const canChange =
    access.isCompanyAdmin ||
    access.can("batch.disposition");
  const targets = useMemo(
    () =>
      batch
        ? allowedBatchDispositionTargets(batch.disposition)
        : [],
    [batch],
  );
  const command = useBatchDispositionCommand({
    batch,
    canChange,
    onSucceeded: async () => {
      await onChanged();
      onClose();
    },
  });
  const activeTarget =
    command.target ??
    command.pending?.payload.disposition ??
    null;
  const reasonPresets = useMemo(
    () =>
      activeTarget
        ? reasonPresetKeys[activeTarget].map((key) =>
            t(`inventoryBatches.disposition.reasonPresets.${key}`),
          )
        : [],
    [activeTarget, t],
  );

  if (!batch) return null;

  const locked =
    command.busy ||
    command.pending !== null ||
    command.pendingBlocked;
  const canSubmit =
    command.isOnline &&
    canChange &&
    !command.busy &&
    !command.pendingBlocked &&
    (command.pending !== null ||
      (command.target !== null &&
        command.reason.trim().length > 0));

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={t("inventoryBatches.disposition.title", {
        batch: batch.batch_number,
      })}
      subtitle={t(
        "inventoryBatches.disposition.scopeHint",
      )}
      maxWidth="max-w-xl"
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
          <p className="text-[10px] font-black text-slate-500">
            {t("inventoryBatches.disposition.current")}
          </p>
          <p className="mt-1 text-sm font-black text-slate-900">
            {t(
              `inventoryLive.batchDisposition.${batch.disposition}`,
            )}
          </p>
          {batch.disposition_reason ? (
            <p className="mt-1 text-[10px] font-bold leading-4 text-slate-600">
              {t("inventoryBatches.disposition.reasonDisplay", {
                reason: batch.disposition_reason,
              })}
            </p>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[9px] font-semibold text-slate-500">
            <span>
              {t("inventoryLive.expiryDate")}: {batch.expiry_date ?? "—"}
            </span>
            {batch.days_to_expiry !== null ? (
              <span>
                {batch.days_to_expiry < 0
                  ? t("inventoryLive.expiredSince", {
                      count: Math.abs(batch.days_to_expiry),
                    })
                  : batch.days_to_expiry === 0
                    ? t("inventoryLive.expiresToday")
                    : t("inventoryLive.daysRemaining", {
                        count: batch.days_to_expiry,
                      })}
              </span>
            ) : null}
          </div>
        </div>

        {batch.disposition === "RECALLED" ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3 text-[11px] font-bold leading-5 text-rose-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {t(
                  "inventoryBatches.disposition.recalledTerminal",
                )}
              </span>
            </div>
          </div>
        ) : (
          <div>
            <p className="mb-2 text-[11px] font-black text-slate-700">
              {t("inventoryBatches.disposition.choose")}
            </p>
            <div className="grid gap-2">
              {targets.map((item) => (
                <button
                  key={item}
                  type="button"
                  disabled={locked || !canChange}
                  aria-pressed={command.target === item}
                  onClick={() => command.setTarget(item)}
                  className={`grid grid-cols-[2rem_minmax(0,1fr)] items-start gap-2 rounded-xl border p-3 text-start transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 disabled:opacity-50 ${
                    command.target === item
                      ? "border-slate-900 bg-slate-50"
                      : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                >
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-700">
                    {targetIcon(item)}
                  </span>
                  <span>
                    <span className="block text-[11px] font-black text-slate-900">
                      {t(
                        `inventoryBatches.disposition.targets.${item}.label`,
                      )}
                    </span>
                    <span className="mt-0.5 block text-[9px] font-semibold leading-4 text-slate-500">
                      {t(
                        `inventoryBatches.disposition.targets.${item}.hint`,
                      )}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {targets.length > 0 &&
        (command.target !== null ||
          command.pending !== null) ? (
          <ReasonPresetField
            label={t("inventoryBatches.disposition.reason")}
            chooseLabel={t(
              "inventoryBatches.disposition.reasonChoose",
            )}
            otherLabel={t(
              "inventoryBatches.disposition.reasonOther",
            )}
            customPlaceholder={t(
              "inventoryBatches.disposition.reasonPlaceholder",
            )}
            presets={reasonPresets}
            value={command.reason}
            onChange={command.setReason}
            disabled={locked || !canChange}
            maxLength={2000}
            multiline
            autoFocus={command.target !== null}
            canSubmit={canSubmit}
            onSubmit={() => void command.submit()}
            onCancel={onClose}
          />
        ) : null}

        {command.pending ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-[10px] font-bold leading-5 text-amber-900">
            {t("inventoryBatches.disposition.pending")}
          </div>
        ) : null}

        {command.pendingBlocked ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3 text-[10px] font-bold leading-5 text-rose-900">
            {t("inventoryBatches.disposition.pendingBlocked")}
          </div>
        ) : null}

        {!canChange ? (
          <p className="text-[10px] font-bold text-slate-500">
            {t("inventoryBatches.disposition.noPermission")}
          </p>
        ) : null}

        {productVariantId !== null ? (
          <BatchQuantityActions
            batch={batch}
            productVariantId={productVariantId}
            baseUomCode={baseUomCode}
            onChanged={onChanged}
            onOpenTransfers={onOpenTransfers}
          />
        ) : null}

        {targets.length > 0 ? (
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            <button
              type="button"
              disabled={!canSubmit}
              onClick={() => void command.submit()}
              className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-[10px] font-black text-white transition hover:bg-slate-800 disabled:opacity-40"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {command.pending
                ? t(
                    "inventoryBatches.disposition.retry",
                  )
                : t(
                    "inventoryBatches.disposition.apply",
                  )}
            </button>
            <button
              type="button"
              disabled={command.busy}
              onClick={onClose}
              className="min-h-9 rounded-lg px-3 text-[10px] font-black text-slate-500 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
