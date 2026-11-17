import { useMemo, useState } from "react";
import { Search, Truck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";

const MAX_OPTIONS = 120;

/** A native select keeps the representatives' menu above the browser window edge. */
export function ShortageDriverPicker({ drivers, driverId, onChange, editing, disabled,
  allowUnassigned, onAllowUnassigned,
}: {
  drivers: readonly { id: string; name: string }[];
  driverId: string;
  onChange: (id: string) => void;
  editing: boolean;
  disabled: boolean;
  allowUnassigned: boolean;
  onAllowUnassigned: (value: boolean) => void;
}) {
  const { i18n } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1]) => dispatchUiText(i18n.language, key);
  const [search,setSearch] = useState("");
  const current=drivers.find(driver=>driver.id===driverId);
  const choices=useMemo(() => {
    const q=search.trim().toLocaleLowerCase();
    const filtered=q ? drivers.filter(driver=>driver.name.toLocaleLowerCase().includes(q)) : drivers;
    const first=filtered.slice(0,MAX_OPTIONS);
    if (current && !first.some(driver=>driver.id===current.id)) return [current,...first];
    return first;
  },[drivers,search,current]);

  return <section className="min-w-0 space-y-1.5" aria-label={t("shortageStudioDriver")}>
    <label htmlFor="shortage-driver-select" className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
      <Truck aria-hidden="true" className="h-4 w-4 text-sky-700"/>{t("shortageStudioDriver")}
    </label>
    {drivers.length>MAX_OPTIONS && !editing && !disabled && <div className="relative">
      <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
      <input type="search" value={search} maxLength={100} onChange={event=>setSearch(event.target.value)}
        aria-label={t("shortageStudioFindDriver")} placeholder={t("shortageStudioFindDriver")}
        className="mb-1 h-9 w-full rounded-lg border border-slate-200 bg-white ps-10 pe-3 text-xs outline-none focus:ring-2 focus:ring-sky-100"/>
    </div>}
    <select id="shortage-driver-select"
      value={allowUnassigned && !driverId ? "__unassigned__" : driverId}
      disabled={disabled||editing}
      onChange={event=>{
        if(event.target.value==="__unassigned__"){onChange("");onAllowUnassigned(true);}
        else{onChange(event.target.value);onAllowUnassigned(false);}
        setSearch("");
      }}
      className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100 disabled:bg-slate-100">
      <option value="">{t("shortageStudioPickDriver")}</option>
      {choices.map(driver=><option key={driver.id} value={driver.id}>{driver.name}</option>)}
      {!editing && <option value="__unassigned__">{t("shortageStudioUnassigned")}</option>}
    </select>
  </section>;
}
