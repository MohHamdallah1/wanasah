import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone } from "@/types/dispatch";

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
  isOpen,
  onClose,
  selectedShopIds,
  zones,
  selectedZoneIdForZones,
  targetTransferZoneId,
  onTargetTransferZoneChange,
  onConfirm,
}: BulkTransferModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="نقل المحلات الجماعي"
      footer={
        <button 
          onClick={onConfirm}
          className="w-full bg-[#1e87bb] text-white py-2.5 rounded-xl font-bold hover:bg-[#166a94] transition-colors shadow-lg"
        >
          تأكيد النقل
        </button>
      }
    >
      <div className="space-y-6 min-h-[250px] overflow-visible">
        <p className="text-sm text-slate-600">سيتم نقل {selectedShopIds.length} محلات إلى المنطقة المختارة:</p>
        <div className="space-y-1.5">
          <span className="text-xs font-bold text-slate-500 text-start block">المنطقة المستهدفة</span>
          <CustomSelect
            label=""
            options={zones.filter(z => z.id !== selectedZoneIdForZones).map(z => ({ id: z.id, label: z.name }))}
            value={targetTransferZoneId}
            onChange={onTargetTransferZoneChange}
            placeholder="— اختر المنطقة —"
            className="w-full"
          />
        </div>
      </div>
    </Modal>
  );
}
