import {
  AlertTriangle,
  ArrowRightLeft,
  RotateCcw,
  ShieldAlert,
  Trash2,
  Truck,
  Warehouse,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import {
  compareQuantity,
  type Quantity,
} from "@/lib/quantity";

import type {
  BatchSpecialTransferPurpose,
  BatchSpecialTransferResult,
} from "./batchSpecialTransferContract";
import type { BatchActionSnapshot } from "./contracts";
import type {
  BatchStockSource,
  BatchStockSources,
  BatchStockSourceStatus,
  BatchStockStatus,
  ReservationOwner,
} from "./batchStockSourcesContract";
import { useBatchSpecialTransfer } from "./useBatchSpecialTransfer";
import { BatchTerminalActionDialog, type BatchTerminalChoice } from "./BatchTerminalActionDialog";
import { useBatchTerminalAction } from "./useBatchTerminalAction";
import { useBatchStockSources } from "./useBatchStockSources";

type Props = {
  batch: BatchActionSnapshot;
  productVariantId: number;
  baseUomCode: string;
  onChanged: () => void | Promise<void>;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onConfigureQualityDestinations?: () => void;
  stockSources?: BatchStockSources;
  onRefreshStockSources?: () => Promise<void>;
  showTransferListLink?: boolean;
  header?: ReactNode;
  suppressDestinationSetupPrompt?: boolean;
};

type Choice = {
  purpose: BatchSpecialTransferPurpose;
  source: BatchStockSource;
  status: BatchStockSourceStatus;
};

const purposePermission: Record<
  BatchSpecialTransferPurpose,
  string
> = {
  QUARANTINE: "transfer.special.quarantine",
  RECALL_RETURN: "transfer.special.recall_return",
  RETURN_TO_VENDOR: "transfer.special.return_to_vendor",
  DISPOSAL: "transfer.special.disposal",
};

const purposeIcon = (
  purpose: BatchSpecialTransferPurpose,
) => {
  if (purpose === "QUARANTINE") {
    return <ShieldAlert className="h-3.5 w-3.5" />;
  }
  if (purpose === "RECALL_RETURN") {
    return <RotateCcw className="h-3.5 w-3.5" />;
  }
  if (purpose === "RETURN_TO_VENDOR") {
    return <Truck className="h-3.5 w-3.5" />;
  }
  return <Trash2 className="h-3.5 w-3.5" />;
};

const choiceKey = (choice: Choice) =>
  [
    choice.source.location_id,
    choice.status.stock_status,
    choice.purpose,
  ].join(":");

export function BatchQuantityActions({
  batch,
  productVariantId,
  baseUomCode,
  onChanged,
  onOpenTransfers,
  onOpenReservationOwner,
  onConfigureQualityDestinations,
  stockSources,
  onRefreshStockSources,
  showTransferListLink = false,
  header,
  suppressDestinationSetupPrompt = false,
}: Props) {
  const { t } = useTranslation();
  const access = useInventoryAccess();
  const stockQuery = useBatchStockSources(
    batch.batch_id,
    stockSources === undefined,
  );
  const refreshStockSources = async () => {
    if (onRefreshStockSources) {
      await onRefreshStockSources();
      return;
    }
    await stockQuery.refetch();
  };
  const transfer = useBatchSpecialTransfer({
    batch,
    productVariantId,
    onSucceeded: async () => {
      await refreshStockSources();
      await onChanged();
    },
  });
  const [choice, setChoice] = useState<Choice | null>(null);
  const [terminalChoice, setTerminalChoice] = useState<BatchTerminalChoice | null>(null);
  const [lastTransfer, setLastTransfer] =
    useState<BatchSpecialTransferResult | null>(null);
  const terminal = useBatchTerminalAction({
    batch,
    productVariantId,
    baseUomCode,
    onSucceeded: async () => {
      await refreshStockSources();
      await onChanged();
    },
  });
  const data = stockSources ?? stockQuery.data;

  const stockRows = useMemo(
    () =>
      data?.sources.flatMap((source) =>
        source.statuses.map((status) => ({ source, status })),
      ) ?? [],
    [data],
  );

  if (stockSources === undefined && stockQuery.isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 text-[10px] font-bold text-slate-500">
        {t("inventoryBatches.quantityActions.loading")}
      </div>
    );
  }

  if ((stockSources === undefined && stockQuery.isError) || !data) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3">
        <p className="text-[10px] font-bold text-rose-800">
          {t("inventoryBatches.quantityActions.errors.load")}
        </p>
        <button
          type="button"
          onClick={() => void refreshStockSources()}
          className="mt-2 text-[10px] font-black underline underline-offset-4"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  if (data.product_variant_id !== productVariantId) {
    return null;
  }

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/40 p-3">
      {header ?? <div>
        <p className="text-xs font-black text-slate-950">
          {t("inventoryBatches.quantityActions.title")}
        </p>
        <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
          {t("inventoryBatches.quantityActions.hint")}
        </p>
      </div>}

      {stockRows.length === 0 ? (
        <p className="rounded-lg bg-white p-2.5 text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">
          {t("inventoryBatches.quantityActions.noMovable")}
        </p>
      ) : (
        <div className="space-y-2">
          {stockRows.map(({ source, status }) => {
            const purposes = status.allowed_purposes;
            const key = `${source.location_id}:${status.stock_status}`;
            return (
              <div
                key={key}
                className="rounded-xl border border-slate-200 bg-white p-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="mt-0.5 text-slate-400">
                      {source.location_type === "VEHICLE" ? (
                        <Truck className="h-4 w-4" />
                      ) : (
                        <Warehouse className="h-4 w-4" />
                      )}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-[11px] font-black text-slate-900">
                        {source.location_name}
                      </p>
                      <p className="mt-0.5 text-[9px] font-semibold text-slate-500">
                        {t(
                          `inventoryBatches.quantityActions.locationTypes.${source.location_type}`,
                        )}
                        {" · "}
                        {t(
                          `inventoryBatches.quantityActions.stockStatuses.${status.stock_status}`,
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="text-end text-[9px] font-semibold leading-4 text-slate-500">
                    <p>
                      {t("inventoryBatches.quantityActions.onHand", {
                        quantity: status.on_hand_quantity,
                        unit: baseUomCode,
                      })}
                    </p>
                    <p className="font-black text-slate-900">
                      {t("inventoryBatches.quantityActions.movable", {
                        quantity: status.movable_quantity,
                        unit: baseUomCode,
                      })}
                    </p>
                    {compareQuantity(
                      status.reserved_quantity,
                      "0",
                    ) > 0 ? (
                      <p className="font-bold text-amber-700">
                        {t("inventoryBatches.quantityActions.reserved", {
                          quantity: status.reserved_quantity,
                          unit: baseUomCode,
                        })}
                      </p>
                    ) : null}
                  </div>
                </div>

                {compareQuantity(status.reserved_quantity, "0") > 0 ? (
                  <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50/60 p-2.5">
                    <p className="text-[9px] font-black text-amber-950">
                      {t("inventoryBatches.quantityActions.reservationEvidence.title")}
                    </p>
                    {status.reservation_evidence.owners.length > 0 ? (
                      <div className="mt-1.5 space-y-1.5">
                        {status.reservation_evidence.owners.map((owner) => (
                          <div
                            key={owner.transfer_id}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-white/80 px-2 py-1.5 ring-1 ring-amber-100"
                          >
                            <div className="min-w-0 text-[9px] font-semibold leading-4 text-slate-700">
                              <p className="font-black text-slate-900">
                                {t(
                                  `inventoryBatches.quantityActions.reservationEvidence.purposes.${owner.transfer_purpose}`,
                                  { reference: owner.reference_number },
                                )}
                              </p>
                              <p>
                                {t("inventoryBatches.quantityActions.reservationEvidence.ownerQuantity", {
                                  quantity: owner.quantity,
                                  unit: baseUomCode,
                                })}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => onOpenReservationOwner(owner)}
                              className="shrink-0 rounded-md border border-amber-200 bg-white px-2 py-1 text-[9px] font-black text-amber-900 hover:bg-amber-100"
                            >
                              {t(
                                owner.action === "FORCE_CANCEL_HANDSHAKE"
                                  ? "inventoryBatches.quantityActions.reservationEvidence.openAndRelease"
                                  : "inventoryBatches.quantityActions.reservationEvidence.openOwner",
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {compareQuantity(
                      status.reservation_evidence.unattributed_quantity,
                      "0",
                    ) > 0 ? (
                      <p className="mt-1.5 text-[9px] font-semibold leading-4 text-amber-800">
                        {t("inventoryBatches.quantityActions.reservationEvidence.unattributed", {
                          quantity: status.reservation_evidence.unattributed_quantity,
                          unit: baseUomCode,
                        })}
                      </p>
                    ) : null}
                    {status.reservation_evidence.owners_truncated ? (
                      <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
                        {t("inventoryBatches.quantityActions.reservationEvidence.previewLimited")}
                      </p>
                    ) : null}
                  </div>
                ) : null}

                {(purposes.length > 0 || status.terminal_actions.some((action) => action.allowed)) ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {purposes.map((purpose) => {
                      const permitted =
                        access.isCompanyAdmin ||
                        access.can(purposePermission[purpose]);
                      return (
                        <button
                          key={purpose}
                          type="button"
                          disabled={
                            !permitted ||
                            !transfer.isOnline ||
                            transfer.busyKey !== null
                          }
                          onClick={() =>
                            setChoice({
                              purpose,
                              source,
                              status,
                            })
                          }
                          className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[9px] font-black text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {purposeIcon(purpose)}
                          {t(
                            `inventoryBatches.quantityActions.purposes.${purpose}.label`,
                          )}
                        </button>
                      );
                    })}
                    {status.terminal_actions.filter((action) => action.allowed).map((availability) => (
                      <button key={availability.action} type="button" disabled={!terminal.isOnline || terminal.busyKey !== null}
                        onClick={() => setTerminalChoice({ availability, source, status })}
                        className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 text-[9px] font-black text-emerald-900 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-40">
                        {availability.action === "CONFIRM_DISPOSAL" ? <Trash2 className="h-3.5 w-3.5" /> : <Truck className="h-3.5 w-3.5" />}
                        {t(`terminalQualityActions.actions.${availability.action}.label`)}
                      </button>
                    ))}
                  </div>
                ) : status.special_actions.some(
                    (action) => action.reason_code === "NO_CONFIGURED_DESTINATION",
                  ) ? (
                  suppressDestinationSetupPrompt ? null : (
                    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50/70 p-3">
                    <p className="text-[10px] font-black text-amber-950">
                      {t("qualityActionReasons.setupRequiredTitle")}
                    </p>
                    <p className="mt-1 text-[9px] font-semibold leading-4 text-amber-900/80">
                      {t("qualityActionReasons.setupRequiredHint")}
                    </p>
                    {onConfigureQualityDestinations ? (
                      <button
                        type="button"
                        onClick={onConfigureQualityDestinations}
                        className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-[9px] font-black text-amber-950 focus-visible:ring-2 focus-visible:ring-amber-300"
                      >
                        {t("qualityActionReasons.configure")}
                      </button>
                    ) : null}
                    </div>
                  )
                ) : (
                  <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
                    <p className="text-[9px] font-black text-slate-700">
                      {t("qualityActionReasons.title")}
                    </p>
                    <div className="mt-1.5 space-y-1">
                      {status.special_actions
                        .filter(
                          (action) =>
                            !(
                              data?.operational_hold === "RECALL" &&
                              action.purpose === "QUARANTINE"
                            ),
                        )
                        .map((action) => (
                          <p key={action.purpose} className="text-[9px] font-semibold leading-4 text-slate-600">
                            <span className="font-black text-slate-800">
                              {t(`inventoryBatches.quantityActions.purposes.${action.purpose}.label`)}:
                            </span>{" "}
                            {t(`qualityActionReasons.reasons.${action.reason_code}`)}
                          </p>
                        ))}
                      {status.terminal_actions.map((action) => (
                        <p key={action.action} className="text-[9px] font-semibold leading-4 text-slate-600">
                          <span className="font-black text-slate-800">{t(`terminalQualityActions.actions.${action.action}.label`)}:</span>{" "}
                          {t(`terminalQualityActions.reasons.${action.reason_code}`)}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {choice ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
            <div>
              <p className="text-[11px] font-black text-amber-950">
                {t(
                  `inventoryBatches.quantityActions.purposes.${choice.purpose}.confirmTitle`,
                )}
              </p>
              <p className="mt-1 text-[9px] font-semibold leading-4 text-amber-900/80">
                {t(
                  `inventoryBatches.quantityActions.purposes.${choice.purpose}.confirmHint`,
                  {
                    quantity: choice.status.movable_quantity,
                    unit: baseUomCode,
                    source: choice.source.location_name,
                  },
                )}
              </p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={transfer.busyKey !== null}
              onClick={async () => {
                const result = await transfer.run({
                  purpose: choice.purpose,
                  sourceLocationId: choice.source.location_id,
                  sourceStatus: choice.status.stock_status,
                  quantity: choice.status.movable_quantity as Quantity,
                  baseUomId: data.base_uom_id,
                });
                if (result) {
                  setChoice(null);
                  setLastTransfer(result);
                }
              }}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-slate-950 px-4 text-[10px] font-black text-white hover:bg-slate-800 disabled:opacity-40"
            >
              <ArrowRightLeft className="h-3.5 w-3.5" />
              {t("inventoryBatches.quantityActions.confirm")}
            </button>
            <button
              type="button"
              disabled={transfer.busyKey !== null}
              onClick={() => setChoice(null)}
              className="min-h-9 rounded-lg px-3 text-[10px] font-black text-slate-600 hover:bg-white disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {terminalChoice ? (
        <BatchTerminalActionDialog choice={terminalChoice} baseUomCode={baseUomCode}
          busy={terminal.busyKey !== null} online={terminal.isOnline} onClose={() => setTerminalChoice(null)}
          onConfirm={async (evidence) => {
            const result = await terminal.run({
              action: terminalChoice.availability.action,
              sourceLocationId: terminalChoice.source.location_id,
              sourceStatus: terminalChoice.status.stock_status,
              ...evidence,
            });
            if (result) setTerminalChoice(null);
          }} />
      ) : null}

      {lastTransfer ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-2.5">
          <p className="text-[9px] font-bold text-emerald-800">
            {t("inventoryBatches.quantityActions.createdReference", {
              reference: lastTransfer.transfer_reference,
            })}
          </p>
          <button
            type="button"
            onClick={() => onOpenTransfers(lastTransfer)}
            className="mt-1 inline-flex items-center gap-1.5 text-[9px] font-black text-emerald-900 underline underline-offset-4"
          >
            <ArrowRightLeft className="h-3.5 w-3.5" />
            {t("inventoryBatches.quantityActions.followCreatedTransfer")}
          </button>
        </div>
      ) : null}

      {showTransferListLink && <button
        type="button"
        onClick={() => onOpenTransfers()}
        className="inline-flex items-center gap-1.5 text-[9px] font-black text-slate-600 underline underline-offset-4 hover:text-slate-950"
      >
        <ArrowRightLeft className="h-3.5 w-3.5" />
        {t("inventoryBatches.quantityActions.openTransfers")}
      </button>}
    </div>
  );
}
