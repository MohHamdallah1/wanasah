import { MapPin, CircleDollarSign } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { Zone } from "@/types/dispatch";

interface ShopFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  editingShopId: string | null;
  shopForm: {
    name: string;
    owner: string;
    phone: string;
    mapLink: string;
    zoneId: string;
    initialDebt: number;
    maxDebtLimit: number;
  };
  onShopFormChange: (form: any) => void;
  zones: Zone[];
  onSave: () => void;
}

export function ShopFormModal({
  isOpen,
  onClose,
  editingShopId,
  shopForm,
  onShopFormChange,
  zones,
  onSave,
}: ShopFormModalProps) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={editingShopId ? "تعديل بيانات المحل" : "إضافة محل جديد"}
      footer={
        <div className="flex gap-2 w-full">
          <button type="button" onClick={onClose} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
          <button type="submit" form="shop-form" className="flex-1 bg-[#1e87bb] text-white py-2 rounded-xl font-bold hover:bg-[#0f766e] transition-colors shadow-lg">حفظ البيانات</button>
        </div>
      }
    >
      <form id="shop-form" onSubmit={(e) => { e.preventDefault(); onSave(); }} className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">اسم المحل</span>
          <input
            type="text"
            value={shopForm.name}
            onChange={e => onShopFormChange({ ...shopForm, name: e.target.value })}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
            placeholder="مثلاً: بقالة الخير"
          />
        </div>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">اسم المالك</span>
          <input
            type="text"
            value={shopForm.owner}
            onChange={e => onShopFormChange({ ...shopForm, owner: e.target.value })}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
            placeholder="الاسم الثلاثي"
          />
        </div>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">رقم الهاتف</span>
          <input
            type="tel"
            value={shopForm.phone}
            onChange={e => {
              const onlyNumsAndPlus = e.target.value.replace(/[^\d+]/g, '');
              onShopFormChange({ ...shopForm, phone: onlyNumsAndPlus });
            }}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
            placeholder="07xxxxxxxx"
            dir="ltr"
          />
        </div>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">المنطقة</span>
          <CustomSelect
            label=""
            options={zones.map(z => ({ id: z.id, label: z.name }))}
            value={shopForm.zoneId}
            onChange={id => onShopFormChange({ ...shopForm, zoneId: id })}
          />
        </div>
        <div className="col-span-2 space-y-1">
          <span className="text-xs font-bold text-slate-500">رابط الخريطة / Map Link</span>
          <div className="relative">
            <MapPin className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="url"
              value={shopForm.mapLink}
              onChange={e => onShopFormChange({ ...shopForm, mapLink: e.target.value })}
              className="w-full rounded-xl border border-slate-200 pr-9 pl-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
              placeholder="https://maps.google.com/..."
            />
          </div>
        </div>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">سقف الدين / Max Debt</span>
          <div className="relative">
            <CircleDollarSign className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="number"
              value={shopForm.maxDebtLimit}
              onChange={e => onShopFormChange({ ...shopForm, maxDebtLimit: Number(e.target.value) })}
              onFocus={(e) => e.target.select()}
              className="w-full rounded-xl border border-slate-200 pr-9 pl-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
              placeholder="0.00"
            />
          </div>
        </div>
        <div className="space-y-1">
          <span className="text-xs font-bold text-slate-500">المديونية الحالية</span>
          <input
            type="number"
            value={shopForm.initialDebt}
            onChange={e => onShopFormChange({ ...shopForm, initialDebt: Number(e.target.value) })}
            onFocus={(e) => e.target.select()}
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
            placeholder="0.00"
          />
        </div>
      </form>
    </Modal>
  );
}
