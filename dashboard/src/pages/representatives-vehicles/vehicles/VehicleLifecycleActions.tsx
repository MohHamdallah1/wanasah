import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { deactivateVehicle, reactivateVehicle } from "./api";
import type { Vehicle } from "./contracts";
import { vehicleErrorMessage } from "./vehicleErrorMessage";

interface VehicleLifecycleActionsProps {
  vehicle: Vehicle;
  allowed: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type LifecycleCommand = {
  vehicleId: number;
  plate: string;
  action: "deactivate" | "reactivate";
  requestId: string;
  expectedVersion: number;
};

export function VehicleLifecycleActions({
  vehicle,
  allowed,
  open,
  onOpenChange,
}: VehicleLifecycleActionsProps) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const formId = `vehicle-lifecycle-${vehicle.id}`;
  const command = useRef<LifecycleCommand>({
    vehicleId: vehicle.id,
    plate: vehicle.plate_number,
    action: vehicle.is_active ? "deactivate" : "reactivate",
    requestId: crypto.randomUUID(),
    expectedVersion: vehicle.version,
  });

  const close = () => {
    if (!busy) onOpenChange(false);
  };

  const run = async () => {
    if (!allowed || busy) return;
    const pending = command.current;
    setBusy(true);
    try {
      if (pending.action === "deactivate") {
        await deactivateVehicle(
          authFetch,
          pending.vehicleId,
          pending.requestId,
          pending.expectedVersion,
        );
      } else {
        await reactivateVehicle(
          authFetch,
          pending.vehicleId,
          pending.requestId,
          pending.expectedVersion,
        );
      }
      await queryClient.invalidateQueries({ queryKey: ["vehicles"] });
      toast.success(t(
        pending.action === "deactivate"
          ? "representativesVehicles.vehicles.lifecycle.successDeactivate"
          : "representativesVehicles.vehicles.lifecycle.successReactivate",
      ));
      onOpenChange(false);
    } catch (error) {
      toast.error(vehicleErrorMessage(
        error,
        t("representativesVehicles.vehicles.lifecycle.failed"),
      ));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={open}
      onClose={close}
      title={t("representativesVehicles.vehicles.lifecycle.title")}
      maxWidth="max-w-md"
      initialFocusRef={confirmButtonRef}
      footer={
        <>
          <button type="button" disabled={busy} onClick={close} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">
            {t("common.cancel")}
          </button>
          <button ref={confirmButtonRef} type="submit" form={formId} disabled={busy || !allowed} className="h-10 rounded-xl bg-slate-900 px-4 text-sm font-black text-white disabled:opacity-50">
            {busy ? t("common.saving") : t("common.confirm")}
          </button>
        </>
      }
    >
      <form id={formId} onSubmit={(event) => { event.preventDefault(); void run(); }}>
        <p className="text-sm font-semibold leading-7 text-slate-600">
          {t(
            command.current.action === "deactivate"
              ? "representativesVehicles.vehicles.lifecycle.deactivateConfirm"
              : "representativesVehicles.vehicles.lifecycle.reactivateConfirm",
            { plate: command.current.plate },
          )}
        </p>
      </form>
    </Modal>
  );
}
