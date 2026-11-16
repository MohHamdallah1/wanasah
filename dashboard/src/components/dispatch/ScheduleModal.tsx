import { Search } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import type { Zone } from "@/types/dispatch";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { zoneText, type ZoneFrequency } from "@/features/dispatch/zones/zoneUi";

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
  schedulingForm: { frequency: string; startDate: string };
  onSchedulingFormChange: (form: { frequency: string; startDate: string }) => void;
  customDays: number;
  onCustomDaysChange: (days: number) => void;
  onUpdateScheduling: () => void;
  onClearScheduling: () => void;
  busy: boolean;
  feedback: string | null;
}
export function ScheduleModal({
  isOpen,onClose,schedulingType,zones,selectedZoneIdForZones,bulkZoneSearch,
  onBulkZoneSearchChange,selectedBulkZoneIds,onToggleBulkZoneSelection,
  onToggleAllBulkZones,schedulingForm,onSchedulingFormChange,customDays,
  onCustomDaysChange,onUpdateScheduling,onClearScheduling,busy,feedback,
}: ScheduleModalProps) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof zoneText>[1], values?: Record<string, string | number>) =>
    zoneText(i18n.language,key,values);
  const filtered = useMemo(()=>zones.filter(zone=>
    zone.name.toLocaleLowerCase(i18n.language).includes(bulkZoneSearch.trim().toLocaleLowerCase(i18n.language))
  ),[zones,bulkZoneSearch,i18n.language]);
  const allSelected = filtered.length>0 && filtered.every(z=>selectedBulkZoneIds.includes(z.id));
  const localZone=zones.find(z=>z.id===selectedZoneIdForZones);
  const canClear = schedulingType==="local" && Boolean(localZone?.intervalDays || localZone?.startDate);
  const choice = schedulingForm.frequency as ZoneFrequency;
  return (
    <Modal isOpen={isOpen} onClose={busy?()=>undefined:onClose}
      title={t("scheduleTitle")}
      footer={
        <div className="flex w-full flex-wrap justify-end gap-2" dir={i18n.dir()}>
          {canClear && <button type="button" onClick={onClearScheduling} disabled={busy}
            className="min-h-11 rounded-xl border border-amber-400 px-4 py-2 text-sm font-bold text-amber-900 focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-40">
            {t("scheduleClear")}
          </button>}
          <button type="button" onClick={onUpdateScheduling} disabled={busy || (schedulingType==="bulk" && selectedBulkZoneIds.length===0)}
            className="min-h-11 flex-1 rounded-xl bg-[#1e87bb] px-6 py-2 font-bold text-white focus-visible:ring-2 focus-visible:ring-[#1e87bb] disabled:opacity-40">
            {busy?t("scheduleBusy"):t("scheduleUpdate")}
          </button>
        </div>
      }>
      <div className="space-y-5" dir={i18n.dir()}>
        <p className="text-sm text-slate-600">
          {schedulingType==="bulk"?t("scheduleBulk"):t("scheduleLocal",{name:localZone?.name||""})}
        </p>
        {feedback && <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{feedback}</p>}
        {schedulingType==="bulk" && <div className="space-y-3">
          <label className="relative block">
            <Search aria-hidden className="absolute start-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"/>
            <span className="sr-only">{t("scheduleSearch")}</span>
            <input type="search" value={bulkZoneSearch} onChange={e=>onBulkZoneSearchChange(e.target.value)}
              placeholder={t("scheduleSearch")} disabled={busy}
              className="w-full rounded-xl border bg-slate-50 py-2 ps-9 pe-3 text-sm focus-visible:ring-2"/>
          </label>
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600">{t("scheduleSelection")} ({selectedBulkZoneIds.length})</span>
            <button type="button" disabled={busy || filtered.length===0} onClick={onToggleAllBulkZones}
              className="rounded-lg px-2 py-1 text-xs font-semibold text-[#1e87bb] focus-visible:ring-2 disabled:opacity-40">
              {allSelected?t("scheduleClearVisible"):t("scheduleAllVisible")}
            </button>
          </div>
          <ul className="max-h-44 space-y-1 overflow-y-auto rounded-xl border border-slate-200 p-2">
            {filtered.map(zone=><li key={zone.id}>
              <label className="flex min-h-9 items-center gap-2 rounded-lg p-2 hover:bg-slate-50">
                <input type="checkbox" checked={selectedBulkZoneIds.includes(zone.id)}
                  disabled={busy} onChange={()=>onToggleBulkZoneSelection(zone.id)}
                  className="h-4 w-4 rounded focus-visible:ring-2"/>
                <span className="truncate text-sm text-slate-700">{zone.name}</span>
              </label>
            </li>)}
            {filtered.length===0 && <li className="p-3 text-center text-xs text-slate-500">{t("scheduleNoMatch")}</li>}
          </ul>
        </div>}
        <label className="block space-y-1">
          <span className="block text-xs font-bold text-slate-600">{t("scheduleFrequency")}</span>
          <select value={choice} disabled={busy}
            onChange={e=>onSchedulingFormChange({...schedulingForm,frequency:e.target.value})}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm focus-visible:ring-2">
            <option value="7">{t("schedule7")}</option>
            <option value="14">{t("schedule14")}</option>
            <option value="30">{t("schedule30")}</option>
            <option value="custom">{t("scheduleCustom")}</option>
          </select>
        </label>
        {choice==="custom" && <label className="block space-y-1">
          <span className="block text-xs font-bold text-slate-600">{t("scheduleDays")}</span>
          <input type="number" min={1} max={2147483647} step={1} value={customDays}
            disabled={busy} onChange={e=>onCustomDaysChange(Number(e.target.value))}
            placeholder={t("scheduleDaysHint")}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm focus-visible:ring-2"/>
        </label>}
        <label className="block space-y-1">
          <span className="block text-xs font-bold text-slate-600">{t("scheduleStart")}</span>
          <input type="date" value={schedulingForm.startDate} disabled={busy}
            onChange={e=>onSchedulingFormChange({...schedulingForm,startDate:e.target.value})}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-sm focus-visible:ring-2"/>
        </label>
      </div>
    </Modal>
  );
}
