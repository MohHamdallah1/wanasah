import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  normalizeOptionalPhone,
  normalizeRepresentativeFormValue,
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
  const [name, setName] = useState(representative?.name ?? "");
  const [username, setUsername] = useState(representative?.username ?? "");
  const [phone, setPhone] = useState(representative?.phone ?? "");
  const [validation, setValidation] = useState("");

  useEffect(() => {
    setName(representative?.name ?? "");
    setUsername(representative?.username ?? "");
    setPhone(representative?.phone ?? "");
    setValidation("");
  }, [representative]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = normalizeRepresentativeFormValue(name);
    const normalizedUsername = normalizeRepresentativeFormValue(username);
    if (!normalizedName || (!representative && !normalizedUsername)) {
      setValidation(t("representativesVehicles.representatives.form.required"));
      return;
    }

    setValidation("");
    if (representative) {
      await onSubmit({ name: normalizedName, phone: normalizeOptionalPhone(phone) });
    } else {
      await onSubmit({
        username: normalizedUsername,
        name: normalizedName,
        phone: normalizeOptionalPhone(phone),
      });
    }
  };

  const inputClass = "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60 disabled:bg-slate-50 disabled:text-slate-500";

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-1.5">
        <label htmlFor="representative-name" className="text-xs font-black text-slate-700">
          {t("representativesVehicles.representatives.fields.name")}
        </label>
        <input
          id="representative-name"
          autoFocus
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("representativesVehicles.representatives.form.namePlaceholder")}
          className={inputClass}
          disabled={busy}
          autoComplete="off"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="representative-username" className="text-xs font-black text-slate-700">
          {t("representativesVehicles.representatives.fields.username")}
        </label>
        <input
          id="representative-username"
          dir="ltr"
          maxLength={120}
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder={t("representativesVehicles.representatives.form.usernamePlaceholder")}
          className={inputClass}
          disabled={busy || Boolean(representative)}
          autoComplete="off"
        />
        {representative ? (
          <p className="text-[11px] font-semibold leading-5 text-slate-500">
            {t("representativesVehicles.representatives.form.usernameCreateOnly")}
          </p>
        ) : null}
      </div>

      <div className="space-y-1.5">
        <label htmlFor="representative-phone" className="text-xs font-black text-slate-700">
          {t("representativesVehicles.representatives.fields.phone")}
        </label>
        <input
          id="representative-phone"
          dir="ltr"
          inputMode="tel"
          maxLength={40}
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          placeholder={t("representativesVehicles.representatives.form.phonePlaceholder")}
          className={inputClass}
          disabled={busy}
          autoComplete="tel"
        />
      </div>

      {validation ? <p role="alert" className="text-xs font-bold text-rose-700">{validation}</p> : null}

      <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} disabled={busy}
          className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-sm font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
          {t("common.cancel")}
        </button>
        <button type="submit" disabled={busy}
          className="h-10 rounded-xl bg-slate-900 px-5 text-sm font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-50">
          {busy ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
