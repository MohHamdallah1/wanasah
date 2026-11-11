import { useTranslation } from "react-i18next";
import { DispatchChrome } from "./DispatchChrome";
import "./dispatchNoMotion.css";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import type { TabId } from "@/types/dispatch";

/** Visible structural workspace, with no customer, route or financial data. */
export function DispatchWorkspaceStructure({ activeTab }: { activeTab: TabId }) {
  const { i18n } = useTranslation();
  const zone = dispatchUiText(i18n.language, "zone");
  const shop = dispatchUiText(i18n.language, "shop");
  const table = (
    <div className="min-h-0 flex-1 overflow-hidden rounded-b-2xl bg-white">
      <div className="grid grid-cols-4 gap-3 border-b border-slate-100 px-4 py-3" aria-hidden="true">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-4 rounded bg-slate-100" />
        ))}
      </div>
      <div className="grid grid-cols-4 gap-3 px-4 py-4" aria-hidden="true">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-7 rounded bg-slate-50" />
        ))}
      </div>
    </div>
  );
  return (
    <div data-testid="dispatch-quiet-loading" role="status" aria-busy="true"
      data-testid-workspace="dispatch-structure"
      className={activeTab === "zones"
        ? "dispatch-zones-workbench flex min-h-0 w-full flex-1 flex-col gap-4 xl:flex-row"
        : "flex min-h-0 w-full flex-1 flex-col gap-4"}
    >
      <span data-testid="dispatch-structural-workspace" className="sr-only" aria-hidden="true" />
      {activeTab === "zones" ? (
        <>
          <div className="dispatch-surface flex w-full min-h-40 flex-col rounded-2xl border border-slate-200 bg-white xl:w-[29%] xl:min-w-0">
            <div className="border-b border-slate-100 px-4 py-3 font-bold text-slate-800">{zone}</div>
            <div className="flex-1 p-3"><div className="h-9 rounded-lg bg-slate-50" /></div>
          </div>
          <div className="dispatch-surface flex w-full min-w-0 flex-1 flex-col rounded-2xl border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3 font-bold text-slate-800">{shop}</div>
            {table}
          </div>
        </>
      ) : activeTab === "launch" ? (
        <>
          <div className="dispatch-surface grid grid-cols-2 gap-3 rounded-2xl border border-slate-200 bg-white p-4 xl:grid-cols-4" aria-hidden="true">
            {Array.from({ length: 4 }, (_, i) => <div key={i} className="h-10 rounded-lg bg-slate-50" />)}
          </div>
          <div className="dispatch-surface flex min-h-40 flex-1 flex-col rounded-2xl border border-slate-200 bg-white">{table}</div>
        </>
      ) : (
        <div className="dispatch-surface flex min-h-40 flex-1 flex-col rounded-2xl border border-slate-200 bg-white">
          <div className="flex h-12 shrink-0 items-center justify-end border-b border-slate-100 bg-slate-50 px-3" aria-hidden="true">
            <div className="h-8 w-32 rounded-lg bg-white" />
          </div>
          {table}
        </div>
      )}
    </div>
  );
}

/** Same lightweight shared chrome during first lazy Dispatch chunk download. */
export function DispatchColdFrame() {
  return (
    <div className="dispatch-board flex h-full min-h-0 w-full flex-1 flex-col">
      <DispatchChrome activeTab="routes" admitted={false} permissionKnown={false} />
      <div className="dispatch-content pt-2 pb-0 px-0 w-full h-full flex-1 min-h-0 flex flex-col">
        <DispatchWorkspaceStructure activeTab="routes" />
      </div>
    </div>
  );
}
