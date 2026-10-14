import { type FocusEvent, type FormEvent, type MouseEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  normalizeDebtLimit,
  normalizeRequiredPhone,
  normalizeRepresentativeText,
  type CreateRepresentativeInput,
  type Representative,
  type UpdateRepresentativeInput,
} from "./contracts";
import { isRepresentativePasswordValid } from "./passwordPolicy";
import { formatRepresentativeMoney } from "./representativeMoney";
import { RepresentativePasswordInput } from "./RepresentativePasswordInput";
import { isRepresentativeUsernameValid } from "./usernamePolicy";

interface RepresentativeFormProps {
  representative?: Representative | null;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (
    input: CreateRepresentativeInput | UpdateRepresentativeInput,
    requestId: string,
  ) => Promise<void> | void;
}

type PendingFormOperation = {
  fingerprint: string;
  requestId: string;
};

const editableDebtLimit = (representative?: Representative | null) =>
  representative
    ? formatRepresentativeMoney(representative.max_debt_limit, { groupThousands: false })
    : "";

const usernameDirection = (value: string, fallback: "rtl" | "ltr") => {
  if (!value) return fallback;
  return /[A-Za-z]/.test(value) ? "ltr" : "rtl";
};

export function RepresentativeForm({
  representative = null,
  busy = false,
  onCancel,
  onSubmit,
}: RepresentativeFormProps) {
  const { t, i18n } = useTranslation();
  const [fullName, setFullName] = useState(representative?.full_name ?? "");
  const [username, setUsername] = useState(representative?.username ?? "");
  const [phone, setPhone] = useState(representative?.phone_number ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [canAllowDebt, setCanAllowDebt] = useState(representative?.can_allow_debt ?? false);
  const [maxDebtLimit, setMaxDebtLimit] = useState(editableDebtLimit(representative));
  const [validation, setValidation] = useState("");
  const operation = useRef<PendingFormOperation | null>(null);
  const debtSelectionHandled = useRef(false);
  const debtMouseUpSelectionPending = useRef(false);
  const formDirection = i18n.dir();
  const localeTextAlignment = formDirection === "rtl" ? "text-right" : "text-left";

  useEffect(() => {
    setFullName(representative?.full_name ?? "");
    setUsername(representative?.username ?? "");
    setPhone(representative?.phone_number ?? "");
    setPassword("");
    setConfirmPassword("");
    setCanAllowDebt(representative?.can_allow_debt ?? false);
    setMaxDebtLimit(editableDebtLimit(representative));
    setValidation("");
    operation.current = null;
    debtSelectionHandled.current = false;
    debtMouseUpSelectionPending.current = false;
  }, [representative]);

  const resetOperation = () => {
    if (validation) setValidation("");
  };

  const requestIdForSubmission = (
    input: CreateRepresentativeInput | UpdateRepresentativeInput,
  ) => {
    const fingerprint = JSON.stringify({
      full_name: input.full_name,
      username: input.username,
      phone_number: input.phone_number,
      can_allow_debt: input.can_allow_debt,
      max_debt_limit: input.max_debt_limit,
    });
    if (!operation.current || operation.current.fingerprint !== fingerprint) {
      operation.current = { fingerprint, requestId: crypto.randomUUID() };
    }
    return operation.current.requestId;
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = normalizeRepresentativeText(fullName);
    const normalizedUsername = normalizeRepresentativeText(username);
    const normalizedPhone = normalizeRequiredPhone(phone);
    const debtInput = maxDebtLimit.trim();
    const normalizedDebt = debtInput ? normalizeDebtLimit(debtInput) : null;

    if (!normalizedName || normalizedName.length > 120) {
      setValidation(t("representativesVehicles.representatives.form.required"));
      return;
    }
    if (!normalizedUsername) {
      setValidation(t("representativesVehicles.representatives.form.required"));
      return;
    }
    if (!isRepresentativeUsernameValid(normalizedUsername)) {
      setValidation(t("representativesVehicles.representatives.form.usernameInvalid"));
      return;
    }
    if (!normalizedPhone) {
      setValidation(t("representativesVehicles.representatives.form.phoneRequired"));
      return;
    }
    if (normalizedPhone.length > 20) {
      setValidation(t("representativesVehicles.representatives.form.phoneInvalid"));
      return;
    }
    if (canAllowDebt && !debtInput) {
      setValidation(t("representativesVehicles.representatives.form.debtRequired"));
      return;
    }
    if (canAllowDebt && !normalizedDebt) {
      setValidation(t("representativesVehicles.representatives.form.debtInvalid"));
      return;
    }
    if (!representative) {
      if (!isRepresentativePasswordValid(password)) {
        setValidation(t("representativesVehicles.representatives.form.passwordInvalid"));
        return;
      }
      if (!confirmPassword) {
        setValidation(t("representativesVehicles.representatives.form.confirmRequired"));
        return;
      }
      if (password !== confirmPassword) {
        setValidation(t("representativesVehicles.representatives.form.passwordMismatch"));
        return;
      }
    }

    setValidation("");

    if (representative) {
      const update: UpdateRepresentativeInput = {};
      const originalName = normalizeRepresentativeText(representative.full_name);
      const originalUsername = normalizeRepresentativeText(representative.username);
      const originalPhone = normalizeRequiredPhone(representative.phone_number ?? "");
      const originalDebt =
        normalizeDebtLimit(representative.max_debt_limit) ?? representative.max_debt_limit;

      if (normalizedName !== originalName) update.full_name = normalizedName;
      if (normalizedUsername !== originalUsername) update.username = normalizedUsername;
      if (normalizedPhone !== originalPhone) update.phone_number = normalizedPhone;
      if (canAllowDebt !== representative.can_allow_debt) {
        update.can_allow_debt = canAllowDebt;
      }
      if (canAllowDebt && normalizedDebt && normalizedDebt !== originalDebt) {
        update.max_debt_limit = normalizedDebt;
      }

      if (Object.keys(update).length === 0) {
        setValidation(t("representativesVehicles.representatives.form.noChanges"));
        return;
      }

      await onSubmit(update, requestIdForSubmission(update));
      return;
    }

    const createInput: CreateRepresentativeInput = {
      full_name: normalizedName,
      username: normalizedUsername,
      phone_number: normalizedPhone,
      password,
      can_allow_debt: canAllowDebt,
      max_debt_limit: canAllowDebt ? normalizedDebt! : "0.000",
    };
    await onSubmit(createInput, requestIdForSubmission(createInput));
  };

  const selectExistingDebtOnFirstFocus = (event: FocusEvent<HTMLInputElement>) => {
    if (!representative || debtSelectionHandled.current || !event.currentTarget.value) return;
    event.currentTarget.select();
    debtSelectionHandled.current = true;
    debtMouseUpSelectionPending.current = true;
  };

  const preserveFirstDebtSelection = (event: MouseEvent<HTMLInputElement>) => {
    if (!debtMouseUpSelectionPending.current) return;
    event.preventDefault();
    debtMouseUpSelectionPending.current = false;
  };

  const inputClass = "h-10 min-w-0 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:bg-slate-50 disabled:text-slate-500";

  return (
    <form dir={formDirection} className="space-y-4" onSubmit={submit}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="min-w-0 space-y-1.5 sm:col-span-2">
          <label htmlFor="representative-name" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.name")}</label>
          <input id="representative-name" autoFocus required aria-required="true" maxLength={120} value={fullName} onChange={(event) => { resetOperation(); setFullName(event.target.value); }} placeholder={t("representativesVehicles.representatives.form.namePlaceholder")} className={inputClass} disabled={busy} autoComplete="off" />
        </div>

        <div className="min-w-0 space-y-1.5">
          <label htmlFor="representative-username" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.username")}</label>
          <input id="representative-username" aria-describedby="representative-username-hint" required aria-required="true" dir={usernameDirection(username, formDirection)} maxLength={80} value={username} onChange={(event) => { resetOperation(); setUsername(event.target.value); }} placeholder={t("representativesVehicles.representatives.form.usernamePlaceholder")} className={`${inputClass} ${localeTextAlignment}`} disabled={busy} autoComplete="off" />
          <p id="representative-username-hint" className="text-[11px] font-semibold leading-5 text-slate-500">{t("representativesVehicles.representatives.form.usernameHint")}</p>
        </div>

        <div className="min-w-0 space-y-1.5">
          <label htmlFor="representative-phone" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.phone")}</label>
          <input id="representative-phone" required aria-required="true" dir={phone ? "ltr" : formDirection} inputMode="tel" maxLength={20} value={phone} onChange={(event) => { resetOperation(); setPhone(event.target.value); }} placeholder={t("representativesVehicles.representatives.form.phonePlaceholder")} className={`${inputClass} ${localeTextAlignment}`} disabled={busy} autoComplete="tel" />
        </div>

        {!representative ? (
          <>
            <div className="min-w-0 space-y-1.5 sm:col-span-2">
              <label htmlFor="representative-password" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.password")}</label>
              <RepresentativePasswordInput
                id="representative-password"
                value={password}
                onChange={(value) => { operation.current = null; resetOperation(); setPassword(value); }}
                placeholder={t("representativesVehicles.representatives.form.passwordPlaceholder")}
                className={inputClass}
                disabled={busy}
                resetSignal="create"
              />
            </div>
            <div className="min-w-0 space-y-1.5 sm:col-span-2">
              <label htmlFor="representative-confirm-password" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.confirmPassword")}</label>
              <RepresentativePasswordInput
                id="representative-confirm-password"
                value={confirmPassword}
                onChange={(value) => { resetOperation(); setConfirmPassword(value); }}
                placeholder={t("representativesVehicles.representatives.form.confirmPasswordPlaceholder")}
                className={inputClass}
                disabled={busy}
                resetSignal="create"
              />
            </div>
          </>
        ) : null}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3">
        <label className="flex cursor-pointer items-center justify-between gap-3 text-sm font-black text-slate-700">
          <span>{t("representativesVehicles.representatives.fields.debtPermission")}</span>
          <input
            type="checkbox"
            checked={canAllowDebt}
            onChange={(event) => {
              resetOperation();
              setCanAllowDebt(event.target.checked);
            }}
            disabled={busy}
            className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-cyan-400"
          />
        </label>
        {canAllowDebt ? (
          <div className="mt-3 space-y-1.5">
            <label htmlFor="representative-debt-limit" className="block text-start text-xs font-black text-slate-700">{t("representativesVehicles.representatives.fields.debtLimit")}</label>
            <input
              id="representative-debt-limit"
              aria-describedby="representative-debt-hint"
              required
              aria-required="true"
              dir={maxDebtLimit ? "ltr" : formDirection}
              inputMode="decimal"
              value={maxDebtLimit}
              onFocus={selectExistingDebtOnFirstFocus}
              onMouseUp={preserveFirstDebtSelection}
              onChange={(event) => {
                debtMouseUpSelectionPending.current = false;
                resetOperation();
                setMaxDebtLimit(event.target.value);
              }}
              placeholder={t("representativesVehicles.representatives.form.debtLimitPlaceholder")}
              className={`${inputClass} ${localeTextAlignment} font-mono tabular-nums`}
              disabled={busy}
              autoComplete="off"
            />
            <span id="representative-debt-hint" className="sr-only">{t("representativesVehicles.representatives.form.debtA11yHint")}</span>
          </div>
        ) : (
          <p className="mt-3 rounded-xl bg-white px-3 py-2 text-xs font-black text-slate-500 ring-1 ring-slate-200">
            {t("representativesVehicles.representatives.form.debtDisabled")}
          </p>
        )}
      </div>

      {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}

      <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} disabled={busy} className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">{t("common.cancel")}</button>
        <button type="submit" disabled={busy} className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">{busy ? t("common.saving") : t("common.save")}</button>
      </div>
    </form>
  );
}
