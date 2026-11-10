import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";

interface ZoneModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingZoneId: string | null;
  zoneFormName: string;
  onZoneFormNameChange: (name: string) => void;
  onSave: () => void;
}

export function ZoneModal({
  isOpen, onClose, editingZoneId, zoneFormName, onZoneFormNameChange, onSave,
}: ZoneModalProps) {
  const { i18n } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const text = (key: Parameters<typeof dispatchUiText>[1]) =>
    dispatchUiText(i18n.language, key);

  return (
    <Modal isOpen={isOpen} onClose={onClose} initialFocusRef={inputRef}
      title={text(editingZoneId ? "zoneEdit" : "zoneCreate")}
      footer={
        <div className="flex w-full flex-col-reverse gap-2 sm:flex-row" dir={i18n.dir()}>
          <button type="button" onClick={onClose}
            className="min-h-11 rounded-xl px-5 py-2 text-slate-600 font-bold hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
            {text("cancel")}
          </button>
          <button type="submit" form="zone-form"
            className="min-h-11 flex-1 rounded-xl bg-[#1e87bb] py-2 font-bold text-white hover:bg-[#0f766e] focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-[#1e87bb]">
            {text("save")}
          </button>
        </div>
      }>
      <form id="zone-form" onSubmit={event => { event.preventDefault(); onSave(); }} dir={i18n.dir()}>
        <label className="block space-y-1">
          <span className="text-xs font-bold text-slate-600">{text("zoneName")}</span>
          <input ref={inputRef} type="text" minLength={2} maxLength={100}
            value={zoneFormName} onChange={event => onZoneFormNameChange(event.target.value)}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]"
            placeholder={text("zonePlaceholder")} required />
        </label>
      </form>
    </Modal>
  );
}
