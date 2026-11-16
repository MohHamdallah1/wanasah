import { Archive, Plus, Upload } from "lucide-react";
import { zoneText } from "./zoneUi";

interface HeaderActionsProps {
  language: string;
  onOpenArchive: () => void;
  onAddShop: () => void;
}

/** Zone workbench controls retain their original layout and DOM positions. */
export function ZoneShopHeaderActions({ language, onOpenArchive, onAddShop }: HeaderActionsProps) {
  const archiveLabel = zoneText(language, "shopArchiveOpen");
  return <>
    <button type="button" onClick={onOpenArchive}
      aria-label={archiveLabel} title={archiveLabel}
      className="p-2.5 rounded-xl border border-slate-200 text-slate-500 hover:bg-slate-50 shadow-sm hover:text-blue-600 focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
      <Archive aria-hidden="true" className="w-5 h-5" />
    </button>
    <button type="button" onClick={onAddShop}
      className="bg-[#1e87bb] hover:bg-[#0f766e] text-white px-4 py-2.5 rounded-xl text-sm font-bold flex items-center gap-2 shadow-sm focus-visible:ring-2 focus-visible:ring-[#1e87bb] focus-visible:ring-offset-2">
      <Plus aria-hidden="true" className="w-4 h-4" />
      {zoneText(language, "shopAdd")}
    </button>
  </>;
}

interface ImportActionProps {
  language: string;
  onOpenImport: () => void;
}

/** Same import command; labels alone are language-aware. */
export function ZoneShopImportAction({ language, onOpenImport }: ImportActionProps) {
  return <button type="button" onClick={onOpenImport}
    className="w-full rounded-xl border-2 border-dashed border-slate-200 bg-white p-4 flex items-center justify-center gap-3 hover:border-[#1e87bb] hover:bg-slate-50 group shadow-sm focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
    <Upload aria-hidden="true" className="w-6 h-6 text-slate-400 group-hover:text-[#1e87bb]" />
    <span className="text-start">
      <span className="block text-base font-bold text-slate-700 group-hover:text-[#1e87bb]">
        {zoneText(language, "shopBulkImportTitle")}
      </span>
      <span className="block text-xs text-slate-500">
        {zoneText(language, "shopBulkImportHint")}
      </span>
    </span>
  </button>;
}
