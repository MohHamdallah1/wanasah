import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type { Quantity } from "@/lib/quantity";

import type {
  StatusChangeAvailability,
} from "./batchActionContracts";
import { batchActionText } from "./batchActionsI18n";
import type { BatchStockStatus } from "./batchStockSourcesContract";
import { useStockStatusCommand } from "./useStockStatusCommand";

type Props = {
  locationId: number;
  locationName: string;
  productVariantId: number;
  batchId: number;
  baseUomId: number;
  baseUomCode: string;
  quantityScale: number;
  quantityStep: Quantity;
  sourceStatus: BatchStockStatus;
  action: StatusChangeAvailability;
  reservedQuantity: Quantity;
  canChange: boolean;
  onClose: () => void;
  onSucceeded: () => void | Promise<void>;
};

export function StockStatusChangeDialog({
  locationId,
  locationName,
  productVariantId,
  batchId,
  baseUomId,
  baseUomCode,
  quantityScale,
  quantityStep,
  sourceStatus,
  action,
  reservedQuantity,
  canChange,
  onClose,
  onSucceeded,
}: Props) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const quantityRef = useRef<HTMLInputElement>(null);
  const command = useStockStatusCommand({
    locationId,
    productVariantId,
    batchId,
    baseUomId,
    sourceStatus,
    destinationStatus: action.destination_status,
    eligibleQuantity: action.eligible_quantity,
    quantityScale,
    quantityStep,
    canChange,
    onSucceeded: async () => {
      await onSucceeded();
      onClose();
    },
  });
  const text = (
    key: Parameters<typeof batchActionText>[2],
    values: Record<string, unknown> = {},
  ) => batchActionText(t, language, key, values);
  const statusLabel = (status: BatchStockStatus) =>
    text(`status_${status}` as Parameters<typeof batchActionText>[2]);

  const canSubmit =
    canChange &&
    action.allowed &&
    command.isOnline &&
    !command.busy &&
    !command.pendingBlocked &&
    (command.pending !== null || command.validationError === null);

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={text("stockStatusTitle")}
      subtitle={text("stockStatusScope")}
      maxWidth="max-w-lg"
      initialFocusRef={quantityRef}
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) void command.submit();
        }}
      >
        <div className="rounded-xl border border-blue-200 bg-blue-50/70 p-3 text-[11px] font-bold leading-5 text-blue-950">
          <p>{text("selectedWarehouse", { warehouse: locationName })}</p>
          <p>
            {text("sourceStatus")}: {statusLabel(sourceStatus)}
          </p>
          <p>
            {text("destinationStatus")}: {statusLabel(action.destination_status)}
          </p>
          <p>{text("eligible", { quantity: action.eligible_quantity, unit: baseUomCode })}</p>
          <p>{text("reserved", { quantity: reservedQuantity, unit: baseUomCode })}</p>
        </div>

        <label className="block">
          <span className="mb-1 block text-[11px] font-black text-slate-700">
            {text("quantity")}
          </span>
          <input
            ref={quantityRef}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={command.quantity}
            disabled={command.busy || command.pending !== null || command.pendingBlocked}
            onChange={(event) => command.setQuantity(event.target.value)}
            aria-describedby="cp3-status-quantity-hint"
            className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:bg-slate-100"
          />
          <span id="cp3-status-quantity-hint" className="mt-1 block text-[9px] font-semibold text-slate-500">
            {text("quantityHint", {
              unit: baseUomCode,
              scale: quantityScale,
              step: quantityStep,
            })}
          </span>
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] font-black text-slate-700">
            {text("reason")}
          </span>
          <textarea
            value={command.reason}
            disabled={command.busy || command.pending !== null || command.pendingBlocked}
            onChange={(event) => command.setReason(event.target.value)}
            maxLength={2000}
            rows={3}
            placeholder={text("reasonPlaceholder")}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:bg-slate-100"
          />
        </label>

        {command.validationError && command.pending === null ? (
          <p role="alert" className="text-[10px] font-bold text-rose-700">
            {command.validationError}
          </p>
        ) : null}
        {command.pending ? (
          <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] font-bold text-amber-900">
            {text("pending")}
          </p>
        ) : null}
        {command.pendingBlocked ? (
          <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-[10px] font-bold text-rose-900">
            {text("pendingBlocked")}
          </p>
        ) : null}

        <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={command.busy}
            className="min-h-10 rounded-lg border border-slate-200 bg-white px-4 text-[11px] font-black text-slate-700 focus-visible:ring-2 focus-visible:ring-slate-300 disabled:opacity-50"
          >
            {text("cancel")}
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="min-h-10 rounded-lg bg-slate-950 px-4 text-[11px] font-black text-white focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-40"
          >
            {command.pending ? text("retry") : text("apply")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
