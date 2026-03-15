import { Modal } from "@/components/ui/modal";

interface ZoneModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingZoneId: string | null;
  zoneFormName: string;
  onZoneFormNameChange: (name: string) => void;
  onSave: () => void;
}

export function ZoneModal({
  isOpen,
  onClose,
  editingZoneId,
  zoneFormName,
  onZoneFormNameChange,
  onSave,
}: ZoneModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={editingZoneId ? "تعديل اسم المنطقة" : "إضافة منطقة جديدة"}
      footer={
        <div className="flex gap-2 w-full">
          <button type="button" onClick={onClose} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
          <button type="submit" form="zone-form" className="flex-1 bg-[#1e87bb] text-white py-2 rounded-xl font-bold hover:bg-[#0f766e] transition-colors shadow-lg shadow-[#1e87bb]/20">حفظ البيانات</button>
        </div>
      }
    >
      <form id="zone-form" onSubmit={(e) => { e.preventDefault(); onSave(); }} className="space-y-4">
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">اسم المنطقة</span>
          <input
            type="text"
            value={zoneFormName}
            onChange={e => onZoneFormNameChange(e.target.value)}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
            placeholder="مثلاً: عمان الغربية"
          />
        </div>
      </form>
    </Modal>
  );
}
