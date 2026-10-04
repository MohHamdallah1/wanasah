import {
  AlertTriangle,
  ArrowRightLeft,
  RotateCcw,
  ShieldAlert,
  Trash2,
  Truck,
  Warehouse,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import type { WarehouseBatchInventoryItem } from "@/pages/inventory/liveStock/contracts";
import {
  compareQuantity,
  type Quantity,
} from "@/lib/quantity";

import type {
  BatchSpecialTransferPurpose,
} from "./batchSpecialTransferContract";
import type {
  BatchStockSource,
  BatchStockSourceStatus,
  BatchStockStatus,
} from "./batchStockSourcesContract";
import { useBatchSpecialTransfer } from "./useBatchSpecialTransfer";
import { useBatchStockSources } from "./useBatchStockSources";

type Props = {
  batch: WarehouseBatchInventoryItem;
  productVariantId: number;
  baseUomCode: string;
  onChanged: () => void | Promise<void>;
  onOpenTransfers: () => void;
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

const allowedPurposes = (
  batchDisposition: WarehouseBatchInventoryItem["disposition"],
  operationalHold: "NONE" | "SALES_HOLD" | "RECALL",
  sourceStatus: BatchStockStatus,
  metadataRestricted: boolean,
): BatchSpecialTransferPurpose[] => {
  const result: BatchSpecialTransferPurpose[] = [];
  const unsafeOrRestricted =
    sourceStatus !== "AVAILABLE" ||
    batchDisposition !== "RELEASED" ||
    operationalHold !== "NONE" ||
    metadataRestricted;

  if (
    operationalHold === "RECALL" &&
    sourceStatus !== "DAMAGED" &&
    sourceStatus !== "DISPOSAL_PENDING"
  ) {
    result.push("RECALL_RETURN");
  }

  if (
    batchDisposition !== "BLOCKED" &&
    sourceStatus !== "BLOCKED" &&
    sourceStatus !== "DAMAGED" &&
    sourceStatus !== "DISPOSAL_PENDING" &&
    unsafeOrRestricted
  ) {
    result.push("QUARANTINE");
  }

  const returnable =
    sourceStatus === "QUARANTINED" ||
    sourceStatus === "BLOCKED" ||
    sourceStatus === "DAMAGED" ||
    batchDisposition === "QUARANTINED" ||
    batchDisposition === "BLOCKED" ||
    metadataRestricted;
  if (
    operationalHold !== "RECALL" &&
    batchDisposition !== "RECALLED" &&
    sourceStatus !== "RECALLED" &&
    sourceStatus !== "DISPOSAL_PENDING" &&
    returnable
  ) {
    result.push("RETURN_TO_VENDOR");
  }

  if (unsafeOrRestricted) {
    result.push("DISPOSAL");
  }

  return result;
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
}: Props) {
  const { t } = useTranslation();
  const access = useInventoryAccess();
  const stockQuery = useBatchStockSources(batch.batch_id);
  const transfer = useBatchSpecialTransfer({
    batch,
    productVariantId,
    onSucceeded: async () => {
      await stockQuery.refetch();
      await onChanged();
    },
  });
  const [choice, setChoice] = useState<Choice | null>(null);
  const data = stockQuery.data;

  const stockRows = useMemo(
    () =>
      data?.sources.flatMap((source) =>
        source.statuses.map((status) => ({ source, status })),
      ) ?? [],
    [data],
  );

  if (stockQuery.isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 text-[10px] font-bold text-slate-500">
        {t("inventoryBatches.quantityActions.loading")}
      </div>
    );
  }

  if (stockQuery.isError || !data) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3">
        <p className="text-[10px] font-bold text-rose-800">
          {t("inventoryBatches.quantityActions.errors.load")}
        </p>
        <button
          type="button"
          onClick={() => void stockQuery.refetch()}
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
      <div>
        <p className="text-xs font-black text-slate-950">
          {t("inventoryBatches.quantityActions.title")}
        </p>
        <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
          {t("inventoryBatches.quantityActions.hint")}
        </p>
      </div>

      {stockRows.length === 0 ? (
        <p className="rounded-lg bg-white p-2.5 text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">
          {t("inventoryBatches.quantityActions.noMovable")}
        </p>
      ) : (
        <div className="space-y-2">
          {stockRows.map(({ source, status }) => {
            const purposes = allowedPurposes(
              batch.disposition,
              data.operational_hold,
              status.stock_status,
              batch.days_to_expiry !== null && batch.days_to_expiry < 0,
            );
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

                {compareQuantity(status.movable_quantity, "0") <= 0 ? (
                  <p className="mt-2 text-[9px] font-semibold leading-4 text-amber-700">
                    {t("inventoryBatches.quantityActions.fullyReserved")}
                  </p>
                ) : !source.can_send ? (
                  <p className="mt-2 text-[9px] font-semibold leading-4 text-slate-500">
                    {t("inventoryBatches.quantityActions.noSendPermission")}
                  </p>
                ) : purposes.length > 0 ? (
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
                  </div>
                ) : (
                  <p className="mt-2 text-[9px] font-semibold leading-4 text-slate-500">
                    {t("inventoryBatches.quantityActions.noActionForStatus")}
                  </p>
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
                const ok = await transfer.run({
                  purpose: choice.purpose,
                  sourceLocationId: choice.source.location_id,
                  sourceStatus: choice.status.stock_status,
                  quantity: choice.status.movable_quantity as Quantity,
                  baseUomId: data.base_uom_id,
                });
                if (ok === true) setChoice(null);
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

      <button
        type="button"
        onClick={onOpenTransfers}
        className="inline-flex items-center gap-1.5 text-[9px] font-black text-slate-600 underline underline-offset-4 hover:text-slate-950"
      >
        <ArrowRightLeft className="h-3.5 w-3.5" />
        {t("inventoryBatches.quantityActions.openTransfers")}
      </button>
    </div>
  );
}
