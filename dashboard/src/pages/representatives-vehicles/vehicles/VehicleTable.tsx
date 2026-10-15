import { useTranslation } from "react-i18next";

import type { Vehicle } from "./contracts";
import { VehicleRowActions } from "./VehicleRowActions";

interface VehicleTableProps {
  items: Vehicle[];
  loading?: boolean;
  canManage: boolean;
  onEdit: (vehicle: Vehicle) => void;
  onLifecycle: (vehicle: Vehicle) => void;
}

type VehicleNote =
  | { kind: "custody" }
  | { kind: "maintenance"; date: string; overdue: boolean }
  | { kind: "license"; date: string }
  | { kind: "oil"; mileage: number; due: boolean };

const localDateKey = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

const formatBusinessDate = (value: string, language: string) => {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return new Intl.DateTimeFormat(
    language.startsWith("ar") ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
    { year: "numeric", month: "2-digit", day: "2-digit" },
  ).format(date);
};

const formatBusinessNumber = (value: number, language: string) =>
  new Intl.NumberFormat(
    language.startsWith("ar") ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
  ).format(value);

const notesForVehicle = (vehicle: Vehicle): VehicleNote[] => {
  const today = localDateKey();
  const notes: VehicleNote[] = [];
  if (!vehicle.custody_ready) notes.push({ kind: "custody" });
  if (vehicle.next_maintenance_date) {
    notes.push({
      kind: "maintenance",
      date: vehicle.next_maintenance_date,
      overdue: vehicle.next_maintenance_date < today,
    });
  }
  if (vehicle.license_expiry_date && vehicle.license_expiry_date < today) {
    notes.push({ kind: "license", date: vehicle.license_expiry_date });
  }
  if (vehicle.next_oil_change !== null && vehicle.next_oil_change !== undefined) {
    notes.push({
      kind: "oil",
      mileage: vehicle.next_oil_change,
      due: vehicle.current_mileage >= vehicle.next_oil_change,
    });
  }
  return notes;
};

const noteIsOverdue = (note: VehicleNote) =>
  note.kind === "custody" ||
  note.kind === "license" ||
  (note.kind === "maintenance" && note.overdue) ||
  (note.kind === "oil" && note.due);

export function VehicleTable({ items, loading = false, canManage, onEdit, onLifecycle }: VehicleTableProps) {
  const { t, i18n } = useTranslation();

  const noteText = (note: VehicleNote) => {
    if (note.kind === "custody") return t("representativesVehicles.vehicles.notes.custodyUnavailable");
    if (note.kind === "maintenance") {
      return t(
        note.overdue ? "representativesVehicles.vehicles.notes.maintenanceOverdue" : "representativesVehicles.vehicles.notes.maintenanceUpcoming",
        { date: formatBusinessDate(note.date, i18n.language) },
      );
    }
    if (note.kind === "license") {
      return t("representativesVehicles.vehicles.notes.licenseExpired", { date: formatBusinessDate(note.date, i18n.language) });
    }
    if (note.due) {
      return t("representativesVehicles.vehicles.notes.oilDue", { mileage: formatBusinessNumber(note.mileage, i18n.language) });
    }
    return `${t("representativesVehicles.vehicles.fields.nextOilChange")}: ${formatBusinessNumber(note.mileage, i18n.language)}`;
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
                    {notes.map((note, noteIndex) => (
                      <p key={`${vehicle.id}-${note.kind}-${noteIndex}`} className={`text-[10px] font-bold leading-4 ${noteIsOverdue(note) ? "text-rose-700" : "text-slate-500"}`}>
                        {noteText(note)}
                      </p>
                    ))}
                  </div>
                ) : <span className="text-xs font-semibold text-slate-400">—</span>}
              </td>
              <td className="border-b border-slate-100 px-4 py-2 text-center">
                <VehicleRowActions vehicle={vehicle} canManage={canManage} onEdit={onEdit} onLifecycle={onLifecycle} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
