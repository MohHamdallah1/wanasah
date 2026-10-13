import { useState } from "react";
import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resetRepresentativeCredentials } from "./api";
import type { Representative } from "./contracts";

export function RepresentativeCredentialAction({ representative }: { representative: Representative }) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [validation, setValidation] = useState("");

  const resetFields = () => {
    setPassword("");
    setConfirmPassword("");
    setValidation("");
  };

  const close = () => {
    if (busy) return;
    setOpen(false);
    resetFields();
  };

  const run = async () => {
    if (password.length < 8 || password.length > 72) {
      setValidation(t("representativesVehicles.representatives.form.passwordInvalid"));
      return;
    }
    if (password !== confirmPassword) {
      setValidation(t("representativesVehicles.representatives.credentials.mismatch"));
      return;
    }

    setValidation("");
    setBusy(true);
    try {
      await resetRepresentativeCredentials(authFetch, representative.id, password);
      toast.success(t("representativesVehicles.representatives.credentials.success"));
      setOpen(false);
      resetFields();
    } catch (error) {
      toast.error(apiErrorMessage(error, t("representativesVehicles.representatives.credentials.failed")));
    } finally {
      setBusy(false);
    }
  };

  const inputClass = "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60";

  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
      <h3 className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.credentials.title")}</h3>
      <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">{t("representativesVehicles.representatives.credentials.hint")}</p>
      <button type="button" onClick={() => setOpen(true)} className="mt-2 inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
        <KeyRound className="h-4 w-4" />
        {t("representativesVehicles.representatives.credentials.reset")}
      </button>
      <Modal
        isOpen={open}
        onClose={close}
        title={t("representativesVehicles.representatives.credentials.title")}
        maxWidth="max-w-md"
        footer={
          <>
            <button type="button" disabled={busy} onClick={close} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">{t("common.cancel")}</button>
            <button type="button" disabled={busy} onClick={() => void run()} className="h-10 rounded-xl bg-slate-900 px-4 text-sm font-black text-white disabled:opacity-50">{busy ? t("common.saving") : t("common.confirm")}</button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-sm font-semibold leading-6 text-slate-600">{representative.full_name}</p>
          <div className="space-y-1.5">
            <label htmlFor="representative-new-password" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.newPassword")}</label>
            <input id="representative-new-password" autoFocus type="password" minLength={8} maxLength={72} value={password} onChange={(event) => setPassword(event.target.value)} className={inputClass} autoComplete="new-password" />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="representative-confirm-password" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.confirmPassword")}</label>
            <input id="representative-confirm-password" type="password" minLength={8} maxLength={72} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className={inputClass} autoComplete="new-password" />
          </div>
          {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}
        </div>
      </Modal>
    </section>
  );
}
