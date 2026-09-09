import { Package, Eraser, Lock } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import { QuantityInput } from "@/components/ui/quantity-input";
import { PendingRoute } from "@/types/dispatch";

// DASHBOARD_DISPATCH_ROUTE_CONTRACT_V3
interface RouteManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  routeModalType: "follow_up" | "transfer";
  activeRoute: PendingRoute | null;
  drivers: { id: string; name: string }[];
  transferDriverId: string;
  onTransferDriverChange: (id: string) => void;
  vehicles: { id: string; label: string }[];
  selectedVehicleId: string;
  onVehicleChange: (id: string) => void;
  products: { id: string; name: string }[];
  preloadQuantities: Record<string, number>;
  onPreloadQuantitiesChange: (quantities: Record<string, number>) => void;
  onClearInventory: () => void;
  onConfirmAction: () => void;
}

export function RouteManagementModal({
  isOpen,
  onClose,
  routeModalType,
  activeRoute,
  drivers,
  transferDriverId,
  onTransferDriverChange,
  vehicles,
  selectedVehicleId,
  onVehicleChange,
  products,
  preloadQuantities,
  onPreloadQuantitiesChange,
  onClearInventory,
  onConfirmAction,
}: RouteManagementModalProps) {
  const identityLocked = Boolean(activeRoute?.sessionBound);
  const sessionEnded = Boolean(activeRoute?.sessionEnded);
  const transferBlocked = routeModalType === "transfer" && identityLocked;
  const actionBlocked = !activeRoute || sessionEnded || transferBlocked;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={routeModalType === "follow_up" ? "متابعة الحمولة والمسار" : "تحويل لمندوب آخر"}
      footer={
        <button
          onClick={onConfirmAction}
          disabled={actionBlocked}
          className="px-8 py-2.5 rounded-xl bg-[#1e87bb] text-white font-bold hover:bg-[#0f766e] transition-colors shadow-lg shadow-[#1e87bb]/20 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          تأكيد وإطلاق
        </button>
      }
    >
      <div className="space-y-6">
        {identityLocked && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-800 flex items-center gap-2">
            <Lock className="w-4 h-4 shrink-0" />
            تم ربط WorkSession؛ المندوب والسيارة أصبحا عهدة تاريخية ولا يمكن تبديلهما.
          </div>
        )}

        {sessionEnded && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-bold text-red-700">
            WorkSession منتهية. استخدم مسار التراجع المخصص إن كان مسموحاً، أو أغلق/أجّل خط السير.
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold text-slate-600">المندوب / Driver</span>
            {routeModalType === "follow_up" || identityLocked ? (
              <div className="px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-500 font-medium text-sm">
                {activeRoute?.driverName}
              </div>
            ) : (
              <CustomSelect
                label=""
                options={drivers
                  .filter((driver) => driver.id !== activeRoute?.driverId)
                  .map((driver) => ({ id: driver.id, label: driver.name }))}
                value={transferDriverId}
                onChange={onTransferDriverChange}
              />
            )}
          </div>

          <CustomSelect
            label="السيارة / Vehicle"
            options={vehicles.map((vehicle) => ({ id: vehicle.id, label: vehicle.label }))}
            value={selectedVehicleId}
            onChange={onVehicleChange}
            disabled={identityLocked || sessionEnded}
          />
        </div>

        <div className="rounded-2xl border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 bg-slate-50/80 border-b border-slate-200 flex items-center justify-between">
            <h4 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <Package className="w-4 h-4 text-[#1e87bb]" />
              الحمولة المستهدفة للسيارة
            </h4>
            <button
              onClick={onClearInventory}
              disabled={sessionEnded}
              className="text-xs font-bold text-red-500 hover:text-red-600 flex items-center gap-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Eraser className="w-3.5 h-3.5" />
              تصفير جميع الكميات
            </button>
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="bg-white border-b border-slate-100">
                <th className="text-start p-2 text-slate-500 font-bold text-[11px]">المنتج</th>
                <th className="text-center p-2 font-bold text-slate-500 text-[11px]">الكمية المستهدفة (كرتونة)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {products.map((product) => (
                <tr key={product.id}>
                  <td className="p-2 font-medium text-slate-800">{product.name}</td>
                  <td className="p-2">
                    <div className="flex justify-center">
                      <QuantityInput
                        value={preloadQuantities[product.id] ?? 0}
                        onChange={(quantity) =>
                          onPreloadQuantitiesChange({
                            ...preloadQuantities,
                            [product.id]: quantity,
                          })
                        }
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
}
