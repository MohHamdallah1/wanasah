import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type { Vehicle } from "./contracts";
import {
  formatBusinessDate,
  formatBusinessNumber,
  notesForVehicle,
  type VehicleNote,
} from "./vehiclePresentation";

interface VehicleDetailsModalProps {
  vehicle: Vehicle;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function VehicleDetailsModal({ vehicle, open, onOpenChange }: VehicleDetailsModalProps) {
  const { t, i18n } = useTranslation();
  const notes = notesForVehicle(vehicle);
  const language = i18n.language;
  const empty = "—";

  const noteText = (note: VehicleNote) => {
    if (note.kind === "custody") return t("representativesVehicles.vehicles.notes.custodyUnavailable");
    if (note.kind === "maintenance") {
      return t(
        note.overdue
          ? "representativesVehicles.vehicles.notes.maintenanceOverdue"
          : "representativesVehicles.vehicles.notes.maintenanceDue",
        { date: formatBusinessDate(note.date, language) },
      );
    }
    if (note.kind === "license") {
      return t("representativesVehicles.vehicles.notes.licenseExpired", {
        date: formatBusinessDate(note.date, language),
      });
    }
    return t("representativesVehicles.vehicles.notes.oilDue", {
      mileage: formatBusinessNumber(note.mileage, language),
    });
  };

  const rows = [
    [t("representativesVehicles.vehicles.fields.plate"), vehicle.plate_number],
    [t("representativesVehicles.vehicles.fields.type"), vehicle.vehicle_type || empty],
    [t("representativesVehicles.vehicles.fields.mileage"), formatBusinessNumber(vehicle.current_mileage, language)],
    [t("representativesVehicles.vehicles.fields.nextOilChange"), vehicle.next_oil_change == null ? empty : formatBusinessNumber(vehicle.next_oil_change, language)],
    [t("representativesVehicles.vehicles.fields.licenseExpiry"), vehicle.license_expiry_date ? formatBusinessDate(vehicle.license_expiry_date, language) : empty],
    [t("representativesVehicles.vehicles.fields.nextMaintenanceDate"), vehicle.next_maintenance_date ? formatBusinessDate(vehicle.next_maintenance_date, language) : empty],
    [t("representativesVehicles.vehicles.fields.status"), t(vehicle.is_active ? "representativesVehicles.vehicles.active" : "representativesVehicles.vehicles.inactive")],
    [t("representativesVehicles.vehicles.fields.maintenance"), t(vehicle.maintenance_status === "Active" ? "representativesVehicles.vehicles.maintenance.active" : "representativesVehicles.vehicles.maintenance.inMaintenance")],
    [t("representativesVehicles.vehicles.fields.custody"), t(vehicle.custody_ready ? "representativesVehicles.vehicles.custody.ready" : "representativesVehicles.vehicles.custody.unavailable")],
  ] as const;

  return (
    <Modal
      isOpen={open}
      onClose={() => onOpenChange(false)}
      title={t("representativesVehicles.vehicles.details.title")}
      maxWidth="max-w-xl"
    >
      <div className="space-y-5">
        <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
          {rows.map(([label, value]) => (
            <div key={label} className="rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2.5 text-start">
              <dt className="text-[11px] font-black text-slate-500">{label}</dt>
              <dd className="mt-1 break-words text-sm font-bold text-slate-800">{value}</dd>
            </div>
          ))}
        </dl>

        <section aria-labelledby="vehicle-details-notes">
          <h4 id="vehicle-details-notes" className="text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.notes")}
          </h4>
          {notes.length ? (
            <div className="mt-2 space-y-1.5 rounded-xl border border-rose-100 bg-rose-50/50 px-3 py-2.5">
              {notes.map((note, index) => (
                <p key={`${note.kind}-${index}`} className="text-start text-xs font-bold leading-5 text-rose-700">
                  {noteText(note)}
                </p>
              ))}
            </div>
          ) : (
            <p className="mt-2 rounded-xl border border-slate-100 bg-slate-50/70 px-3 py-2.5 text-start text-xs font-semibold text-slate-500">
              {t("representativesVehicles.vehicles.details.noNotes")}
            </p>
          )}
        </section>
      </div>
    </Modal>
  );
}
