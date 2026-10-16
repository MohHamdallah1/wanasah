import { Ban, CheckCircle2, XCircle } from "lucide-react";
import { useTransferTranslation as useTranslation } from "./i18n";
import { Modal } from "@/components/ui/modal";
import type {
  TransferAction,
  WarehouseTransferListItem,
} from "./types";

interface TransferDecisionModalProps {
  action: TransferAction | null;
  transfer: WarehouseTransferListItem | null;
  decisionReason: string;
  submitting: boolean;
  pending?: boolean;
  retrying?: boolean;
  onRetry?: () => void | Promise<void>;
  onClose: () => void;
  onDecisionReasonChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
}

export function TransferDecisionModal({
  action,
  transfer,
  decisionReason,
  submitting,
  pending = false,
  retrying = false,
  onRetry,
  onClose,
  onDecisionReasonChange,
  onSubmit,
}: TransferDecisionModalProps) {
  const { t } = useTranslation();
  const title = action === "receive"
    ? t("inventoryTransfers.receiveTitle")
    : action === "reject"
      ? t("inventoryTransfers.rejectTitle")
      : t("inventoryTransfers.cancelTitle");
  const tone = action === "receive"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : action === "reject"
      ? "border-red-200 bg-red-50 text-red-900"
      : "border-amber-200 bg-amber-50 text-amber-950";
  const submitTone = action === "receive"
    ? "bg-emerald-600 hover:bg-emerald-700 focus-visible:ring-emerald-300"
    : action === "reject"
      ? "bg-red-600 hover:bg-red-700 focus-visible:ring-red-300"
      : "bg-amber-600 hover:bg-amber-700 focus-visible:ring-amber-300";
  const DecisionIcon = action === "receive"
    ? CheckCircle2
    : action === "reject"
      ? XCircle
      : Ban;

  return (
    <Modal
      isOpen={action !== null && transfer !== null}
      onClose={onClose}
      title={title}
    >
      {pending ? (
        <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
          <p>{t("inventoryTransfers.pending")}</p>
          <button
            type="button"
            disabled={retrying}
            onClick={() => void onRetry?.()}
            className="rounded-lg border border-amber-200 bg-white px-2.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-amber-300 disabled:opacity-50"
          >
            {t("inventoryTransfers.retry")}
          </button>
        </div>
      ) : null}

      <form
        className="space-y-3"
        data-cp13-transfer-decision={action ?? undefined}
        onSubmit={(event) => {
          event.preventDefault();
          void onSubmit();
        }}
      >
        <div className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 ${tone}`}>
          <DecisionIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <div className="text-xs font-black">{title}</div>
            <div className="mt-1 grid grid-cols-1 gap-1 text-[11px] sm:grid-cols-2">
              <div className="min-w-0">
                <span className="font-bold opacity-70">{t("inventoryTransfers.source")}: </span>
                <span className="font-black">{transfer?.source_location_name}</span>
              </div>
              <div className="min-w-0">
                <span className="font-bold opacity-70">{t("inventoryTransfers.destination")}: </span>
                <span className="font-black">{transfer?.destination_location_name}</span>
              </div>
            </div>
            <div className="mt-1 text-[10px] font-semibold opacity-80">{transfer?.reference_number}</div>
          </div>
        </div>

        {action !== "receive" ? (
          <label className="block text-xs font-bold text-slate-700">
            {t("inventoryTransfers.decisionReason")}
            <textarea
              aria-label={t("inventoryTransfers.decisionReason")}
              aria-required="true"
              disabled={submitting}
              value={decisionReason}
              onChange={(event) => onDecisionReasonChange(event.target.value)}
              maxLength={2000}
              className="mt-1 min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:opacity-60"
            />
          </label>
        ) : null}

        {action === "receive" ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-900">
            {t("inventoryTransfers.receiveHint")}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={submitting}
          className={`w-full rounded-xl py-2.5 text-xs font-black text-white outline-none disabled:opacity-50 focus-visible:ring-2 ${submitTone}`}
          data-cp13-action-priority="primary"
        >
          {submitting
            ? t("inventoryTransfers.executing")
            : action === "receive"
              ? t("inventoryTransfers.confirmReceive")
              : action === "reject"
                ? t("inventoryTransfers.confirmReject")
                : t("inventoryTransfers.confirmCancel")}
        </button>
      </form>
    </Modal>
  );
}
