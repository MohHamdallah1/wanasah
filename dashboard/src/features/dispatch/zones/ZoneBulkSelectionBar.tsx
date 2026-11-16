import { Archive, ArrowLeftRight, X } from "lucide-react";
import { zoneText } from "./zoneUi";

interface Props {
  language: string;
  visibleSelected: number;
  totalSelected: number;
  visibleRows: number;
  eligibleVisibleRows: number;
  hiddenSelected: number;
  draftBlocked: boolean;
  draftReason: string;
  onMove: () => void;
  onArchive: () => void;
  onKeepVisible: () => void;
  onClear: () => void;
}

/** The bulk bar never silently submits search-hidden or other-zone rows. */
export function ZoneBulkSelectionBar({
  language, visibleSelected, totalSelected, visibleRows,
  eligibleVisibleRows, hiddenSelected, draftBlocked, draftReason, onMove, onArchive, onKeepVisible, onClear,
}: Props) {
  const t=(key: Parameters<typeof zoneText>[1], values?:Record<string,string|number>)=>zoneText(language,key,values);
  return <div role="region" aria-label={t("selectionSummary",{
      visible:visibleSelected,total:totalSelected,matches:visibleRows,current:eligibleVisibleRows,
    })} className="absolute inset-x-2 bottom-2 z-20 rounded-2xl border border-slate-700 bg-slate-900 p-3 text-white shadow-xl sm:inset-x-6" dir={language.startsWith("ar")?"rtl":"ltr"}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs font-semibold" data-testid="zone-bulk-selection-count">
        {t("selectionSummary",{visible:visibleSelected,total:totalSelected,matches:visibleRows,current:eligibleVisibleRows})}
      </p>
      <div className="flex flex-wrap gap-2">
        {hiddenSelected>0 && <button type="button" onClick={onKeepVisible}
          className="rounded-lg bg-amber-200 px-3 py-2 text-xs font-bold text-slate-900 focus-visible:outline focus-visible:outline-2">
          {t("keepVisible")}
        </button>}
        <button type="button" onClick={onMove} disabled={hiddenSelected>0||visibleSelected===0||draftBlocked}
          className="flex items-center gap-1 rounded-lg bg-[#1e87bb] px-3 py-2 text-xs font-bold focus-visible:outline focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-40">
          <ArrowLeftRight aria-hidden="true" className="h-4 w-4"/>{t("moveSelected")}
        </button>
        <button type="button" onClick={onArchive} disabled={hiddenSelected>0||visibleSelected===0||draftBlocked}
          className="flex items-center gap-1 rounded-lg bg-red-600 px-3 py-2 text-xs font-bold focus-visible:outline focus-visible:outline-2 disabled:cursor-not-allowed disabled:opacity-40">
          <Archive aria-hidden="true" className="h-4 w-4"/>{t("archiveSelected")}
        </button>
        <button type="button" onClick={onClear} aria-label={t("clearSelection")}
          className="rounded-lg p-2 text-slate-200 focus-visible:outline focus-visible:outline-2">
          <X aria-hidden="true" className="h-4 w-4"/>
        </button>
      </div>
    </div>
    {draftBlocked && <p role="alert" className="mt-2 text-xs text-amber-200">{draftReason}</p>}
    {hiddenSelected>0 && <p role="alert" className="mt-2 text-xs text-amber-200">
      {t("selectionHidden",{count:hiddenSelected})}
    </p>}
  </div>;
}
