import { Search, Calendar } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { Zone } from "@/types/dispatch";

interface ScheduleModalProps {
  isOpen: boolean;
  onClose: () => void;
  schedulingType: "bulk" | "local";
  zones: Zone[];
  selectedZoneIdForZones: string;
  bulkZoneSearch: string;
  onBulkZoneSearchChange: (query: string) => void;
  selectedBulkZoneIds: string[];
  onToggleBulkZoneSelection: (id: string) => void;
  onToggleAllBulkZones: () => void;
  schedulingForm: {
    frequency: string;
    visitDay: string;
    startDate: string;
  };
  onSchedulingFormChange: (form: { frequency: string; visitDay: string; startDate: string }) => void;
  customDays: number;
  onCustomDaysChange: (days: number) => void;
  onUpdateScheduling: () => void;
}

export function ScheduleModal({
  isOpen,
  onClose,
  schedulingType,
  zones,
  selectedZoneIdForZones,
  bulkZoneSearch,
  onBulkZoneSearchChange,
  selectedBulkZoneIds,
  onToggleBulkZoneSelection,
  onToggleAllBulkZones,
  schedulingForm,
  onSchedulingFormChange,
  customDays,
  onCustomDaysChange,
  onUpdateScheduling,
}: ScheduleModalProps) {
  const filteredZones = zones.filter(z => z.name.toLowerCase().includes(bulkZoneSearch.toLowerCase()));
  const allSelected = filteredZones.length > 0 && filteredZones.every(z => selectedBulkZoneIds.includes(z.id));

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="إعدادات الجدولة"
      footer={
        <button
          onClick={onUpdateScheduling}
          className="px-8 py-2 rounded-xl bg-[#1e87bb] text-white font-bold hover:bg-[#0f766e] transition-colors shadow-lg shadow-[#1e87bb]/20"
        >
          تأكيد الجدولة
        </button>
      }
    >
      <div className="space-y-6">
        <p className="text-sm text-slate-600">
          {schedulingType === "bulk" ? "تعديل جدول العمل للمناطق المختارة." : `تعديل جدول العمل لمنطقة: ${zones.find(z => z.id === selectedZoneIdForZones)?.name}`}
        </p>

        {schedulingType === "bulk" && (
          <div className="space-y-4">
            <div className="relative">
              <Search className="absolute end-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="search"
                value={bulkZoneSearch}
                onChange={(e) => onBulkZoneSearchChange(e.target.value)}
                placeholder="بحث عن المناطق..."
                className="w-full rounded-xl border border-slate-200 bg-slate-50 pe-9 ps-4 py-2 text-sm focus:ring-2 focus:ring-[#1e87bb]/20 outline-none transition-all"
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-500">اختيار المناطق</span>
                <button
                  onClick={onToggleAllBulkZones}
                  className="text-[10px] font-bold text-[#1e87bb] hover:underline"
                >
                  {allSelected ? "إلغاء تحديد الكل" : "تحديد الكل"}
                </button>
              </div>
              <div className="max-h-[180px] overflow-y-auto border border-slate-100 rounded-xl p-3 space-y-1 bg-slate-50/50">
                {filteredZones.map(z => (
                  <label key={z.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-white transition-colors cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={selectedBulkZoneIds.includes(z.id)}
                      onChange={() => onToggleBulkZoneSelection(z.id)}
                      className="w-4 h-4 rounded border-slate-300 text-[#1e87bb] focus:ring-[#1e87bb]/20"
                    />
                    <span className="text-sm text-slate-700 group-hover:text-slate-900 transition-colors">{z.name}</span>
                  </label>
                ))}
                {filteredZones.length === 0 && (
                  <p className="text-center text-xs text-slate-400 py-4">لا توجد مناطق تطابق البحث</p>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="space-y-4">
          <div className="space-y-1.5">
            <span className="text-xs font-bold text-slate-500 text-start block">تكرار الزيارة</span>
            <select
              value={schedulingForm.frequency}
              onChange={e => onSchedulingFormChange({ ...schedulingForm, frequency: e.target.value })}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20 transition-all"
            >
              <option>أسبوعي (مرة في الأسبوع)</option>
              <option>كل أسبوعين (مرة كل 14 يوم)</option>
              <option>شهري (مرة في الشهر)</option>
              <option>مخصص</option>
            </select>
          </div>

          {schedulingForm.frequency === "مخصص" && (
            <div className="space-y-1.5 animate-in fade-in slide-in-from-top-2">
              <span className="text-xs font-bold text-slate-500 text-start block">كل كم يوم؟ (مثال: 14)</span>
              <input
                type="number"
                value={customDays}
                onChange={e => onCustomDaysChange(parseInt(e.target.value) || 0)}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                placeholder="أدخل عدد الأيام"
              />
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <span className="text-xs font-bold text-slate-500">يوم الزيارة</span>
              <select
                value={schedulingForm.visitDay}
                onChange={e => onSchedulingFormChange({ ...schedulingForm, visitDay: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
              >
                <option>السبت</option>
                <option>الأحد</option>
                <option>الاثنين</option>
                <option>الثلاثاء</option>
                <option>الأربعاء</option>
                <option>الخميس</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <span className="text-xs font-bold text-slate-500">تاريخ البدء</span>
              <input
                type="date"
                min={new Date().toISOString().split('T')[0]}
                value={schedulingForm.startDate}
                onChange={e => onSchedulingFormChange({ ...schedulingForm, startDate: e.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
              />
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
