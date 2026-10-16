import { Car, Search } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { useStocktakeUiCopy } from "./uiCopy";
import type { VehicleReconStartController } from "./hooks/useVehicleReconStart";

interface StocktakeVehicleReconModalProps {
  open: boolean;
  controller: VehicleReconStartController;
  onClose: () => void;
  onOpened: () => void;
}

export function StocktakeVehicleReconModal({ open, controller, onClose, onOpened }: StocktakeVehicleReconModalProps) {
  const { copy, dir } = useStocktakeUiCopy();
  const text = copy.vehicle;
  const { searchInput, setSearchInput, items, nextCursor, loading, loadingMore, busyWorkSessionId, notes, setNotes, loadMore, startOrOpen } = controller;

  const handleCandidate = async (workSessionId: number) => {
    const candidate = items.find((item) => item.work_session_id === workSessionId);
    if (!candidate) return;
    if (await startOrOpen(candidate)) onOpened();
  };

  return (
    <Modal isOpen={open} onClose={onClose} title={text.title} maxWidth="max-w-5xl">
      <div dir={dir} className="space-y-4">
        <div className="rounded-xl border border-violet-100 bg-violet-50 p-4 text-sm font-bold text-violet-800">
          {text.hint}
        </div>
        <div className="relative">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input autoFocus value={searchInput} onChange={(event) => setSearchInput(event.target.value)} maxLength={100} placeholder={text.search} className="w-full rounded-xl border border-slate-200 bg-white ps-10 pe-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-violet-500/20" />
        </div>
        <div className="max-h-[420px] overflow-auto rounded-xl border border-slate-200 divide-y divide-slate-100">
          {items.map((item) => {
            const existing = item.existing_stocktake_session_id !== null;
            const busy = busyWorkSessionId === item.work_session_id;
            return (
              <div key={item.work_session_id} className="p-4 bg-white flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center shrink-0"><Car className="w-5 h-5 text-violet-600" aria-hidden="true" /></div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-black text-slate-800">{item.vehicle_location_name}</span>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-slate-100 text-slate-600" dir="ltr">{item.vehicle_location_code}</span>
                      {existing && <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-amber-50 text-amber-700">{text.openStocktake}: {text.statuses[item.existing_stocktake_status as keyof typeof text.statuses] ?? item.existing_stocktake_status}</span>}
                    </div>
                    <div className="text-xs text-slate-500 mt-1">{text.driver}: <span className="font-bold text-slate-700">{item.driver_name}</span> · {text.session} <span dir="ltr">#{item.work_session_id}</span> · <span dir="ltr">{item.session_date}</span></div>
                    <div className="text-[11px] text-slate-400 mt-1">{text.ended}: <span dir="ltr">{item.end_time}</span>{item.existing_stocktake_reference ? ` · ${item.existing_stocktake_reference}` : ""}</div>
                  </div>
                </div>
                <button type="button" disabled={busyWorkSessionId !== null} onClick={() => void handleCandidate(item.work_session_id)} className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:bg-slate-300 text-white text-xs font-black shrink-0">
                  {busy ? text.opening : existing ? text.open : text.start}
                </button>
              </div>
            );
          })}
          {loading && items.length === 0 && <div className="p-8 text-center text-sm text-slate-400">{text.loading}</div>}
          {!loading && items.length === 0 && <div className="p-8 text-center text-sm text-slate-400">{text.empty}</div>}
        </div>
        {nextCursor && <button type="button" onClick={loadMore} disabled={loadingMore} className="w-full py-2.5 rounded-xl bg-violet-50 text-violet-700 text-xs font-black disabled:opacity-50">{loadingMore ? text.loadingMore : text.loadMore}</button>}
        <div>
          <label className="text-xs font-black text-slate-700">{text.notes}</label>
          <textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={4000} className="mt-1 w-full min-h-20 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none" />
        </div>
      </div>
    </Modal>
  );
}
