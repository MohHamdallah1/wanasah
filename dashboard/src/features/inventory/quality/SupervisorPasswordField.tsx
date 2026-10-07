import { useTranslation } from "react-i18next";

export function SupervisorPasswordField({ value, onChange, disabled }: {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  return <label className="mt-3 block rounded-lg border border-slate-200 bg-white p-3 text-[10px] font-black text-slate-700">
    {t("productQualityInline.fields.supervisorPassword")}
    <input type="password" autoComplete="current-password" maxLength={256}
      value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}
      placeholder={t("productQualityInline.fields.supervisorPasswordPlaceholder")}
      className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
    <span className="mt-1 block text-[9px] font-semibold leading-4 text-slate-500">
      {t("productQualityInline.fields.supervisorPasswordHint")}
    </span>
  </label>;
}
