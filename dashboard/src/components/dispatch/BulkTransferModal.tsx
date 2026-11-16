import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import type { Zone } from "@/types/dispatch";
import { zoneText } from "@/features/dispatch/zones/zoneUi";

interface BulkTransferModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedShopIds: string[];
  zones: Zone[];
  selectedZoneIdForZones: string;
  targetTransferZoneId: string;
  onTargetTransferZoneChange: (id: string) => void;
  onConfirm: () => void;
}

export function BulkTransferModal({
  isOpen, onClose, selectedShopIds, zones, selectedZoneIdForZones,
  targetTransferZoneId, onTargetTransferZoneChange, onConfirm,
}: BulkTransferModalProps) {
  const { i18n } = useTranslation();
  const text = (key: Parameters<typeof zoneText>[1], values?: Record<string, string | number>) =>
    zoneText(i18n.language, key, values);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={text("bulkTransferTitle")}
      footer={
        <button
          type="button"
          onClick={onConfirm}
          disabled={selectedShopIds.length === 0 || !targetTransferZoneId}
          className="w-full rounded-xl bg-[#1e87bb] py-2.5 font-bold text-white shadow-lg transition-colors hover:bg-[#166a94] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {text("bulkTransferConfirm")}
        </button>
      }
    >
      <div className="min-h-[250px] space-y-6 overflow-visible" dir={i18n.dir()}>
        <p className="text-sm text-slate-600">
          {text("bulkTransferDescription", { count: selectedShopIds.length })}
        </p>
        <div className="space-y-1.5">
          <span className="block text-start text-xs font-bold text-slate-500">
            {text("bulkTransferTarget")}
          </span>
          <CustomSelect
            label={text("bulkTransferTarget")}
            options={zones.filter(zone => zone.id !== selectedZoneIdForZones).map(zone => ({
              id: zone.id, label: zone.name,
            }))}
            value={targetTransferZoneId}
            onChange={onTargetTransferZoneChange}
            placeholder={text("bulkTransferPlaceholder")}
            className="w-full"
          />
        </div>
      </div>
    </Modal>
  );
}
