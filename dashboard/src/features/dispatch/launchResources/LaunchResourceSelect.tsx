import { useEffect, useId, useRef, useState } from "react";
import { AlertCircle, ChevronDown, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { LaunchOption } from "./launchResourceRead";
import { resourceReason } from "./launchResourceReasons";

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
  const [hintedId, setHintedId] = useState<string | null>(null);
  const [selectedHint, setSelectedHint] = useState(false);
  const hintId = useId();
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
  const selectedReason = selected && !selected.available ? resourceReason(selected.code, ar) : null;
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
    <div className="relative"
      role={selectedReason && disabled ? "group" : undefined}
      tabIndex={selectedReason && disabled ? 0 : undefined}
      aria-label={selectedReason && disabled ? `${selected.label}: ${selectedReason}` : undefined}
      onMouseEnter={() => setSelectedHint(true)} onMouseLeave={() => setSelectedHint(false)}
      onFocus={() => setSelectedHint(true)} onBlur={() => setSelectedHint(false)}>
      <button type="button" disabled={disabled}
        aria-haspopup="listbox" aria-expanded={open}
        aria-describedby={selectedReason ? `${hintId}-selected-note` : undefined}
        onClick={() => { setHintedId(null); setOpen(v => !v); }}
        className="flex min-h-10 w-full min-w-0 items-center justify-between gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500">
        <span className="min-w-0 truncate">{selected?.label || placeholder}</span>
        {selectedReason && <AlertCircle aria-hidden="true" className="h-4 w-4 shrink-0 text-amber-700" />}
        <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0"/>
      </button>
      {selectedReason && <span id={`${hintId}-selected-note`} className="sr-only">{selectedReason}</span>}
      {selectedReason && selectedHint && !open && <span role="tooltip"
        className="pointer-events-none absolute end-0 top-full z-[80] mt-1 w-max max-w-[min(90vw,320px)] rounded-lg border border-amber-200 bg-white px-3 py-2 text-start text-xs font-medium text-amber-900 shadow-lg">
        {selectedReason}</span>}
      {open && !disabled && <div role="listbox" aria-label={label}
        className="absolute inset-x-0 top-full z-[70] mt-1 flex max-h-[280px] min-w-[240px] max-w-[min(95vw,420px)] flex-col overflow-visible rounded-xl border border-slate-200 bg-white shadow-lg">
        <label className="relative shrink-0 rounded-t-xl border-b p-2">
          <Search className="pointer-events-none absolute end-4 top-4 h-4 w-4 text-slate-500"/>
          <input type="search" value={search} onChange={e => { setSearch(e.target.value); setHintedId(null); }}
            aria-label={ar ? "بحث ضمن الموارد" : "Search resources"}
            placeholder={ar ? "بحث..." : "Search..."}
            className="w-full rounded-lg border p-2 pe-9 text-sm"/>
        </label>
        <div className="min-h-0 overflow-y-auto rounded-b-xl p-1">
          {available.map(x => <button role="option" aria-selected={value === x.id} data-resource-id={x.id}
            aria-label={x.label} key={x.id} type="button"
            onClick={() => choose(x)}
            className="flex w-full min-w-0 items-center rounded-lg px-3 py-2.5 text-start text-sm hover:bg-sky-50">
            <span className="truncate">{x.label}</span>
          </button>)}
          {unavailable.map(x => <div key={x.id} role="group" tabIndex={0}
            className="relative rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]"
            aria-label={`${x.label}: ${resourceReason(x.code, ar)}`}
            aria-describedby={`${hintId}-option-${x.id}`}
            onMouseEnter={() => setHintedId(x.id)} onMouseLeave={() => setHintedId(null)}
            onFocus={() => setHintedId(x.id)} onBlur={() => setHintedId(null)}>
            <button role="option" aria-selected={value === x.id} data-resource-id={x.id}
              aria-label={x.label} type="button" disabled tabIndex={-1}
              className="pointer-events-none flex w-full min-w-0 items-center gap-2 rounded-lg px-3 py-2.5 text-start text-sm text-slate-500 disabled:cursor-not-allowed">
              <span className="min-w-0 truncate">{x.label}</span>
              <AlertCircle aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-amber-600" />
            </button>
            <span id={`${hintId}-option-${x.id}`} className="sr-only">{resourceReason(x.code, ar)}</span>
          </div>)}
          {hintedId && unavailable.some(x => x.id === hintedId) && <span role="tooltip"
            className="pointer-events-none absolute inset-x-0 bottom-full z-[80] mb-1 rounded-lg border border-amber-200 bg-white px-3 py-2 text-start text-xs font-medium text-amber-900 shadow-lg">
            {resourceReason(unavailable.find(x => x.id === hintedId)!.code, ar)}
          </span>}
          {filtered.length === 0 && <p className="p-3 text-center text-sm text-slate-500">
            {ar ? "لا توجد نتائج" : "No matches"}</p>}
        </div>
      </div>}
    </div>
  </div>;
}