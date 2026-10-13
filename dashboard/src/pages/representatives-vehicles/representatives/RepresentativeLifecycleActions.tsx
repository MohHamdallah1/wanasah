import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Power, PowerOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { deactivateRepresentative, reactivateRepresentative } from "./api";
import type { Representative } from "./contracts";

interface RepresentativeLifecycleActionsProps {
  representative: Representative;
  onChanged?: () => void;
}

export function RepresentativeLifecycleActions({ representative, onChanged }: RepresentativeLifecycleActionsProps) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      if (representative.is_active) {
        await deactivateRepresentative(authFetch, representative.id);
      } else {
        await reactivateRepresentative(authFetch, representative.id);
      }
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t(representative.is_active
        ? "representativesVehicles.representatives.lifecycle.successDeactivate"
        : "representativesVehicles.representatives.lifecycle.successReactivate"));
      setConfirmOpen(false);
      onChanged?.();
    } catch (error) {
      toast.error(apiErrorMessage(error, t("representativesVehicles.representatives.lifecycle.failed")));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
      <h3 className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.lifecycle.title")}</h3>
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        className={`mt-2 inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${representative.is_active ? "border-rose-200 bg-white text-rose-700 hover:bg-rose-50" : "border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50"}`}
      >
        {representative.is_active ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
        {t(representative.is_active
          ? "representativesVehicles.representatives.lifecycle.deactivate"
          : "representativesVehicles.representatives.lifecycle.reactivate")}
      </button>

      <Modal
        isOpen={confirmOpen}
        onClose={() => !busy && setConfirmOpen(false)}
        title={t("representativesVehicles.representatives.lifecycle.title")}
        maxWidth="max-w-md"
        footer={
          <>
            <button type="button" disabled={busy} onClick={() => setConfirmOpen(false)} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">{t("common.cancel")}</button>
            <button type="button" disabled={busy} onClick={() => void run()} className="h-10 rounded-xl bg-slate-900 px-4 text-sm font-black text-white disabled:opacity-50">{busy ? t("common.saving") : t("common.confirm")}</button>
          </>
        }
      >
        <p className="text-sm font-semibold leading-7 text-slate-600">
          {t(representative.is_active
            ? "representativesVehicles.representatives.lifecycle.deactivateConfirm"
            : "representativesVehicles.representatives.lifecycle.reactivateConfirm", { name: representative.full_name })}
        </p>
      </Modal>
    </section>
  );
}
