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
  onClose: () => void;
  onDecisionReasonChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
}

export function TransferDecisionModal({
  action,
  transfer,
  decisionReason,
  submitting,
  onClose,
  onDecisionReasonChange,
  onSubmit,
}: TransferDecisionModalProps) {
  return (
    <Modal
      isOpen={action !== null && transfer !== null}
      onClose={onClose}
      title={
        action === "receive"
          ? "تأكيد استلام الحوالة"
          : action === "reject"
            ? "رفض الحوالة"
            : "إلغاء الحوالة"
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-sm">
          <div className="font-bold text-slate-800">
            {transfer?.reference_number}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {transfer?.source_location_name} ←{" "}
            {transfer?.destination_location_name}
          </div>
        </div>

        {action !== "receive" && (
          <div>
            <label className="text-xs font-bold text-slate-600">
              سبب {action === "reject" ? "الرفض" : "الإلغاء"}
            </label>
            <textarea
              value={decisionReason}
              onChange={(event) =>
                onDecisionReasonChange(event.target.value)
              }
              maxLength={2000}
              className="mt-1 w-full min-h-28 rounded-xl border border-slate-200 px-3 py-2.5 outline-none focus:ring-2 focus:ring-blue-500/20"
            />
          </div>
        )}

        {action === "receive" && (
          <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 font-bold">
            سيتم نقل كامل أسطر الحوالة من IN_TRANSIT إلى وجهتها الأصلية.
            السيرفر يمنع المُرسل من تأكيد استلام حوالته بنفسه.
          </div>
        )}

        <button
          onClick={() => void onSubmit()}
          disabled={submitting}
          className={`w-full py-3 rounded-xl text-white font-bold disabled:opacity-50 ${
            action === "receive"
              ? "bg-emerald-600"
              : action === "reject"
                ? "bg-red-600"
                : "bg-amber-600"
          }`}
        >
          {submitting
            ? "جاري التنفيذ..."
            : action === "receive"
              ? "تأكيد الاستلام"
              : action === "reject"
                ? "تأكيد الرفض"
                : "تأكيد الإلغاء"}
        </button>
      </div>
    </Modal>
  );
}
