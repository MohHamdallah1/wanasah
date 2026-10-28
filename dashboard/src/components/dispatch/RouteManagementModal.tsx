import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { mergeDispatchProductWindow } from "@/features/dispatch/productWindow";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { ProductSearchControls } from "./ProductSearchControls";
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
  productScope: string | null;
  productNames: Record<string, string>;
  preloadQuantities: Record<string, number>;
  custodyProductIds?: string[];
  custodyReady?: boolean;
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
  productScope,
  productNames,
  preloadQuantities,
  custodyProductIds = [],
  custodyReady = true,
  onPreloadQuantitiesChange,
  onClearInventory,
  onConfirmAction,
}: RouteManagementModalProps) {
  const { t, i18n } = useTranslation();
  const context = JSON.stringify([productScope, isOpen, activeRoute?.id, activeRoute?.sourceWarehouseId, selectedVehicleId]);
  const [search, setSearch] = useLoadProductSearchText(context);
  const [selectedNames, setSelectedNames] = useState<Record<string, string>>({});
  const page = useDispatchProductSearch(isOpen && activeRoute && selectedVehicleId
    ? `/dispatch/products?purpose=LOAD&route_id=${encodeURIComponent(activeRoute.id)}&vehicle_id=${encodeURIComponent(selectedVehicleId)}` : null, search, productScope ? context : null);
  const pinned: DispatchDiscoveryProduct[] = [...new Set([...custodyProductIds, ...Object.keys(preloadQuantities)])].map((id) => ({ id,
    name: productNames[id] || selectedNames[id] || t("dispatchProductSearch.unavailable"), load: null }));
  const products = mergeDispatchProductWindow(pinned, page.items);
  const identityLocked = Boolean(activeRoute?.sessionBound);
  const sessionEnded = Boolean(activeRoute?.sessionEnded);
  const transferBlocked = routeModalType === "transfer" && identityLocked;
  const actionBlocked = !activeRoute || sessionEnded || transferBlocked || !custodyReady;

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
      <div dir={i18n.dir()} className="space-y-6">
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
              {t("dispatchProductSearch.managementTitle")}
            </h4>
            <button
              onClick={onClearInventory}
              disabled={sessionEnded || !custodyReady}
              className="text-xs font-bold text-red-500 hover:text-red-600 flex items-center gap-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Eraser className="w-3.5 h-3.5" />
              {t("dispatchProductSearch.clear")}
            </button>
          </div>

          <ProductSearchControls search={search} onChange={setSearch} page={page} />
          <fieldset disabled={!custodyReady || sessionEnded}><div className="max-h-[400px] overflow-auto"><table className="w-full text-sm">
            <thead>
              <tr className="bg-white border-b border-slate-100">
                <th className="text-start p-2 text-slate-500 font-bold text-[11px]">{t("dispatchProductSearch.product")}</th>
                <th className="text-center p-2 font-bold text-slate-500 text-[11px]">{t("dispatchProductSearch.cartons")}</th>
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
                        onChange={(quantity) => {
                          setSelectedNames((names) => ({ ...names, [product.id]: product.name }));
                          onPreloadQuantitiesChange({ ...preloadQuantities, [product.id]: quantity });
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div></fieldset>
        </div>
      </div>
    </Modal>
  );
}
