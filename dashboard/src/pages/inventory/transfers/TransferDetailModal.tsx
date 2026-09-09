import { Modal } from "@/components/ui/modal";
import { STATUS_META } from "./constants";
import type { WarehouseTransferDetail } from "./types";
import { formatDate } from "./utils";

interface TransferDetailModalProps {
  detail: WarehouseTransferDetail | null;
  loading: boolean;
  onClose: () => void;
}

export function TransferDetailModal({
  detail,
  loading,
  onClose,
}: TransferDetailModalProps) {
  return (
    <Modal
      isOpen={detail !== null || loading}
      onClose={onClose}
      title="تفاصيل الحوالة"
      maxWidth="max-w-5xl"
    >
      {loading && (
        <div className="p-12 text-center text-slate-500 font-bold">
          جاري جلب التفاصيل...
        </div>
      )}

      {!loading && detail && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">المرجع</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.reference_number}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">المصدر</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.source_location_name}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">الوجهة</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.destination_location_name}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">الحالة</div>
              <div className="font-bold text-slate-800">
                {STATUS_META[detail.transfer.status].label}
              </div>
            </div>
          </div>

          {(detail.transfer.notes || detail.transfer.decision_reason) && (
            <div className="rounded-xl border border-slate-200 p-4 text-sm">
              {detail.transfer.notes && (
                <p>
                  <span className="font-bold">ملاحظات:</span>{" "}
                  {detail.transfer.notes}
                </p>
              )}
              {detail.transfer.decision_reason && (
                <p className="mt-2">
                  <span className="font-bold">سبب القرار:</span>{" "}
                  {detail.transfer.decision_reason}
                </p>
              )}
            </div>
          )}

          <div className="border border-slate-200 rounded-xl overflow-auto max-h-[45vh]">
            <table className="w-full text-sm text-right">
              <thead className="bg-slate-50 sticky top-0">
                <tr>
                  <th className="p-3">المنتج</th>
                  <th className="p-3">الدفعة</th>
                  <th className="p-3">الصلاحية</th>
                  <th className="p-3">الكمية</th>
                  <th className="p-3">FEFO</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {detail.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="p-3 font-bold text-slate-800">
                      {line.product_name}
                    </td>
                    <td className="p-3 font-mono text-xs">
                      {line.batch_number}
                    </td>
                    <td className="p-3 text-xs text-slate-600">
                      {line.expiry_date}
                    </td>
                    <td className="p-3 font-bold">{line.quantity}</td>
                    <td className="p-3 text-xs">
                      {line.fefo_override_reason_id
                        ? `تجاوز موثّق: ${line.fefo_override_note || "بدون وصف"}`
                        : "FEFO تلقائي"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-slate-500">
            <div>
              المرسل:{" "}
              <span className="font-bold text-slate-700">
                {detail.transfer.dispatched_by_name}
              </span>
            </div>
            <div>
              المستلم:{" "}
              <span className="font-bold text-slate-700">
                {detail.transfer.received_by_name || "—"}
              </span>
            </div>
            <div>
              الإنشاء:{" "}
              <span className="font-bold text-slate-700">
                {formatDate(detail.transfer.created_at)}
              </span>
            </div>
            <div>
              الترحيل:{" "}
              <span className="font-bold text-slate-700">
                {formatDate(detail.transfer.posted_at)}
              </span>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
