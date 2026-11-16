import { Archive, CalendarDays, Pencil, AlertCircle } from "lucide-react";
import type { Zone } from "@/types/dispatch";
import { zoneText } from "./zoneUi";

interface Props {
  zone: Zone;
  language: string;
  selected: boolean;
  disabled: boolean;
  canManage: boolean;
  onSelect: (id: string) => void;
  onEdit: (zone: Zone) => void;
  onSchedule: (zone: Zone) => void;
  onArchive: (zone: Zone) => void;
}

/** Native selection button and three SIBLING actions: no nested buttons. */
export function ZoneListItem({
  zone, language, selected, disabled, canManage, onSelect, onEdit, onSchedule, onArchive,
}: Props) {
  const t = (key: Parameters<typeof zoneText>[1], values?: Record<string, string | number>) =>
    zoneText(language, key, values);
  return (
    <div data-testid={"zone-list-item-" + zone.id}
      className={"flex min-w-0 items-center gap-1 rounded-xl transition-colors " +
        (selected ? "bg-emerald-50 text-[#1e87bb]" : "text-slate-600 hover:bg-slate-50")}>
      <button type="button" aria-current={selected ? "true" : undefined}
        aria-label={t("zoneSelect", { name: zone.name })} disabled={disabled}
        onClick={() => onSelect(zone.id)}
        className="flex min-h-12 min-w-0 flex-1 flex-col items-start rounded-lg p-3 text-start focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1e87bb] disabled:cursor-not-allowed disabled:opacity-50">
        <span className="flex min-w-0 items-center gap-2 font-semibold">
          <span className="truncate">{zone.name}</span>
          {(!zone.startDate || !zone.intervalDays) && (
            <span title={t("zoneScheduleWarning")} aria-label={t("zoneScheduleWarning")} className="text-amber-600">
              <AlertCircle aria-hidden="true" className="h-4 w-4" />
            </span>
          )}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          <span>{zone.intervalDays ? t("zoneEvery", { days: zone.intervalDays }) : t("zoneUnscheduled")}</span>
          {zone.startDate && <span dir="ltr">({zone.startDate})</span>}
          <span className="text-[#1e87bb]">{t("zoneShops", { count: zone.shopsCount || 0 })}</span>
        </span>
      </button>
      {canManage && (
        <div className="flex shrink-0 items-center gap-0.5 pe-2">
          <button type="button" onClick={() => onEdit(zone)} disabled={disabled}
            aria-label={t("zoneEdit", { name: zone.name })} title={t("zoneEdit", { name: zone.name })}
            className="rounded-lg p-2 text-slate-500 hover:bg-white hover:text-[#1e87bb] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1e87bb] disabled:opacity-40">
            <Pencil aria-hidden="true" className="h-4 w-4" />
          </button>
          <button type="button" onClick={() => onSchedule(zone)} disabled={disabled}
            aria-label={t("zoneSchedule", { name: zone.name })} title={t("zoneSchedule", { name: zone.name })}
            className="rounded-lg p-2 text-slate-500 hover:bg-white hover:text-[#1e87bb] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1e87bb] disabled:opacity-40">
            <CalendarDays aria-hidden="true" className="h-4 w-4" />
          </button>
          <button type="button" onClick={() => onArchive(zone)} disabled={disabled}
            aria-label={t("zoneArchive", { name: zone.name })} title={t("zoneArchive", { name: zone.name })}
            className="rounded-lg p-2 text-slate-500 hover:bg-white hover:text-red-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-600 disabled:opacity-40">
            <Archive aria-hidden="true" className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
