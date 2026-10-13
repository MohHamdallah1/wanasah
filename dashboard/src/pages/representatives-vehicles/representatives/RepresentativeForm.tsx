import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  normalizeDebtLimit,
  normalizeOptionalPhone,
  normalizeRepresentativeText,
  type CreateRepresentativeInput,
  type Representative,
  type UpdateRepresentativeInput,
} from "./contracts";

interface RepresentativeFormProps {
  representative?: Representative | null;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (input: CreateRepresentativeInput | UpdateRepresentativeInput) => Promise<void> | void;
}

export function RepresentativeForm({
  representative = null,
  busy = false,
  onCancel,
  onSubmit,
}: RepresentativeFormProps) {
  const { t } = useTranslation();
  const [fullName, setFullName] = useState(representative?.full_name ?? "");
  const [username, setUsername] = useState(representative?.username ?? "");
  const [phone, setPhone] = useState(representative?.phone_number ?? "");
  const [password, setPassword] = useState("");
  const [canAllowDebt, setCanAllowDebt] = useState(representative?.can_allow_debt ?? false);
  const [maxDebtLimit, setMaxDebtLimit] = useState(representative?.max_debt_limit ?? "0.000");
  const [validation, setValidation] = useState("");

  useEffect(() => {
    setFullName(representative?.full_name ?? "");
    setUsername(representative?.username ?? "");
    setPhone(representative?.phone_number ?? "");
    setPassword("");
    setCanAllowDebt(representative?.can_allow_debt ?? false);
    setMaxDebtLimit(representative?.max_debt_limit ?? "0.000");
    setValidation("");
  }, [representative]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = normalizeRepresentativeText(fullName);
    const normalizedUsername = normalizeRepresentativeText(username);
    const normalizedPhone = normalizeOptionalPhone(phone);
    const normalizedDebt = normalizeDebtLimit(canAllowDebt ? maxDebtLimit : "0.000");

    if (!normalizedName || !normalizedUsername) {
      setValidation(t("representativesVehicles.representatives.form.required"));
      return;
    }
    if (normalizedName.length > 120 || normalizedUsername.length > 80) {
      setValidation(t("representativesVehicles.representatives.form.required"));
      return;
    }
    if (normalizedPhone && normalizedPhone.length > 20) {
      setValidation(t("representativesVehicles.representatives.form.phoneInvalid"));
      return;
    }
    if (!normalizedDebt) {
      setValidation(t("representativesVehicles.representatives.form.debtInvalid"));
      return;
    }
    if (!representative && (password.length < 8 || password.length > 72)) {
      setValidation(t("representativesVehicles.representatives.form.passwordInvalid"));
      return;
    }

    setValidation("");
    const shared = {
      full_name: normalizedName,
      username: normalizedUsername,
      phone_number: normalizedPhone,
      can_allow_debt: canAllowDebt,
      max_debt_limit: normalizedDebt,
    };

    if (representative) {
      await onSubmit(shared);
    } else {
      await onSubmit({ ...shared, password });
    }
  };

  const inputClass = "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:bg-slate-50 disabled:text-slate-500";

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <label htmlFor="representative-name" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.name")}</label>
          <input id="representative-name" autoFocus maxLength={120} value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder={t("representativesVehicles.representatives.form.namePlaceholder")} className={inputClass} disabled={busy} autoComplete="off" />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="representative-username" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.username")}</label>
          <input id="representative-username" dir="ltr" maxLength={80} value={username} onChange={(event) => setUsername(event.target.value)} placeholder={t("representativesVehicles.representatives.form.usernamePlaceholder")} className={inputClass} disabled={busy} autoComplete="off" />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="representative-phone" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.phone")}</label>
          <input id="representative-phone" dir="ltr" inputMode="tel" maxLength={20} value={phone} onChange={(event) => setPhone(event.target.value)} placeholder={t("representativesVehicles.representatives.form.phonePlaceholder")} className={inputClass} disabled={busy} autoComplete="tel" />
        </div>

        {!representative ? (
          <div className="space-y-1.5 sm:col-span-2">
            <label htmlFor="representative-password" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.password")}</label>
            <input id="representative-password" type="password" minLength={8} maxLength={72} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={t("representativesVehicles.representatives.form.passwordPlaceholder")} className={inputClass} disabled={busy} autoComplete="new-password" />
          </div>
        ) : null}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
        <label className="flex cursor-pointer items-center justify-between gap-3 text-sm font-black text-slate-700">
          <span>{t("representativesVehicles.representatives.fields.debtPermission")}</span>
          <input
            type="checkbox"
            checked={canAllowDebt}
            onChange={(event) => {
              setCanAllowDebt(event.target.checked);
              if (!event.target.checked) setMaxDebtLimit("0.000");
            }}
            disabled={busy}
            className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-cyan-400"
          />
        </label>
        <div className="mt-3 space-y-1.5">
          <label htmlFor="representative-debt-limit" className="text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.debtLimit")}</label>
          <input id="representative-debt-limit" dir="ltr" inputMode="decimal" value={maxDebtLimit} onChange={(event) => setMaxDebtLimit(event.target.value)} placeholder={t("representativesVehicles.representatives.form.debtLimitPlaceholder")} className={inputClass} disabled={busy || !canAllowDebt} autoComplete="off" />
          <p className="text-[11px] font-semibold leading-5 text-slate-500">{t("representativesVehicles.representatives.form.debtHint")}</p>
        </div>
      </div>

      {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}

      <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} disabled={busy} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">{t("common.cancel")}</button>
        <button type="submit" disabled={busy} className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">{busy ? t("common.saving") : t("common.save")}</button>
      </div>
    </form>
  );
}
