import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  normalizeVehicleText,
  parseOptionalNonnegativeInteger,
  type CreateVehicleInput,
  type UpdateVehicleInput,
  type Vehicle,
  type VehicleMaintenanceStatus,
} from "./contracts";

interface VehicleFormProps {
  vehicle?: Vehicle | null;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (
    input: CreateVehicleInput | UpdateVehicleInput,
    requestId: string,
  ) => Promise<void> | void;
}

type PendingOperation = { fingerprint: string; requestId: string };

const editableNumber = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : String(value);

function FieldLabel({ htmlFor, label, badge }: { htmlFor: string; label: string; badge: string }) {
  return (
    <label htmlFor={htmlFor} className="flex items-center gap-2 text-start text-xs font-black text-slate-700">
      <span>{label}</span>
      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">
        {badge}
      </span>
    </label>
  );
}

export function VehicleForm({
  vehicle = null,
  busy = false,
  onCancel,
  onSubmit,
}: VehicleFormProps) {
  const { t, i18n } = useTranslation();
  const [plate, setPlate] = useState(vehicle?.plate_number ?? "");
  const [vehicleType, setVehicleType] = useState(vehicle?.vehicle_type ?? "");
  const [mileage, setMileage] = useState(editableNumber(vehicle?.current_mileage));
  const [nextOilChange, setNextOilChange] = useState(editableNumber(vehicle?.next_oil_change));
  const [licenseExpiry, setLicenseExpiry] = useState(vehicle?.license_expiry_date ?? "");
  const [nextMaintenanceDate, setNextMaintenanceDate] = useState(vehicle?.next_maintenance_date ?? "");
  const [maintenanceStatus, setMaintenanceStatus] = useState<VehicleMaintenanceStatus>(
    vehicle?.maintenance_status ?? "Active",
  );
  const [validation, setValidation] = useState("");
  const operation = useRef<PendingOperation | null>(null);

  useEffect(() => {
    setPlate(vehicle?.plate_number ?? "");
    setVehicleType(vehicle?.vehicle_type ?? "");
    setMileage(editableNumber(vehicle?.current_mileage));
    setNextOilChange(editableNumber(vehicle?.next_oil_change));
    setLicenseExpiry(vehicle?.license_expiry_date ?? "");
    setNextMaintenanceDate(vehicle?.next_maintenance_date ?? "");
    setMaintenanceStatus(vehicle?.maintenance_status ?? "Active");
    setValidation("");
    operation.current = null;
  }, [vehicle]);

  const requestIdFor = (input: CreateVehicleInput | UpdateVehicleInput) => {
    const fingerprint = JSON.stringify(input);
    if (!operation.current || operation.current.fingerprint !== fingerprint) {
      operation.current = { fingerprint, requestId: crypto.randomUUID() };
    }
    return operation.current.requestId;
  };

  const resetValidation = () => {
    if (validation) setValidation("");
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedPlate = normalizeVehicleText(plate);
    const normalizedType = normalizeVehicleText(vehicleType);
    const parsedMileage = parseOptionalNonnegativeInteger(mileage);
    const parsedOil = parseOptionalNonnegativeInteger(nextOilChange);

    if (!normalizedPlate || normalizedPlate.length > 20 || normalizedPlate.includes("\u0000")) {
      setValidation(t("representativesVehicles.vehicles.form.plateInvalid"));
      return;
    }
    if (normalizedType.length > 50 || normalizedType.includes("\u0000")) {
      setValidation(t("representativesVehicles.vehicles.form.typeInvalid"));
      return;
    }
    if (parsedMileage === null || parsedMileage === undefined) {
      setValidation(t("representativesVehicles.vehicles.form.mileageInvalid"));
      return;
    }
    if (parsedOil === undefined) {
      setValidation(t("representativesVehicles.vehicles.form.oilInvalid"));
      return;
    }
    setValidation("");
    const normalizedLicense = licenseExpiry || null;
    const normalizedMaintenanceDate = nextMaintenanceDate || null;
    const normalizedVehicleType = normalizedType || null;

    if (vehicle) {
      const update: UpdateVehicleInput = {};
      if (normalizedPlate !== normalizeVehicleText(vehicle.plate_number)) {
        update.plate_number = normalizedPlate;
      }
      if (normalizedVehicleType !== vehicle.vehicle_type) {
        update.vehicle_type = normalizedVehicleType;
      }
      if (parsedMileage !== vehicle.current_mileage) {
        update.current_mileage = parsedMileage;
      }
      if (parsedOil !== vehicle.next_oil_change) {
        update.next_oil_change = parsedOil;
      }
      if (normalizedLicense !== vehicle.license_expiry_date) {
        update.license_expiry_date = normalizedLicense;
      }
      if (normalizedMaintenanceDate !== vehicle.next_maintenance_date) {
        update.next_maintenance_date = normalizedMaintenanceDate;
      }
      if (maintenanceStatus !== vehicle.maintenance_status) {
        update.maintenance_status = maintenanceStatus;
      }
      if (Object.keys(update).length === 0) {
        setValidation(t("representativesVehicles.vehicles.form.noChanges"));
        return;
      }
      await onSubmit(update, requestIdFor(update));
      return;
    }

    const createInput: CreateVehicleInput = {
      plate_number: normalizedPlate,
      vehicle_type: normalizedVehicleType,
      current_mileage: parsedMileage,
      next_oil_change: parsedOil,
      license_expiry_date: normalizedLicense,
      next_maintenance_date: normalizedMaintenanceDate,
      maintenance_status: maintenanceStatus,
    };
    await onSubmit(createInput, requestIdFor(createInput));
  };

  const inputClass = "h-10 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:bg-slate-50 disabled:text-slate-500";

  return (
    <form dir={i18n.dir()} className="space-y-4" onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-plate" label={t("representativesVehicles.vehicles.fields.plate")} badge={t("representativesVehicles.vehicles.form.badges.required")} />
          <input
            id="vehicle-plate"
            autoFocus
            required
            aria-required="true"
            maxLength={20}
            value={plate}
            onChange={(event) => { resetValidation(); setPlate(event.target.value); }}
            className={inputClass}
            placeholder={t("representativesVehicles.vehicles.form.platePlaceholder")}
            disabled={busy}
            autoComplete="off"
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-type" label={t("representativesVehicles.vehicles.fields.type")} badge={t("representativesVehicles.vehicles.form.badges.optional")} />
          <input
            id="vehicle-type"
            maxLength={50}
            value={vehicleType}
            onChange={(event) => { resetValidation(); setVehicleType(event.target.value); }}
            className={inputClass}
            placeholder={t("representativesVehicles.vehicles.form.typePlaceholder")}
            disabled={busy}
            autoComplete="off"
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-mileage" label={t("representativesVehicles.vehicles.fields.mileage")} badge={t("representativesVehicles.vehicles.form.badges.required")} />
          <input
            id="vehicle-mileage"
            required
            aria-required="true"
            inputMode="numeric"
            dir="ltr"
            value={mileage}
            onChange={(event) => { resetValidation(); setMileage(event.target.value); }}
            className={`${inputClass} font-mono tabular-nums`}
            disabled={busy}
            autoComplete="off"
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-oil" label={t("representativesVehicles.vehicles.fields.nextOilChange")} badge={t("representativesVehicles.vehicles.form.badges.optional")} />
          <input
            id="vehicle-oil"
            inputMode="numeric"
            dir="ltr"
            value={nextOilChange}
            onChange={(event) => { resetValidation(); setNextOilChange(event.target.value); }}
            className={`${inputClass} font-mono tabular-nums`}
            placeholder={t("representativesVehicles.vehicles.form.optional")}
            disabled={busy}
            autoComplete="off"
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-license" label={t("representativesVehicles.vehicles.fields.licenseExpiry")} badge={t("representativesVehicles.vehicles.form.badges.optional")} />
          <input
            id="vehicle-license"
            type="date"
            dir="ltr"
            value={licenseExpiry}
            onChange={(event) => { resetValidation(); setLicenseExpiry(event.target.value); }}
            className={inputClass}
            disabled={busy}
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-next-maintenance" label={t("representativesVehicles.vehicles.fields.nextMaintenanceDate")} badge={t("representativesVehicles.vehicles.form.badges.optional")} />
          <input
            id="vehicle-next-maintenance"
            type="date"
            dir="ltr"
            value={nextMaintenanceDate}
            onChange={(event) => { resetValidation(); setNextMaintenanceDate(event.target.value); }}
            className={inputClass}
            disabled={busy}
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <FieldLabel htmlFor="vehicle-maintenance" label={t("representativesVehicles.vehicles.fields.maintenance")} badge={t("representativesVehicles.vehicles.form.badges.default")} />
          <select
            id="vehicle-maintenance"
            value={maintenanceStatus}
            onChange={(event) => {
              resetValidation();
              setMaintenanceStatus(event.target.value as VehicleMaintenanceStatus);
            }}
            className={inputClass}
            disabled={busy}
          >
            <option value="Active">{t("representativesVehicles.vehicles.maintenance.active")}</option>
            <option value="In_Maintenance">{t("representativesVehicles.vehicles.maintenance.inMaintenance")}</option>
          </select>
        </div>
      </div>

      <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs font-semibold leading-5 text-slate-500 ring-1 ring-slate-200">
        {t("representativesVehicles.vehicles.form.custodyHint")}
      </p>
      {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}
      <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} disabled={busy} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">
          {t("common.cancel")}
        </button>
        <button type="submit" disabled={busy} className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">
          {busy ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
