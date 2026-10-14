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

export function VehicleForm({
  vehicle = null,
  busy = false,
  onCancel,
  onSubmit,
}: VehicleFormProps) {
  const { t, i18n } = useTranslation();
  const [plate, setPlate] = useState(vehicle?.plate_number ?? "");
  const [vehicleType, setVehicleType] = useState(vehicle?.vehicle_type ?? "");
  const [mileage, setMileage] = useState(editableNumber(vehicle?.current_mileage ?? 0));
  const [nextOilChange, setNextOilChange] = useState(editableNumber(vehicle?.next_oil_change));
  const [licenseExpiry, setLicenseExpiry] = useState(vehicle?.license_expiry_date ?? "");
  const [maintenanceStatus, setMaintenanceStatus] = useState<VehicleMaintenanceStatus>(
    vehicle?.maintenance_status ?? "Active",
  );
  const [validation, setValidation] = useState("");
  const operation = useRef<PendingOperation | null>(null);

  useEffect(() => {
    setPlate(vehicle?.plate_number ?? "");
    setVehicleType(vehicle?.vehicle_type ?? "");
    setMileage(editableNumber(vehicle?.current_mileage ?? 0));
    setNextOilChange(editableNumber(vehicle?.next_oil_change));
    setLicenseExpiry(vehicle?.license_expiry_date ?? "");
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
    if (parsedOil !== null && parsedOil < parsedMileage) {
      setValidation(t("representativesVehicles.vehicles.form.oilBeforeMileage"));
      return;
    }

    setValidation("");
    const normalizedLicense = licenseExpiry || null;
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
      maintenance_status: maintenanceStatus,
    };
    await onSubmit(createInput, requestIdFor(createInput));
  };

  const inputClass = "h-10 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:bg-slate-50 disabled:text-slate-500";

  return (
    <form dir={i18n.dir()} className="space-y-4" onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="min-w-0 space-y-1.5">
          <label htmlFor="vehicle-plate" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.plate")}
          </label>
          <input
            id="vehicle-plate"
            autoFocus
            required
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
          <label htmlFor="vehicle-type" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.type")}
          </label>
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
          <label htmlFor="vehicle-mileage" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.mileage")}
          </label>
          <input
            id="vehicle-mileage"
            required
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
          <label htmlFor="vehicle-oil" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.nextOilChange")}
          </label>
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
          <label htmlFor="vehicle-license" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.licenseExpiry")}
          </label>
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
          <label htmlFor="vehicle-maintenance" className="block text-start text-xs font-black text-slate-700">
            {t("representativesVehicles.vehicles.fields.maintenance")}
          </label>
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
