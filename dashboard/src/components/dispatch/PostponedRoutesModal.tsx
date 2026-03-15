import { RotateCcw } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { PendingRoute } from "@/types/dispatch";

interface PostponedRoutesModalProps {
  isOpen: boolean;
  onClose: () => void;
  routes: PendingRoute[];
  drivers: { id: string; name: string }[];
  onUpdateDriver: (id: string, driverId: string) => void;
  onRestore: (id: string) => void;
}

export function PostponedRoutesModal({
  isOpen,
  onClose,
  routes,
  drivers,
  onUpdateDriver,
  onRestore,
}: PostponedRoutesModalProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="🕒 المناطق المؤجلة" maxWidth="max-w-4xl">
      <div className="space-y-4">
        {routes.length === 0 ? (
          <div className="py-12 text-center text-slate-400">لا توجد مناطق مؤجلة</div>
        ) : (
          <div className="rounded-2xl border border-slate-200 overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-start p-4 text-slate-500 font-bold">المنطقة</th>
                  <th className="text-start p-4 text-slate-500 font-bold">المندوب</th>
                  <th className="text-center p-4 text-slate-500 font-bold">المحلات</th>
                  <th className="w-32 p-4"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {routes.map(route => (
                  <tr key={route.id} className="hover:bg-slate-50">
                    <td className="p-4 font-bold text-slate-800">{route.zoneName}</td>
                    <td className="p-4">
                      <select 
                        value={route.driverId} 
                        onChange={e => onUpdateDriver(route.id, e.target.value)} 
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"
                      >
                        {drivers.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                      </select>
                    </td>
                    <td className="p-4 text-center font-bold text-amber-600">{route.shopsRemaining}</td>
                    <td className="p-4">
                      <button 
                        onClick={() => onRestore(route.id)} 
                        className="w-full bg-emerald-500 text-white px-4 py-2 rounded-xl text-xs font-bold hover:bg-emerald-600 transition-colors flex items-center justify-center gap-2"
                      >
                        <RotateCcw className="w-3.5 h-3.5" /> 
                        استعادة
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}
