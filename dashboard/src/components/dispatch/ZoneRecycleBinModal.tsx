import { Search, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import type { Zone } from "@/types/dispatch";
import { zoneText } from "@/features/dispatch/zones/zoneUi";

interface ZoneRecycleBinModalProps {
  isOpen: boolean;
  onClose: () => void;
  recycleSearchQuery: string;
  onRecycleSearchQueryChange: (query: string) => void;
  filteredRecycleBin: Zone[];
  onRestoreZone: (id: string) => void;
}
export function ZoneRecycleBinModal({
  isOpen,onClose,recycleSearchQuery,onRecycleSearchQueryChange,
  filteredRecycleBin,onRestoreZone,
}: ZoneRecycleBinModalProps) {
  const { i18n } = useTranslation();
  const t=(key: Parameters<typeof zoneText>[1], vars?:Record<string,string|number>)=>zoneText(i18n.language,key,vars);
  return <Modal isOpen={isOpen} onClose={onClose} title={t("recycleTitle")}>
    <div className="space-y-4" dir={i18n.dir()}>
      <p className="text-xs text-amber-900" role="note">{t("recycleWarning")}</p>
      <div className="relative">
        <Search aria-hidden className="absolute start-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input type="search" value={recycleSearchQuery}
          onChange={e=>onRecycleSearchQueryChange(e.target.value)}
          aria-label={t("recycleSearch")} placeholder={t("recycleSearch")}
          className="w-full rounded-xl border border-slate-200 bg-slate-50 ps-9 pe-4 py-2.5 text-sm focus-visible:ring-2 focus-visible:ring-[#1e87bb]" />
      </div>
      {filteredRecycleBin.length===0 ? <p className="py-12 text-center text-slate-500">{t("recycleEmpty")}</p> : (
        <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto rounded-2xl border border-slate-100">
          {filteredRecycleBin.map(zone=><li key={zone.id} className="flex items-center justify-between gap-3 p-4">
            <span className="min-w-0 truncate font-bold text-slate-800">{zone.name}</span>
            <button type="button" onClick={()=>onRestoreZone(zone.id)}
              aria-label={t("recycleRestore",{name:zone.name})}
              className="flex shrink-0 items-center gap-2 rounded-xl bg-emerald-50 px-4 py-2 text-sm font-bold text-[#1e87bb] hover:bg-emerald-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#1e87bb]">
              <RotateCcw aria-hidden className="h-4 w-4"/>{t("recycleRestore",{name:zone.name})}
            </button>
          </li>)}
        </ul>
      )}
    </div>
  </Modal>;
}
