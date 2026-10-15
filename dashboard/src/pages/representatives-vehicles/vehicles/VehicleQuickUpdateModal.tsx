import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type { UpdateVehicleInput, Vehicle, VehicleMaintenanceStatus } from "./contracts";
import { localDateKey } from "./vehiclePresentation";

export type VehicleQuickActionKind = "oil" | "maintenance" | "license";

interface VehicleQuickUpdateModalProps {
  vehicle: Vehicle;
  kind: VehicleQuickActionKind;
  open: boolean;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (input: UpdateVehicleInput, requestId: string) => Promise<void> | void;
}

type PendingOperation = { fingerprint: string; requestId: string };

export function VehicleQuickUpdateModal({
  vehicle,
  kind,
  open,
  busy = false,
  onClose,
  onSubmit,
}: VehicleQuickUpdateModalProps) {
  const { t, i18n } = useTranslation();
  const [value, setValue] = useState("");
  const [validation, setValidation] = useState("");
  const operation = useRef<PendingOperation | null>(null);

  const requestIdFor = (input: UpdateVehicleInput) => {
    const fingerprint = JSON.stringify(input);
    if (!operation.current || operation.current.fingerprint !== fingerprint) {
      operation.current = { fingerprint, requestId: crypto.randomUUID() };
    }
    return operation.current.requestId;
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    let input: UpdateVehicleInput;

    if (kind === "oil") {
      const normalized = value.trim();
      if (!/^\d+$/.test(normalized)) {
        setValidation(t("representativesVehicles.vehicles.quickActions.oilInvalid"));
        return;
      }
      const nextOil = Number(normalized);
      if (!Number.isSafeInteger(nextOil) || nextOil < 0 || nextOil > 2_147_483_647) {
        setValidation(t("representativesVehicles.vehicles.quickActions.oilInvalid"));
        return;
      }
      if (nextOil <= vehicle.current_mileage) {
        setValidation(t("representativesVehicles.vehicles.quickActions.oilMustBeFuture", {
          mileage: new Intl.NumberFormat(
            i18n.language.startsWith("ar") ? "ar-JO-u-nu-latn" : "en-US-u-nu-latn",
          ).format(vehicle.current_mileage),
        }));
        return;
      }
      if (nextOil === vehicle.next_oil_change) {
        setValidation(t("representativesVehicles.vehicles.form.noChanges"));
        return;
      }
      input = { next_oil_change: nextOil };
    } else {
      if (!value) {
        setValidation(t("representativesVehicles.vehicles.quickActions.dateRequired"));
        return;
      }
      const current = kind === "maintenance"
        ? vehicle.next_maintenance_date
        : vehicle.license_expiry_date;
      if (value === current) {
        setValidation(t("representativesVehicles.vehicles.form.noChanges"));
        return;
      }
      input = kind === "maintenance"
        ? {
            next_maintenance_date: value,
            ...(vehicle.maintenance_status === "In_Maintenance"
              ? { maintenance_status: "Active" as VehicleMaintenanceStatus }
              : {}),
          }
        : { license_expiry_date: value };
    }

    setValidation("");
    await onSubmit(input, requestIdFor(input));
  };

  const titleKey = `representativesVehicles.vehicles.quickActions.${kind}.title`;
  const labelKey = kind === "oil"
    ? "representativesVehicles.vehicles.fields.nextOilChange"
    : kind === "maintenance"
      ? "representativesVehicles.vehicles.fields.nextMaintenanceDate"
      : "representativesVehicles.vehicles.fields.licenseExpiry";

  return (
    <Modal isOpen={open} onClose={() => { if (!busy) onClose(); }} title={t(titleKey)} maxWidth="max-w-md">
      <form dir={i18n.dir()} className="space-y-4" onSubmit={submit}>
        <div className="space-y-1.5">
          <label htmlFor={`vehicle-quick-${kind}`} className="block text-start text-xs font-black text-slate-700">
            {t(labelKey)}
          </label>
          {kind === "oil" ? (
            <input
              id={`vehicle-quick-${kind}`}
              autoFocus
              inputMode="numeric"
              dir="ltr"
              value={value}
              onChange={(event) => { setValidation(""); setValue(event.target.value); }}
              className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-right font-mono text-sm font-semibold tabular-nums text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60"
              placeholder={t("representativesVehicles.vehicles.quickActions.oil.placeholder")}
              disabled={busy}
            />
          ) : (
            <input
              id={`vehicle-quick-${kind}`}
              autoFocus
              type="date"
              dir="ltr"
              min={localDateKey()}
              value={value}
              onChange={(event) => { setValidation(""); setValue(event.target.value); }}
              className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60"
              disabled={busy}
            />
          )}
        </div>

        {kind === "maintenance" && vehicle.maintenance_status === "In_Maintenance" ? (
          <p className="rounded-xl bg-emerald-50 px-3 py-2 text-start text-xs font-semibold leading-5 text-emerald-800 ring-1 ring-emerald-200">
            {t("representativesVehicles.vehicles.quickActions.maintenance.returnToServiceHint")}
          </p>
        ) : null}

        {validation ? <p role="alert" className="text-start text-xs font-bold text-rose-700">{validation}</p> : null}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={busy} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">
            {t("common.cancel")}
          </button>
          <button type="submit" disabled={busy} className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-black text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">
            {busy ? t("common.saving") : t("common.save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
