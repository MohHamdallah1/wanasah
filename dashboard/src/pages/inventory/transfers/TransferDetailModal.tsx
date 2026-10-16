import { Modal } from "@/components/ui/modal";
import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { formatTransferDateOnly } from "./utils";
import { formatPublicBatchNumber } from "../publicBatchNumber";
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
  const { t } = useTranslation();
  return (
    <Modal
      isOpen={detail !== null || loading}
      onClose={onClose}
      title={t("inventoryTransfers.detailTitle")}
      maxWidth="max-w-5xl"
    >
      {loading && (
        <div className="p-12 text-center text-slate-500 font-bold">{t("inventoryTransfers.detailLoading")}</div>
      )}

      {!loading && detail && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">{t("inventoryTransfers.reference")}</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.reference_number}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">{t("inventoryTransfers.source")}</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.source_location_name}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">{t("inventoryTransfers.destination")}</div>
              <div className="font-bold text-slate-800">
                {detail.transfer.destination_location_name}
              </div>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <div className="text-[10px] text-slate-400">{t("inventoryTransfers.status")}</div>
              <div className="font-bold text-slate-800">
                {t(STATUS_META[detail.transfer.status].label)}
              </div>
            </div>
          </div>

          {(detail.transfer.notes || detail.transfer.decision_reason) && (
            <div className="rounded-xl border border-slate-200 p-4 text-sm">
              {detail.transfer.notes && (
                <p>
                  <span className="font-bold">{t("inventoryTransfers.notesLabel")}</span>{" "}
                  {detail.transfer.notes}
                </p>
              )}
              {detail.transfer.decision_reason && (
                <p className="mt-2">
                  <span className="font-bold">{t("inventoryTransfers.reasonLabel")}</span>{" "}
                  {detail.transfer.decision_reason}
                </p>
              )}
            </div>
          )}

          <div className="border border-slate-200 rounded-xl overflow-auto max-h-[45vh]">
            <table className="w-full text-sm text-start">
              <thead className="bg-slate-50 sticky top-0">
                <tr>
                  <th className="p-3">{t("inventoryTransfers.product")}</th>
                  <th className="p-3">{t("inventoryTransfers.batch")}</th>
                  <th className="p-3">{t("inventoryTransfers.expiry")}</th>
                  <th className="p-3">{t("inventoryTransfers.quantity")}</th>
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
                      {formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}
                    </td>
                    <td className="p-3 text-xs text-slate-600">
                      {formatTransferDateOnly(line.expiry_date)}
                    </td>
                    <td className="p-3 font-bold">{formatTransferNumber(line.quantity)}</td>
                    <td className="p-3 text-xs">
                      {line.fefo_override_reason_id
                        ? t("inventoryTransfers.overrideEvidence", { note: line.fefo_override_note || t("inventoryTransfers.noDescription") })
                        : t("inventoryTransfers.fefoAuto")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-slate-500">
            <div>
              {t("inventoryTransfers.sender")}{" "}
              <span className="font-bold text-slate-700">
                {detail.transfer.dispatched_by_name}
              </span>
            </div>
            <div>
              {t("inventoryTransfers.receiver")}{" "}
              <span className="font-bold text-slate-700">
                {detail.transfer.received_by_name || "—"}
              </span>
            </div>
            <div>
              {t("inventoryTransfers.created")}{" "}
              <span className="font-bold text-slate-700">
                {formatDate(detail.transfer.created_at)}
              </span>
            </div>
            <div>
              {t("inventoryTransfers.posted")}{" "}
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
