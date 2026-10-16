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
import { resolveI18nLocale } from "@/lib/locale";
import { formatBatchDate } from "./batchPresentation";
import { BatchSellabilitySignal } from "./BatchIndexSignals";

import { BatchQuantityActions } from "./BatchQuantityActions";
import type { BatchActionSnapshot, BatchDisposition } from "./contracts";
import type { WarehouseBatchIndexItem } from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";
import type { BatchSpecialTransferResult } from "./batchSpecialTransferContract";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { ReservationOwner } from "./batchStockSourcesContract";
import { batchActionText } from "./batchActionsI18n";
import { StockStatusActionsPanel } from "./StockStatusActionsPanel";
import { useBatchDispositionCommand } from "./useBatchDispositionCommand";

type Props = {
  batch: BatchActionSnapshot | null;
  productVariantId: number | null;
  baseUomCode: string;
  selectedWarehouseId?: number | null;
  batchDetail?: WarehouseBatchIndexItem | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
  onRefreshBatch?: () => void | Promise<void>;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  showQuantityActions?: boolean;
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
  selectedWarehouseId = null,
  batchDetail = null,
  onClose,
  onChanged,
  onRefreshBatch,
  onOpenTransfers,
  onOpenReservationOwner,
  showQuantityActions = true,
}: Props) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const locale = resolveI18nLocale(i18n);
  const date = (value: string | null) => formatBatchDate(value, locale, actionText("noValue"));
  const access = useInventoryAccess();
  // Canonical Owner authority is already represented in the server permission
  // contract. Do not add a client-side Owner bypass around the capability.
  const canChange = access.can("batch.disposition");
  const targets = batch?.allowed_disposition_targets ?? [];
  const actionText = (
    key: Parameters<typeof batchActionText>[2],
    values: Record<string, unknown> = {},
  ) => batchActionText(t, language, key, values);
  const command = useBatchDispositionCommand({
    batch,
    canChange,
    onSucceeded: async () => {
      await onChanged();
      onClose();
    },
    onRevisionConflict: async () => {
      await (onRefreshBatch?.() ?? onChanged());
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
        batch: formatPublicBatchNumber(batch.batch_number, actionText("noLot")),
      })}
      subtitle={actionText("dispositionScope")}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-4">
        {batchDetail ? (
          <section className="rounded-xl border border-slate-200 bg-white p-3" aria-labelledby="cp3-batch-detail-title">
            <h3 id="cp3-batch-detail-title" className="text-xs font-black text-slate-950">
              {actionText("detailTitle")}
            </h3>
            <div className="mt-2 grid gap-x-4 gap-y-2 text-[10px] sm:grid-cols-2 lg:grid-cols-3">
              <p><span className="font-black">{actionText("product")}:</span> {batchDetail.product_name}</p>
              <p><span className="font-black">{actionText("sku")}:</span> {batchDetail.sku ?? actionText("noValue")}</p>
              <p><span className="font-black">{batchIndexText(t, language, "familyColumn")}:</span> {batchDetail.family_name}</p>
              <p><span className="font-black">{actionText("lot")}:</span> {formatPublicBatchNumber(batchDetail.batch_number, actionText("noLot"))}</p>
              <p><span className="font-black">{actionText("productionDate")}:</span> {date(batchDetail.production_date)}</p>
              <p><span className="font-black">{actionText("expiryDate")}:</span> {date(batchDetail.expiry_date)}</p>
              <p>
                <span className="font-black">{actionText("sellability")}:</span>{" "}
                {batchDetail.sellability_state === "SELLABLE" ? actionText("sellable") : actionText("notSellable")}
              </p>
              <p><span className="font-black">{actionText("baseUom")}:</span> {batchDetail.base_uom_name} ({batchDetail.base_uom_code})</p>
              <p><span className="font-black">{actionText("displayUom")}:</span> {batchDetail.display_uom_name} ({batchDetail.display_uom_code})</p>
              <p><span className="font-black">{actionText("dispositionRevision", { revision: String(batch.disposition_revision) })}</span></p>
            </div>
            <div className="mt-2">
              <BatchSellabilitySignal t={t} language={language} locale={locale} item={batchDetail} allReasons />
            </div>
            <div className="mt-3 rounded-lg bg-slate-50 p-2.5">
              <p className="text-[10px] font-black text-slate-700">{actionText("quantities")}</p>
              <div className="mt-1 grid gap-1 text-[9px] font-semibold text-slate-600 sm:grid-cols-2 lg:grid-cols-4">
                <span>{batchIndexText(t, language, "onHand")}: {batchDetail.on_hand_quantity} {batchDetail.base_uom_code}</span>
                <span>{batchIndexText(t, language, "reserved")}: {batchDetail.reserved_quantity} {batchDetail.base_uom_code}</span>
                <span>{batchIndexText(t, language, "available")}: {batchDetail.available_for_sale_quantity} {batchDetail.base_uom_code}</span>
                <span>{batchIndexText(t, language, "unavailable")}: {batchDetail.unavailable_quantity} {batchDetail.base_uom_code}</span>
              </div>
            </div>
          </section>
        ) : null}

        <section className="rounded-xl border border-violet-200 bg-violet-50/30 p-3" aria-labelledby="cp3-disposition-title">
          <h3 id="cp3-disposition-title" className="text-xs font-black text-slate-950">
            {actionText("dispositionTitle")}
          </h3>
          <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-600">
            {actionText("dispositionScope")}
          </p>
          <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
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
            <p className="mt-1 text-[9px] font-semibold text-slate-500">
              {actionText("dispositionRevision", { revision: String(batch.disposition_revision) })}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[9px] font-semibold text-slate-500">
              <span>
                {t("inventoryLive.expiryDate")}: {date(batch.expiry_date)}
              </span>
              {batch.days_to_expiry !== null ? (
                <span>
                  {batch.days_to_expiry < 0
                    ? t("inventoryLive.expiredSince", {
                        count: String(Math.abs(batch.days_to_expiry)),
                      })
                    : batch.days_to_expiry === 0
                      ? t("inventoryLive.expiresToday")
                      : t("inventoryLive.daysRemaining", {
                          count: String(batch.days_to_expiry),
                        })}
                </span>
              ) : null}
            </div>
          </div>

          {command.revisionConflict ? (
            <div role="alert" className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-[10px] font-bold leading-5 text-amber-950">
              {actionText("dispositionConflict")}
            </div>
          ) : null}

          {batch.disposition === "RECALLED" ? (
            <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/60 p-3 text-[11px] font-bold leading-5 text-rose-900">
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
            <div className="mt-3">
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
            <div className="mt-3">
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
            </div>
          ) : null}

          {command.pending ? (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-[10px] font-bold leading-5 text-amber-900">
              {t("inventoryBatches.disposition.pending")}
            </div>
          ) : null}

          {command.pendingBlocked ? (
            <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/70 p-3 text-[10px] font-bold leading-5 text-rose-900">
              {t("inventoryBatches.disposition.pendingBlocked")}
            </div>
          ) : null}

          {!canChange ? (
            <p className="mt-3 text-[10px] font-bold text-slate-500">
              {t("inventoryBatches.disposition.noPermission")}
            </p>
          ) : null}

          {targets.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2 border-t border-violet-100 pt-3">
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
            </div>
          ) : null}
        </section>

        {selectedWarehouseId !== null && productVariantId !== null ? (
          <StockStatusActionsPanel
            locationId={selectedWarehouseId}
            productVariantId={productVariantId}
            batchId={batch.batch_id}
            onChanged={onChanged}
          />
        ) : null}

        {showQuantityActions && productVariantId !== null ? (
          <BatchQuantityActions
            batch={batch}
            productVariantId={productVariantId}
            baseUomCode={baseUomCode}
            onChanged={onChanged}
            onOpenTransfers={onOpenTransfers}
            onOpenReservationOwner={onOpenReservationOwner}
          />
        ) : null}
      </div>
    </Modal>
  );
}
