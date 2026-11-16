import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { zoneText } from "@/features/dispatch/zones/zoneUi";

interface ZoneModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingZoneId: string | null;
  zoneFormName: string;
  onZoneFormNameChange: (name: string) => void;
  onSave: () => void;
  onVerify?: () => void;
  busy?: boolean;
  uncertain?: boolean;
}
export function ZoneModal({
  isOpen, onClose, editingZoneId, zoneFormName, onZoneFormNameChange,
  onSave, onVerify = () => undefined, busy = false, uncertain = false,
}: ZoneModalProps) {
  const { i18n } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const t = (key: Parameters<typeof zoneText>[1]) => zoneText(i18n.language, key);
  return (
    <Modal isOpen={isOpen} onClose={busy ? () => undefined : onClose}
      initialFocusRef={inputRef}
      title={t(editingZoneId ? "zoneEditTitle" : "zoneCreate")}
      footer={
        <div className="flex w-full flex-col-reverse gap-2 sm:flex-row" dir={i18n.dir()}>
          <button type="button" disabled={busy || uncertain} onClick={onClose}
            className="min-h-11 rounded-xl px-5 py-2 font-bold text-slate-600 hover:bg-slate-100 focus-visible:ring-2 disabled:opacity-50">
            {t("cancel")}
          </button>
          {uncertain ? (
            <button type="button" onClick={onVerify} disabled={busy}
              className="min-h-11 flex-1 rounded-xl bg-[#1e87bb] px-4 py-2 font-bold text-white focus-visible:ring-2 disabled:opacity-50">
              {busy ? t("zoneVerifying") : t("zoneVerify")}
            </button>
          ) : (
            <button type="submit" form="zone-form" disabled={busy}
              className="min-h-11 flex-1 rounded-xl bg-[#1e87bb] px-4 py-2 font-bold text-white hover:bg-[#0f766e] focus-visible:ring-2 disabled:opacity-50">
              {busy ? t("zoneSaving") : t("save")}
            </button>
          )}
        </div>
      }>
      <form id="zone-form" dir={i18n.dir()}
        onSubmit={event => { event.preventDefault(); if (!busy && !uncertain) onSave(); }}>
        <label className="block space-y-1">
          <span className="text-xs font-bold text-slate-600">{t("zoneName")}</span>
          <input ref={inputRef} type="text" minLength={2} maxLength={100}
            disabled={busy || uncertain}
            value={zoneFormName} onChange={event => onZoneFormNameChange(event.target.value)}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus-visible:ring-2 disabled:opacity-50"
            placeholder={t("zoneNamePlaceholder")} required />
        </label>
        {uncertain && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {t("zoneSaveUnknown")}
        </p>}
      </form>
    </Modal>
  );
}
