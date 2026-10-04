import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import type { Quantity } from "@/lib/quantity";
import type { BatchStockSource, BatchStockSourceStatus, BatchTerminalActionAvailability } from "./batchStockSourcesContract";

export type BatchTerminalChoice = {
  availability: BatchTerminalActionAvailability;
  source: BatchStockSource;
  status: BatchStockSourceStatus;
};

export type BatchTerminalEvidence = {
  quantity: Quantity;
  reason?: string;
  method?: string;
  evidenceReference?: string;
  vendorName?: string;
  vendorReference?: string;
  handoverReference?: string;
};

export function BatchTerminalActionDialog({ choice, baseUomCode, busy, online, onClose, onConfirm }: {
  choice: BatchTerminalChoice;
  baseUomCode: string;
  busy: boolean;
  online: boolean;
  onClose: () => void;
  onConfirm: (evidence: BatchTerminalEvidence) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const action = choice.availability.action;
  const [quantity, setQuantity] = useState<Quantity>(choice.availability.eligible_quantity);
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState("");
  const [evidenceReference, setEvidenceReference] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [vendorReference, setVendorReference] = useState("");
  const [handoverReference, setHandoverReference] = useState("");
  const disposal = action === "CONFIRM_DISPOSAL";
  const requiredReady = quantity.trim().length > 0 && (disposal
    ? reason.trim().length > 0
    : vendorName.trim().length > 0 && vendorReference.trim().length > 0 && handoverReference.trim().length > 0);
  const canConfirm = online && !busy && requiredReady;
  const evidence = (): BatchTerminalEvidence => ({
    quantity,
    reason,
    method,
    evidenceReference,
    vendorName,
    vendorReference,
    handoverReference,
  });

  const inputClass = "mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100";
  return <Modal isOpen onClose={onClose} title={t(`terminalQualityActions.actions.${action}.title`)}
    subtitle={t(`terminalQualityActions.actions.${action}.hint`)} maxWidth="max-w-lg">
    <form className="space-y-3" onSubmit={(event) => {
      event.preventDefault();
      if (canConfirm) void onConfirm(evidence());
    }}>
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
        <p className="font-black text-slate-900">{choice.source.location_name}</p>
        <p className="mt-1 font-semibold text-slate-600">{t("terminalQualityActions.eligible", { quantity: choice.availability.eligible_quantity, unit: baseUomCode })}</p>
      </div>
      <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.quantity")}
        <input autoFocus dir="ltr" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} className={inputClass} />
      </label>
      {disposal ? <>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.disposalReason")}
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("terminalQualityActions.disposalReasonPlaceholder")} className={`${inputClass} min-h-20 resize-y`} />
        </label>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.disposalMethod")}
          <input value={method} onChange={(e) => setMethod(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.evidenceReference")}
          <input value={evidenceReference} onChange={(e) => setEvidenceReference(e.target.value)} className={inputClass} />
        </label>
      </> : <>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.vendorName")}
          <input value={vendorName} onChange={(e) => setVendorName(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.vendorReference")}
          <input value={vendorReference} onChange={(e) => setVendorReference(e.target.value)} className={inputClass} />
        </label>
        <label className="block text-xs font-bold text-slate-700">{t("terminalQualityActions.handoverReference")}
          <input value={handoverReference} onChange={(e) => setHandoverReference(e.target.value)} className={inputClass} />
        </label>
      </>}
      <div className="flex flex-wrap justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} disabled={busy} className="rounded-lg px-3 py-2 text-xs font-black text-slate-600 hover:bg-slate-50 disabled:opacity-40">{t("common.cancel")}</button>
        <button type="submit" disabled={!canConfirm}
          className="rounded-lg bg-slate-950 px-4 py-2 text-xs font-black text-white hover:bg-slate-800 disabled:opacity-40">{t("terminalQualityActions.confirm")}</button>
      </div>
    </form>
  </Modal>;
}
