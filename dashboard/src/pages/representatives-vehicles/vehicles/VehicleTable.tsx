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

export function VehicleTable({ items, loading = false, canManage, onEdit, onLifecycle }: VehicleTableProps) {
  const { t, i18n } = useTranslation();

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
        <col className="w-[20%]" /><col className="w-[17%]" /><col className="w-[14%]" />
        <col className="w-[14%]" /><col className="w-[15%]" /><col className="w-[13%]" /><col className="w-[7%]" />
      </colgroup>
      <thead className="sticky top-0 z-10 bg-slate-50/95 text-[11px] font-black text-slate-500 backdrop-blur">
        <tr>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.plate")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.type")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.mileage")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.status")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.maintenance")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-start">{t("representativesVehicles.vehicles.fields.custody")}</th>
          <th className="border-b border-slate-200 px-4 py-2.5 text-center">{t("representativesVehicles.vehicles.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((vehicle) => (
          <tr key={vehicle.id} className="group transition hover:bg-amber-50/55">
            <td className="border-b border-slate-100 px-4 py-3 text-start font-black text-slate-800"><bdi dir="ltr">{vehicle.plate_number}</bdi></td>
            <td className="border-b border-slate-100 px-4 py-3 text-start font-semibold text-slate-600">{vehicle.vehicle_type || "—"}</td>
            <td className="border-b border-slate-100 px-4 py-3 text-start font-mono font-semibold tabular-nums text-slate-600"><bdi dir="ltr">{vehicle.current_mileage}</bdi></td>
            <td className="border-b border-slate-100 px-4 py-3 text-start">
              <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-black ${vehicle.is_active ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-slate-100 text-slate-600 ring-1 ring-slate-200"}`}>
                {t(vehicle.is_active ? "representativesVehicles.vehicles.active" : "representativesVehicles.vehicles.inactive")}
              </span>
            </td>
            <td className="border-b border-slate-100 px-4 py-3 text-start">
              <div className="flex flex-col items-start gap-1.5">
                <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-black ${vehicle.maintenance_status === "Active" ? "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200" : "bg-amber-50 text-amber-800 ring-1 ring-amber-200"}`}>
                  {t(vehicle.maintenance_status === "Active" ? "representativesVehicles.vehicles.maintenance.active" : "representativesVehicles.vehicles.maintenance.inMaintenance")}
                </span>
                {vehicle.next_maintenance_date ? (
                  <span className={`text-[10px] font-bold leading-4 ${vehicle.next_maintenance_date < localDateKey() ? "text-amber-700" : "text-slate-500"}`}>
                    {t("representativesVehicles.vehicles.fields.nextMaintenanceDate")}: {formatBusinessDate(vehicle.next_maintenance_date, i18n.language)}
                    {vehicle.next_maintenance_date < localDateKey() ? ` \u00b7 ${t("representativesVehicles.vehicles.maintenanceSchedule.overdue")}` : ""}
                  </span>
                ) : null}
              </div>
            </td>
            <td className="border-b border-slate-100 px-4 py-3 text-start text-xs font-black">
              <span className={vehicle.custody_ready ? "text-emerald-700" : "text-rose-700"}>
                {t(vehicle.custody_ready ? "representativesVehicles.vehicles.custody.ready" : "representativesVehicles.vehicles.custody.unavailable")}
              </span>
            </td>
            <td className="border-b border-slate-100 px-4 py-2 text-center">
              <VehicleRowActions vehicle={vehicle} canManage={canManage} onEdit={onEdit} onLifecycle={onLifecycle} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
