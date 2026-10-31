import { useTranslation } from "react-i18next";
import { Lock } from "lucide-react";
import { Modal } from "@/components/ui/modal";
import { CustomSelect } from "@/components/ui/custom-select";
import type { PendingRoute } from "@/types/dispatch";

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
  onConfirmAction: () => void;
  onAdjustLoad: () => void;
}

export function RouteManagementModal({
  isOpen, onClose, routeModalType, activeRoute, drivers,
  transferDriverId, onTransferDriverChange, vehicles, selectedVehicleId,
  onVehicleChange, onConfirmAction, onAdjustLoad,
}: RouteManagementModalProps) {
  const { t, i18n } = useTranslation();
  const identityLocked = Boolean(activeRoute?.sessionBound);
  const sessionEnded = Boolean(activeRoute?.sessionEnded);
  const transferBlocked = routeModalType === "transfer" && identityLocked;
  const actionBlocked = !activeRoute || sessionEnded || transferBlocked;
  // Adjust Load is bound to the Route's existing physical vehicle. A vehicle
  // reassignment is a separate route-only action, never an implied stock move.
  const canAdjust = !!activeRoute && !sessionEnded &&
    selectedVehicleId === activeRoute.vehicleId && activeRoute.can_execute === true;

  return (
    <Modal isOpen={isOpen} onClose={onClose}
      title={t(routeModalType === "follow_up" ? "dispatchRouteSafety.followUp" : "dispatchRouteSafety.transfer")}
      footer={<button type="button" onClick={onConfirmAction} disabled={actionBlocked}
        className="px-8 py-2.5 rounded-xl bg-[#1e87bb] text-white font-bold disabled:opacity-50">
        {t("dispatchRouteSafety.confirmRouteOnly")}
      </button>}>
      <div dir={i18n.dir()} className="space-y-6">
        {identityLocked && <div className="flex items-center gap-2 rounded-xl border p-3 text-sm" role="status">
          <Lock className="size-4" />{t("dispatchRouteSafety.sessionLocked")}
        </div>}
        {sessionEnded && <p role="alert">{t("dispatchRouteSafety.sessionEnded")}</p>}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <span className="text-xs font-semibold">{t("dispatchRouteSafety.driver")}</span>
            {routeModalType === "follow_up" || identityLocked
              ? <div className="rounded-xl border p-2.5">{activeRoute?.driverName}</div>
              : <CustomSelect label="" options={drivers.filter(d => d.id !== activeRoute?.driverId)
                  .map(d => ({ id: d.id, label: d.name }))} value={transferDriverId}
                  onChange={onTransferDriverChange} />}
          </div>
          <CustomSelect label={t("dispatchRouteSafety.vehicle")}
            options={vehicles.map(v => ({ id: v.id, label: v.label }))}
            value={selectedVehicleId} onChange={onVehicleChange}
            disabled={identityLocked || sessionEnded} />
        </div>
        <section className="rounded-xl border p-4 space-y-3" aria-label={t("dispatchAdjustLoad.title")}>
          <p className="text-sm">{t("dispatchRouteSafety.separateStock")}</p>
          <button type="button" onClick={onAdjustLoad} disabled={!canAdjust}
            className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-50">
            {t("dispatchAdjustLoad.title")}
          </button>
          {!canAdjust && selectedVehicleId !== activeRoute?.vehicleId &&
            <p role="status" className="text-xs">{t("dispatchRouteSafety.adjustCurrentVehicle")}</p>}
        </section>
      </div>
    </Modal>
  );
}
