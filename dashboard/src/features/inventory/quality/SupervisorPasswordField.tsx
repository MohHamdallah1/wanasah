import { useState } from "react";
import { useTranslation } from "react-i18next";

export function SupervisorPasswordField({ value, onChange, disabled }: {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [editable, setEditable] = useState(false);

  return (
    <label className="block text-xs font-black text-slate-800">
      {t("productQualityInline.fields.supervisorPassword")}
      <input
        type="password"
        name="quality-confirmation-secret"
        autoComplete="off"
        readOnly={!editable}
        data-lpignore="true"
        data-1p-ignore="true"
        data-form-type="other"
        maxLength={256}
        value={value}
        disabled={disabled}
        onFocus={() => setEditable(true)}
        onChange={(event) => onChange(event.target.value)}
        placeholder={t("productQualityInline.fields.supervisorPasswordPlaceholder")}
        className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-40"
      />
    </label>
  );
}
