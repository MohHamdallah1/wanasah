import { Info, MoreHorizontal, Package, Pencil, Power, PowerOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Vehicle } from "./contracts";

interface VehicleRowActionsProps {
  vehicle: Vehicle;
  canManage: boolean;
  onView: (vehicle: Vehicle) => void;
  onLoad: (vehicle: Vehicle) => void;
  onEdit: (vehicle: Vehicle) => void;
  onLifecycle: (vehicle: Vehicle) => void;
}

export function VehicleRowActions({
  vehicle,
  canManage,
  onView,
  onLoad,
  onEdit,
  onLifecycle,
}: VehicleRowActionsProps) {
  const { t, i18n } = useTranslation();
  const manageDescriptionId = `vehicle-manage-action-${vehicle.id}`;
  const blocked = t("representativesVehicles.vehicles.permissions.manageRequired");

  return (
    <DropdownMenu dir={i18n.dir()} modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t("representativesVehicles.vehicles.actionsMenu", {
            plate: vehicle.plate_number,
          })}
          className="inline-grid h-9 w-9 place-items-center rounded-xl text-slate-500 transition hover:bg-white hover:text-slate-900 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        sideOffset={6}
        collisionPadding={8}
        className="w-52 rounded-xl border-slate-200 bg-white p-1.5 shadow-xl"
      >
        <DropdownMenuItem
          onSelect={() => onView(vehicle)}
          className="gap-2 rounded-lg px-2.5 py-2 text-xs font-black text-slate-700"
        >
          <Info className="h-4 w-4" aria-hidden="true" />
          {t("representativesVehicles.vehicles.details.action")}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => onLoad(vehicle)}
          className="gap-2 rounded-lg px-2.5 py-2 text-xs font-black text-slate-700"
        >
          <Package className="h-4 w-4" aria-hidden="true" />
          {t("representativesVehicles.vehicles.load.action")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canManage}
          aria-describedby={!canManage ? manageDescriptionId : undefined}
          title={!canManage ? blocked : undefined}
          onSelect={() => onEdit(vehicle)}
          className="gap-2 rounded-lg px-2.5 py-2 text-xs font-black text-slate-700"
        >
          <Pencil className="h-4 w-4" aria-hidden="true" />
          {t("representativesVehicles.vehicles.edit")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!canManage}
          aria-describedby={!canManage ? manageDescriptionId : undefined}
          title={!canManage ? blocked : undefined}
          onSelect={() => onLifecycle(vehicle)}
          className={`gap-2 rounded-lg px-2.5 py-2 text-xs font-black ${
            vehicle.is_active
              ? "text-rose-700 focus:bg-rose-50 focus:text-rose-800"
              : "text-emerald-700 focus:bg-emerald-50 focus:text-emerald-800"
          }`}
        >
          {vehicle.is_active ? (
            <PowerOff className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Power className="h-4 w-4" aria-hidden="true" />
          )}
          {t(
            vehicle.is_active
              ? "representativesVehicles.vehicles.lifecycle.deactivate"
              : "representativesVehicles.vehicles.lifecycle.reactivate",
          )}
        </DropdownMenuItem>
        <span id={manageDescriptionId} className="sr-only">{blocked}</span>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
