import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { deactivateRepresentative, reactivateRepresentative } from "./api";
import type { Representative } from "./contracts";
import { representativeErrorMessage } from "./representativeErrorMessage";

interface RepresentativeLifecycleActionsProps {
  representative: Representative;
  allowed: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
}

type LifecycleCommand = {
  representativeId: number;
  fullName: string;
  action: "deactivate" | "reactivate";
  requestId: string;
};

export function RepresentativeLifecycleActions({
  representative,
  allowed,
  open,
  onOpenChange,
  onChanged,
}: RepresentativeLifecycleActionsProps) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const command = useRef<LifecycleCommand>({
    representativeId: representative.id,
    fullName: representative.full_name,
    action: representative.is_active ? "deactivate" : "reactivate",
    requestId: crypto.randomUUID(),
  });

  const close = () => {
    if (busy) return;
    onOpenChange(false);
  };

  const run = async () => {
    if (!allowed) return;
    const pending = command.current;
    setBusy(true);
    try {
      if (pending.action === "deactivate") {
        await deactivateRepresentative(authFetch, pending.representativeId, pending.requestId);
      } else {
        await reactivateRepresentative(authFetch, pending.representativeId, pending.requestId);
      }
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t(pending.action === "deactivate"
        ? "representativesVehicles.representatives.lifecycle.successDeactivate"
        : "representativesVehicles.representatives.lifecycle.successReactivate"));
      onOpenChange(false);
      onChanged?.();
    } catch (error) {
      toast.error(
        representativeErrorMessage(
          error,
          t("representativesVehicles.representatives.lifecycle.failed"),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={open}
      onClose={close}
      title={t("representativesVehicles.representatives.lifecycle.title")}
      maxWidth="max-w-md"
      footer={
        <>
          <button type="button" disabled={busy} onClick={close} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">{t("common.cancel")}</button>
          <button type="button" disabled={busy || !allowed} onClick={() => void run()} className="h-10 rounded-xl bg-slate-900 px-4 text-sm font-black text-white disabled:opacity-50">{busy ? t("common.saving") : t("common.confirm")}</button>
        </>
      }
    >
      <p className="text-sm font-semibold leading-7 text-slate-600">
        {t(command.current.action === "deactivate"
          ? "representativesVehicles.representatives.lifecycle.deactivateConfirm"
          : "representativesVehicles.representatives.lifecycle.reactivateConfirm", { name: command.current.fullName })}
      </p>
    </Modal>
  );
}
