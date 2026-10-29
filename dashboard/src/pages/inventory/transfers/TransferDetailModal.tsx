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
  timeZone?: string;
  onClose: () => void;
}

export function TransferDetailModal({
  detail,
  loading,
  timeZone,
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
      {loading ? (
        <div className="p-10 text-center text-sm font-bold text-slate-500" role="status">
          {t("inventoryTransfers.detailLoading")}
        </div>
      ) : null}

      {!loading && detail ? (
        <div className="space-y-3" data-cp13-transfer-detail="compact">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold text-slate-400">{t("inventoryTransfers.reference")}</div>
              <div className="mt-0.5 truncate text-xs font-black text-slate-800">
                {t("inventoryTransfers.transferNumber", {
                  id: formatTransferNumber(detail.transfer.id),
                })}
              </div>
            </div>
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold text-slate-400">{t("inventoryTransfers.source")}</div>
              <div className="mt-0.5 truncate text-xs font-black text-slate-800">{detail.transfer.source_location_name}</div>
            </div>
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold text-slate-400">{t("inventoryTransfers.destination")}</div>
              <div className="mt-0.5 truncate text-xs font-black text-slate-800">{detail.transfer.destination_location_name}</div>
            </div>
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold text-slate-400">{t("inventoryTransfers.purpose")}</div>
              <div className="mt-0.5 truncate text-xs font-black text-slate-800">
                {t(`inventoryTransfers.${detail.transfer.transfer_purpose}`, { defaultValue: detail.transfer.transfer_purpose })}
              </div>
            </div>
            <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold text-slate-400">{t("inventoryTransfers.status")}</div>
              <span className={`mt-0.5 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-black ${STATUS_META[detail.transfer.status].className}`}>
                <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                {t(STATUS_META[detail.transfer.status].label)}
              </span>
            </div>
          </div>

          {detail.transfer.notes || detail.transfer.decision_reason ? (
            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
              {detail.transfer.notes ? (
                <p>
                  <span className="font-black">{t("inventoryTransfers.notesLabel")}</span>{" "}
                  {detail.transfer.notes}
                </p>
              ) : null}
              {detail.transfer.decision_reason ? (
                <p className={detail.transfer.notes ? "mt-1.5" : ""}>
                  <span className="font-black">{t("inventoryTransfers.reasonLabel")}</span>{" "}
                  {detail.transfer.decision_reason}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="max-h-[45vh] overflow-auto rounded-xl border border-slate-200">
            <table className="w-full min-w-[720px] text-sm text-start">
              <thead className="sticky top-0 bg-slate-50">
                <tr>
                  <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.product")}</th>
                  <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.batch")}</th>
                  <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.expiry")}</th>
                  <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.quantity")}</th>
                  <th className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{t("inventoryTransfers.batchPolicy")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {detail.lines.map((line) => (
                  <tr key={line.id}>
                    <td className="px-3 py-2 text-xs font-black text-slate-800">{line.product_name}</td>
                    <td className="px-3 py-2 font-mono text-[11px]">
                      {formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-600" dir="ltr">
                      {formatTransferDateOnly(line.expiry_date)}
                    </td>
                    <td className="px-3 py-2 text-xs font-black tabular-nums" dir="ltr">
                      {formatTransferNumber(line.quantity)}
                    </td>
                    <td className="px-3 py-2 text-[11px] font-semibold text-slate-600">
                      {line.fefo_override_reason_id
                        ? t("inventoryTransfers.overrideEvidence", { note: line.fefo_override_note || t("inventoryTransfers.noDescription") })
                        : t("inventoryTransfers.fefoAuto")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-2 gap-2 border-t border-slate-100 pt-2 text-[10px] text-slate-500 md:grid-cols-4">
            <div>
              {t("inventoryTransfers.sender")} <span className="font-black text-slate-700">{detail.transfer.dispatched_by_name}</span>
            </div>
            <div>
              {t("inventoryTransfers.receiver")} <span className="font-black text-slate-700">{detail.transfer.received_by_name || "—"}</span>
            </div>
            <div dir="ltr">
              {t("inventoryTransfers.created")} <span className="font-black text-slate-700">{formatDate(detail.transfer.created_at, timeZone)}</span>
            </div>
            <div dir="ltr">
              {t("inventoryTransfers.posted")} <span className="font-black text-slate-700">{formatDate(detail.transfer.posted_at, timeZone)}</span>
            </div>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
