import { useTranslation } from "react-i18next";

import type { Vehicle } from "./contracts";
import { VehicleRowActions } from "./VehicleRowActions";
import {
  formatBusinessDate,
  formatBusinessNumber,
  notesForVehicle,
  type VehicleNote,
} from "./vehiclePresentation";

interface VehicleTableProps {
  items: Vehicle[];
  loading?: boolean;
  canManage: boolean;
  onView: (vehicle: Vehicle) => void;
  onLoad: (vehicle: Vehicle) => void;
  onEdit: (vehicle: Vehicle) => void;
  onLifecycle: (vehicle: Vehicle) => void;
  onNoteAction: (vehicle: Vehicle, note: VehicleNote) => void;
}


export function VehicleTable({ items, loading = false, canManage, onView, onLoad, onEdit, onLifecycle, onNoteAction }: VehicleTableProps) {
  const { t, i18n } = useTranslation();

  const noteText = (note: VehicleNote) => {
    if (note.kind === "custody") return t("representativesVehicles.vehicles.notes.custodyUnavailable");
    if (note.kind === "maintenance") {
      return t(
        note.overdue ? "representativesVehicles.vehicles.notes.maintenanceOverdue" : "representativesVehicles.vehicles.notes.maintenanceDue",
        { date: formatBusinessDate(note.date, i18n.language) },
      );
    }
    if (note.kind === "license") {
      return t("representativesVehicles.vehicles.notes.licenseExpired", { date: formatBusinessDate(note.date, i18n.language) });
    }
    return t("representativesVehicles.vehicles.notes.oilDue", { mileage: formatBusinessNumber(note.mileage, i18n.language) });
  };

  if (loading && items.length === 0) {
    return (
      <div className="space-y-2 p-3" role="status" aria-label={t("representativesVehicles.vehicles.loading")}>
        {[0, 1, 2, 3].map((row) => <div key={row} className="h-14 animate-pulse rounded-xl bg-slate-100" />)}
      </div>
    );
  }

  return (
    <table className="w-full min-w-[900px] table-fixed border-separate border-spacing-0 text-start text-sm">
      <colgroup>
        <col className="w-[6%]" /><col className="w-[17%]" /><col className="w-[14%]" /><col className="w-[12%]" />
        <col className="w-[12%]" /><col className="w-[14%]" /><col className="w-[18%]" /><col className="w-[7%]" />
      </colgroup>
      <thead className="sticky top-0 z-10 bg-slate-50/95 text-[11px] font-black text-slate-500 backdrop-blur">
        <tr>
          <th className="border-b border-slate-200 px-3 py-2.5 text-center">#</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.plate")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.type")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.mileage")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.status")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.maintenance")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.notes")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-center">{t("representativesVehicles.vehicles.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((vehicle, index) => {
          const notes = notesForVehicle(vehicle);
          return (
            <tr key={vehicle.id} className="group transition hover:bg-amber-50/55">
              <td className="border-b border-slate-100 px-3 py-3 text-center font-mono font-semibold tabular-nums text-slate-500"><bdi dir="ltr">{index + 1}</bdi></td>
              <td className="border-b border-slate-100 px-4 py-3 text-start font-black text-slate-800"><bdi dir="ltr">{vehicle.plate_number}</bdi></td>
              <td className="border-b border-slate-100 px-4 py-3 text-start font-semibold text-slate-600">{vehicle.vehicle_type || "—"}</td>
              <td className="border-b border-slate-100 px-4 py-3 text-start font-mono font-semibold tabular-nums text-slate-600"><bdi dir="ltr">{vehicle.current_mileage}</bdi></td>
              <td className="border-b border-slate-100 px-4 py-3 text-start">
                <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-black ${vehicle.is_active ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-1 ring-slate-200"}`}>
                  {t(vehicle.is_active ? "representativesVehicles.vehicles.active" : "representativesVehicles.vehicles.inactive")}
                </span>
              </td>
              <td className="border-b border-slate-100 px-4 py-3 text-start">
                <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-black ${vehicle.maintenance_status === "Active" ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-1 ring-amber-200"}`}>
                  {t(vehicle.maintenance_status === "Active" ? "representativesVehicles.vehicles.maintenance.active" : "representativesVehicles.vehicles.maintenance.inMaintenance")}
                </span>
              </td>
              <td className="border-b border-slate-100 px-4 py-3 text-start">
                {notes.length ? (
                  <div className="space-y-1">
                    {notes.map((note, noteIndex) => {
                      const noteClass = `text-start text-[10px] font-bold leading-4 ${note.kind === "maintenance" && !note.overdue ? "text-amber-700" : "text-rose-700"}`;
                      const actionable = note.kind === "custody" || canManage;
                      return actionable ? (
                        <button
                          key={`${vehicle.id}-${note.kind}-${noteIndex}`}
                          type="button"
                          onClick={() => onNoteAction(vehicle, note)}
                          className={`${noteClass} block max-w-full rounded-sm underline-offset-2 transition hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400`}
                        >
                          {noteText(note)}
                        </button>
                      ) : (
                        <p key={`${vehicle.id}-${note.kind}-${noteIndex}`} className={noteClass}>
                          {noteText(note)}
                        </p>
                      );
                    })}
                  </div>
                ) : <span className="text-xs font-semibold text-slate-400">—</span>}
              </td>
              <td className="border-b border-slate-100 px-4 py-2 text-center">
                <VehicleRowActions vehicle={vehicle} canManage={canManage} onView={onView} onLoad={onLoad} onEdit={onEdit} onLifecycle={onLifecycle} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
