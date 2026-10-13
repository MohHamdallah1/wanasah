import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Power, PowerOff } from "lucide-react";
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
  onChanged?: () => void;
}

export function RepresentativeLifecycleActions({
  representative,
  allowed,
  onChanged,
}: RepresentativeLifecycleActionsProps) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const requestId = useRef<string | null>(null);

  const openConfirm = () => {
    if (!allowed) return;
    requestId.current = crypto.randomUUID();
    setConfirmOpen(true);
  };

  const closeConfirm = () => {
    if (busy) return;
    requestId.current = null;
    setConfirmOpen(false);
  };

  const run = async () => {
    const operationId = requestId.current ?? crypto.randomUUID();
    requestId.current = operationId;
    setBusy(true);
    try {
      if (representative.is_active) {
        await deactivateRepresentative(authFetch, representative.id, operationId);
      } else {
        await reactivateRepresentative(authFetch, representative.id, operationId);
      }
      requestId.current = null;
      await queryClient.invalidateQueries({ queryKey: ["representatives"] });
      toast.success(t(representative.is_active
        ? "representativesVehicles.representatives.lifecycle.successDeactivate"
        : "representativesVehicles.representatives.lifecycle.successReactivate"));
      setConfirmOpen(false);
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
    <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
      <h3 className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.lifecycle.title")}</h3>
      <button
        type="button"
        disabled={!allowed}
        onClick={openConfirm}
        aria-describedby={!allowed ? "representative-lifecycle-blocked" : undefined}
        className={`mt-2 inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:cursor-not-allowed disabled:opacity-50 ${representative.is_active ? "border-rose-200 bg-white text-rose-700 hover:bg-rose-50" : "border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50"}`}
      >
        {representative.is_active ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
        {t(representative.is_active
          ? "representativesVehicles.representatives.lifecycle.deactivate"
          : "representativesVehicles.representatives.lifecycle.reactivate")}
      </button>
      {!allowed ? (
        <p id="representative-lifecycle-blocked" className="mt-2 text-[11px] font-semibold leading-5 text-slate-500">
          {t("representativesVehicles.representatives.permissions.manageRequired")}
        </p>
      ) : null}

      <Modal
        isOpen={confirmOpen}
        onClose={closeConfirm}
        title={t("representativesVehicles.representatives.lifecycle.title")}
        maxWidth="max-w-md"
        footer={
          <>
            <button type="button" disabled={busy} onClick={closeConfirm} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">{t("common.cancel")}</button>
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
