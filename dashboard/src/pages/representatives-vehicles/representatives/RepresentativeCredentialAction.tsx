import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorCode } from "@/lib/apiErrors";
import { resetRepresentativeCredentials } from "./api";
import {
  clearCredentialResetRecovery,
  CredentialResetRecoveryUnavailable,
  hasCredentialResetRecovery,
  prepareCredentialReset,
  resetValidationProvesNoExecution,
  startNewCredentialReset,
  type CredentialResetAttempt,
} from "./credentialResetRecovery";
import type { Representative } from "./contracts";
import { representativePasswordValidation } from "./passwordPolicy";
import { RepresentativePasswordInput } from "./RepresentativePasswordInput";
import { representativeErrorMessage } from "./representativeErrorMessage";

interface RepresentativeCredentialActionProps {
  representative: Representative;
  allowed: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RepresentativeCredentialAction({
  representative,
  allowed,
  open,
  onOpenChange,
}: RepresentativeCredentialActionProps) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [validation, setValidation] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [recoveryConflict, setRecoveryConflict] = useState(false);

  useEffect(() => {
    if (!open || !allowed) return;
    try {
      setRecovering(hasCredentialResetRecovery(representative.id));
    } catch {
      setValidation(t("representativesVehicles.representatives.credentials.recoveryUnavailable"));
    }
  }, [allowed, open, representative.id, t]);

  const resetFields = () => {
    setRecovering(false);
    setRecoveryConflict(false);
    setPassword("");
    setConfirmPassword("");
    setValidation("");
  };

  const close = () => {
    if (busy) return;
    resetFields();
    onOpenChange(false);
  };

  const startNew = () => {
    try {
      startNewCredentialReset(representative.id);
      setRecovering(false);
      setRecoveryConflict(false);
      setValidation("");
    } catch {
      setValidation(t("representativesVehicles.representatives.credentials.recoveryUnavailable"));
    }
  };

  const run = async () => {
    if (!allowed) return;
    const passwordIssue = representativePasswordValidation(password);
    if (passwordIssue) {
      setValidation(t(
        passwordIssue === "tooShort"
          ? "representativesVehicles.representatives.form.passwordTooShort"
          : "representativesVehicles.representatives.form.passwordTooLong",
      ));
      return;
    }
    if (password !== confirmPassword) {
      setValidation(t("representativesVehicles.representatives.credentials.mismatch"));
      return;
    }

    setValidation("");
    setBusy(true);
    let attempt: CredentialResetAttempt | undefined;
    try {
      attempt = prepareCredentialReset(representative.id);
      await resetRepresentativeCredentials(
        authFetch,
        representative.id,
        password,
        attempt.requestId,
      );
      clearCredentialResetRecovery(attempt);
      toast.success(t("representativesVehicles.representatives.credentials.success"));
      resetFields();
      onOpenChange(false);
    } catch (error) {
      let failure = error;
      let pending = Boolean(attempt);
      if (attempt && !attempt.recovered && resetValidationProvesNoExecution(error)) {
        try {
          clearCredentialResetRecovery(attempt);
          pending = false;
        } catch (storageError) {
          failure = storageError;
        }
      }
      setRecovering(pending);
      const conflict = apiErrorCode(error) === "REPRESENTATIVE_IDEMPOTENCY_CONFLICT";
      setRecoveryConflict(conflict);
      toast.error(
        failure instanceof CredentialResetRecoveryUnavailable
          ? t("representativesVehicles.representatives.credentials.recoveryUnavailable")
          : conflict
            ? t("representativesVehicles.representatives.credentials.recoveryConflict")
            : representativeErrorMessage(
                failure,
                t("representativesVehicles.representatives.credentials.failed"),
              ),
      );
    } finally {
      setBusy(false);
    }
  };

  const inputClass = "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60";

  return (
    <Modal
      isOpen={open}
      onClose={close}
      title={t("representativesVehicles.representatives.credentials.title")}
      maxWidth="max-w-md"
      footer={
        <>
          <button type="button" disabled={busy} onClick={close} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 disabled:opacity-50">{t("common.cancel")}</button>
          <button type="button" disabled={busy || !allowed} onClick={() => void run()} className="h-10 rounded-xl bg-slate-900 px-4 text-sm font-black text-white disabled:opacity-50">{busy ? t("common.saving") : t("common.confirm")}</button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm font-semibold leading-6 text-slate-600">{representative.full_name}</p>
        <p className="text-[11px] font-semibold leading-5 text-slate-500">{t("representativesVehicles.representatives.credentials.hint")}</p>
        <div className="space-y-1.5">
          <label htmlFor="representative-new-password" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.newPassword")}</label>
          <RepresentativePasswordInput
            id="representative-new-password"
            autoFocus
            value={password}
            onChange={(value) => { setValidation(""); setPassword(value); }}
            className={inputClass}
            resetSignal={open}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="representative-confirm-password" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.confirmPassword")}</label>
          <RepresentativePasswordInput
            id="representative-confirm-password"
            value={confirmPassword}
            onChange={(value) => { setValidation(""); setConfirmPassword(value); }}
            className={inputClass}
            resetSignal={open}
          />
        </div>
        {recovering && !recoveryConflict ? <p className="text-xs font-semibold text-slate-600">{t("representativesVehicles.representatives.credentials.recoveryPending")}</p> : null}
        {recoveryConflict ? (
          <div role="alert" className="space-y-2">
            <p className="text-xs font-semibold text-rose-700">{t("representativesVehicles.representatives.credentials.recoveryConflict")}</p>
            <button type="button" disabled={busy} onClick={startNew} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">{t("representativesVehicles.representatives.credentials.startNew")}</button>
          </div>
        ) : null}
        {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}
      </div>
    </Modal>
  );
}
