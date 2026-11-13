import { useEffect, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LaunchOption } from "./launchResourceRead";

const reasons: Record<string, [string, string]> = {
  ZONE_INACTIVE: ["المنطقة غير نشطة", "Inactive zone"],
  ZONE_ROUTE_RESERVED: ["المنطقة محجوزة بخط قيد التشغيل أو متوقف مؤقتًا", "Zone assigned to an active or paused route"],
  ZONE_POSTPONED_RESERVED: ["المنطقة مؤجلة ومحجوزة؛ المندوب والسيارة محرران", "Postponed zone stays reserved; representative and vehicle are released"],
  REPRESENTATIVE_INACTIVE: ["المندوب غير نشط", "Inactive representative"],
  REPRESENTATIVE_FIELD_UNVERIFIED: ["هوية المندوب الميدانية غير معتمدة", "Field representative identity is not verified"],
  REPRESENTATIVE_ON_ROUTE: ["المندوب مرتبط بخط نشط أو متوقف مؤقتًا", "Representative assigned to an active or paused route"],
  PREVIOUS_SESSION_UNSETTLED: ["جلسة المندوب السابقة لم تسوَّ بالكامل ماليًا ومخزنيًا", "Prior WorkSession needs full cash and vehicle-stock settlement"],
  VEHICLE_NOT_OPERATIONAL: ["السيارة متوقفة أو تحت الصيانة", "Vehicle inactive or under maintenance"],
  VEHICLE_LOCATION_INVALID: ["موقع عهدة السيارة غير صالح أو غير محدد", "Vehicle custody location is invalid"],
  VEHICLE_ON_ROUTE: ["السيارة مرتبطة بخط نشط أو متوقف مؤقتًا", "Vehicle assigned to an active or paused route"],
  VEHICLE_CUSTODY_UNACCEPTED: ["عهدة السيارة الحالية غير معتمدة", "Current vehicle custody is not accepted"],
  CUSTODY_REQUIRES_REASSIGNMENT: ["عهدة السيارة لمندوب آخر؛ يلزم اعتماد نقلها أولًا", "Custody belongs to another representative; approve reassignment first"],
  WAREHOUSE_INACTIVE: ["المستودع غير نشط", "Inactive warehouse"],
  WAREHOUSE_AUDIT_LOCK: ["المستودع تحت قفل الجرد", "Warehouse stocktake lock is active"],
  NO_EXECUTE_PERMISSION: ["لا تملك صلاحية تشغيل هذا المورد", "Your account cannot execute operations for this resource"],
};
export function resourceReason(code: string, ar: boolean) {
  return reasons[code]?.[ar ? 0 : 1] ||
    (ar ? "هذا المورد غير متاح؛ تحقّق من صلاحيات التشغيل" : "Resource unavailable; verify operational authority");
}

export function LaunchResourceSelect({
  label, options, value, onChange, disabled, placeholder, kind,
}: {
  label: string; options: readonly LaunchOption[]; value: string;
  onChange: (next: string) => void; disabled: boolean; placeholder: string;
  kind: "zones" | "drivers" | "vehicles" | "warehouses";
}) {
  const { i18n } = useTranslation();
  const ar = (i18n.resolvedLanguage || i18n.language).startsWith("ar");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  useEffect(() => { if (!open || disabled) setSearch(""); if (disabled) setOpen(false); }, [open, disabled]);
  const selected = options.find(x => x.id === value);
  const filtered = options.filter(x => x.label.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const available = filtered.filter(x => x.available);
  const unavailable = filtered.filter(x => !x.available);
  const choose = (entry: LaunchOption) => {
    if (disabled || !entry.available) return;
    onChange(entry.id); setOpen(false);
  };
  return <div ref={ref} className="relative mt-2 min-w-0"
    data-testid={"m05-launch-" + kind} dir={i18n.dir()}>
    <span className={"absolute -top-2 z-10 bg-white px-1.5 text-[10px] font-black text-slate-500 " +
      (ar ? "right-3" : "left-3")}>{label}</span>
    <div className="relative">
      <button type="button" disabled={disabled}
        aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(v => !v)}
        className="flex min-h-10 w-full min-w-0 items-center justify-between gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500">
        <span className="truncate">{selected?.label || placeholder}</span>
        <ChevronDown className="h-4 w-4 shrink-0"/>
      </button>
      {open && !disabled && <div aria-label={label}
        className="absolute inset-x-0 top-full z-[70] mt-1 flex max-h-[280px] min-w-[240px] max-w-[min(95vw,420px)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
        <label className="relative shrink-0 border-b p-2">
          <Search className="pointer-events-none absolute end-4 top-4 h-4 w-4 text-slate-500"/>
          <input type="search" value={search} onChange={e => setSearch(e.target.value)}
            aria-label={ar ? "بحث ضمن الموارد" : "Search resources"}
            placeholder={ar ? "بحث..." : "Search..."}
            className="w-full rounded-lg border p-2 pe-9 text-sm"/>
        </label>
        <div className="min-h-0 overflow-y-auto p-1">
          {available.length > 0 && <p className="px-3 py-1.5 text-xs font-bold text-slate-600">
            {ar ? "المتاح" : "Available"} ({available.length})</p>}
          {available.map(x => <button aria-pressed={value === x.id}
            aria-label={x.label} key={x.id} type="button"
            onClick={() => choose(x)}
            className="flex w-full min-w-0 items-center rounded-lg px-3 py-2.5 text-start text-sm hover:bg-sky-50">
            <span className="truncate">{x.label}</span>
          </button>)}
          {unavailable.length > 0 && <p className="border-t px-3 py-1.5 text-xs font-bold text-slate-500">
            {ar ? "غير المتاح" : "Unavailable"} ({unavailable.length})</p>}
          {unavailable.map(x => <button aria-pressed={value === x.id}
            aria-label={x.label} key={x.id} type="button" disabled
            title={resourceReason(x.code, ar)}
            className="flex w-full min-w-0 flex-col rounded-lg px-3 py-2.5 text-start text-sm text-slate-500 opacity-75">
            <span className="truncate">{x.label}</span>
            <span className="text-xs text-amber-800">{resourceReason(x.code, ar)}</span>
          </button>)}
          {filtered.length === 0 && <p className="p-3 text-center text-sm text-slate-500">
            {ar ? "لا توجد نتائج" : "No matches"}</p>}
        </div>
      </div>}
    </div>
    {selected && !selected.available && <p role="status" className="mt-1 text-xs text-amber-800">
      {resourceReason(selected.code, ar)}</p>}
  </div>;
}
