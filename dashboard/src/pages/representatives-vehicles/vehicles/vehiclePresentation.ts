import type { Vehicle } from "./contracts";

export type VehicleNote =
  | { kind: "custody" }
  | { kind: "maintenance"; date: string; overdue: boolean }
  | { kind: "license"; date: string }
  | { kind: "oil"; mileage: number };

export const localDateKey = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

export const formatBusinessDate = (value: string, language: string) => {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return new Intl.DateTimeFormat(
    language.startsWith("ar") ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
    { year: "numeric", month: "2-digit", day: "2-digit" },
  ).format(date);
};

export const formatBusinessNumber = (value: number, language: string) =>
  new Intl.NumberFormat(
    language.startsWith("ar") ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
  ).format(value);

export const notesForVehicle = (vehicle: Vehicle): VehicleNote[] => {
  const today = localDateKey();
  const notes: VehicleNote[] = [];

  if (!vehicle.custody_ready) notes.push({ kind: "custody" });

  if (vehicle.next_maintenance_date && vehicle.next_maintenance_date <= today) {
    notes.push({
      kind: "maintenance",
      date: vehicle.next_maintenance_date,
      overdue: vehicle.next_maintenance_date < today,
    });
  }

  if (vehicle.license_expiry_date && vehicle.license_expiry_date < today) {
    notes.push({ kind: "license", date: vehicle.license_expiry_date });
  }

  if (
    vehicle.next_oil_change !== null &&
    vehicle.next_oil_change !== undefined &&
    vehicle.current_mileage >= vehicle.next_oil_change
  ) {
    notes.push({ kind: "oil", mileage: vehicle.next_oil_change });
  }

  return notes;
};
