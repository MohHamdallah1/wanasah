import { RotateCcw } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import type { PendingRoute } from "@/types/dispatch";
import { currentLocale } from "@/i18n";

export function PostponedRoutesModal({
  isOpen, onClose, routes, onRestore,
}: {
  isOpen: boolean;
  onClose: () => void;
  routes: PendingRoute[];
  onRestore: (id: string) => void;
}) {
  const ar = currentLocale().startsWith("ar");
  return (
    <Modal isOpen={isOpen} onClose={onClose}
      title={ar ? "المناطق المؤجلة" : "Postponed routes"} maxWidth="max-w-4xl">
      <div className="space-y-3">
        {!routes.length ? (
          <p className="py-8 text-center text-sm text-slate-500">
            {ar ? "لا توجد مناطق مؤجلة" : "No postponed routes"}
          </p>
        ) : (
          <div className="max-w-full overflow-x-auto rounded-xl border">
            <table className="w-full min-w-0 text-sm">
              <thead><tr className="bg-slate-50">
                <th className="p-3 text-start">{ar ? "المنطقة" : "Zone"}</th>
                <th className="p-3 text-start">{ar ? "التعيين" : "Assignment"}</th>
                <th className="p-3 text-center">{ar ? "المحلات" : "Shops"}</th>
                <th className="p-3"></th>
              </tr></thead>
              <tbody>
                {routes.map(route => (
                  <tr key={route.id} className="border-t">
                    <td className="p-3 font-semibold">{route.zoneName}</td>
                    <td className="p-3 text-slate-600">
                      {ar ? "يُحدد المندوب والسيارة عند الاستئناف" :
                        "Select both representative and vehicle on resume"}
                    </td>
                    <td className="p-3 text-center">{route.shopsRemaining}</td>
                    <td className="p-3">
                      <button type="button" disabled={route.can_execute !== true}
                        onClick={() => onRestore(route.id)}
                        className="inline-flex gap-2 rounded-lg border px-3 py-2 text-sm disabled:opacity-50">
                        <RotateCcw className="h-4 w-4" />
                        {ar ? "اختيار واستئناف" : "Select and resume"}
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
