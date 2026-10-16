import { ArrowRight } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";

import type { StatusChangeAvailability } from "./batchActionContracts";
import { batchActionText } from "./batchActionsI18n";
import type { BatchStockStatus } from "./batchStockSourcesContract";
import { StockStatusChangeDialog } from "./StockStatusChangeDialog";
import { useWarehouseBatchActionSource } from "./useWarehouseBatchActionSource";

type Choice = {
  sourceStatus: BatchStockStatus;
  reservedQuantity: string;
  action: StatusChangeAvailability;
};

type Props = {
  locationId: number;
  productVariantId: number;
  batchId: number;
  onChanged: () => void | Promise<void>;
};

export function StockStatusActionsPanel({
  locationId,
  productVariantId,
  batchId,
  onChanged,
}: Props) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const access = useInventoryAccess(locationId);
  const query = useWarehouseBatchActionSource(locationId, productVariantId, batchId);
  const [choice, setChoice] = useState<Choice | null>(null);
  const text = (
    key: Parameters<typeof batchActionText>[2],
    values: Record<string, unknown> = {},
  ) => batchActionText(t, language, key, values);
  const statusLabel = (status: BatchStockStatus) =>
    text(`status_${status}` as Parameters<typeof batchActionText>[2]);
  const canChange = access.can("inventory.status_change");

  const reasonMessages = useMemo(() => {
    const seen = new Set<string>();
    return (query.data?.statuses ?? []).flatMap((status) =>
      status.status_change_actions
        .filter((action) => !action.allowed && action.reason_code !== "PERMISSION_REQUIRED")
        .filter((action) => {
          const key = `${status.stock_status}:${action.reason_code}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        }),
    );
  }, [query.data?.statuses]);

  return (
    <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/30 p-3" aria-labelledby="cp3-stock-status-title">
      <div>
        <h3 id="cp3-stock-status-title" className="text-xs font-black text-slate-950">
          {text("stockStatusTitle")}
        </h3>
        <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-600">
          {text("stockStatusScope")}
        </p>
      </div>

      {query.isLoading || access.isPending ? (
        <p role="status" className="text-[10px] font-bold text-slate-500">{t("common.loading")}</p>
      ) : query.isError || access.isError || !query.data ? (
        <div role="alert" className="rounded-lg border border-rose-200 bg-white p-2.5 text-[10px] font-bold text-rose-800">
          <p>{text("saveError")}</p>
          <button
            type="button"
            onClick={() => void Promise.all([query.refetch(), access.refetch()])}
            className="mt-2 rounded-md border px-2 py-1 focus-visible:ring-2"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : (
        <>
          <p className="text-[10px] font-black text-blue-950">
            {text("selectedWarehouse", { warehouse: query.data.location_name })}
          </p>
          {!canChange ? (
            <p className="rounded-lg border border-slate-200 bg-white p-2.5 text-[10px] font-semibold text-slate-600">
              {text("permissionReadOnly")}
            </p>
          ) : null}

          <div className="space-y-2">
            {query.data.statuses.map((status) => {
              const allowed = status.status_change_actions.filter((action) => action.allowed);
              return (
                <div key={status.stock_status} className="rounded-xl border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="text-[11px] font-black text-slate-900">
                      {statusLabel(status.stock_status)}
                    </p>
                    <div className="text-end text-[9px] font-semibold leading-4 text-slate-500">
                      <p>{text("onHand", { quantity: status.on_hand_quantity, unit: query.data.base_uom_code })}</p>
                      <p>{text("reserved", { quantity: status.reserved_quantity, unit: query.data.base_uom_code })}</p>
                      <p className="font-black text-slate-900">
                        {text("eligible", { quantity: status.movable_quantity, unit: query.data.base_uom_code })}
                      </p>
                    </div>
                  </div>
                  {canChange && allowed.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {allowed.map((action) => (
                        <button
                          key={action.destination_status}
                          type="button"
                          onClick={() => setChoice({
                            sourceStatus: status.stock_status,
                            reservedQuantity: status.reserved_quantity,
                            action,
                          })}
                          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 text-[10px] font-black text-blue-950 outline-none hover:bg-blue-100 focus-visible:ring-2 focus-visible:ring-blue-300"
                        >
                          {text("changeStatus")}: {statusLabel(action.destination_status)}
                          <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden="true" />
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {canChange && query.data.statuses.every(
            (status) => status.status_change_actions.every((action) => !action.allowed),
          ) ? (
            <p className="text-[10px] font-bold text-slate-600">{text("noStatusActions")}</p>
          ) : null}
          {reasonMessages.map((action) => (
            <p key={`${action.destination_status}:${action.reason_code}`} className="text-[9px] font-semibold text-slate-500">
              {text(`actionReason_${action.reason_code}` as Parameters<typeof batchActionText>[2])}
            </p>
          ))}
        </>
      )}

      {choice && query.data ? (
        <StockStatusChangeDialog
          locationId={locationId}
          locationName={query.data.location_name}
          productVariantId={productVariantId}
          batchId={batchId}
          baseUomId={query.data.base_uom_id}
          baseUomCode={query.data.base_uom_code}
          quantityScale={query.data.quantity_scale}
          quantityStep={query.data.quantity_step}
          sourceStatus={choice.sourceStatus}
          action={choice.action}
          reservedQuantity={choice.reservedQuantity}
          canChange={canChange}
          onClose={() => setChoice(null)}
          onSucceeded={async () => {
            await query.refetch();
            await onChanged();
          }}
        />
      ) : null}
    </section>
  );
}
