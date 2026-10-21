import { useTranslation } from "react-i18next";
import type { ProductDraft } from "./types";
import type { PurchaseReferenceCreateInput, PurchaseReferenceCreateOptions } from "./purchaseReferenceCreateContract";
import "./purchaseReferenceCreateI18n";

type Props = {
  draft: ProductDraft;
  options?: PurchaseReferenceCreateOptions;
  failed?: boolean;
  saving: boolean;
  onRetry: () => void;
  onChange: (value: PurchaseReferenceCreateInput | undefined) => void;
};

export function CreateProductPurchaseReferenceSection({ draft, options, failed, saving, onRetry, onChange }: Props) {
  const { t, i18n } = useTranslation("productCreatePurchaseReference");
  const value = draft.purchase_cost_reference;
  if (!options?.can_manage && !value && !failed) return null;
  const eligible = options?.uoms.filter((uom) => uom.code === "EACH"
    || (draft.has_package && uom.code === draft.package_uom_code)) ?? [];
  const unavailableUom = Boolean(value && !eligible.some((uom) => uom.id === value.purchase_uom_id));
  const canEnter = options?.can_manage === true && !saving;
  return (
    <section dir={i18n.dir()} className="border-b border-slate-200 px-4 py-4 sm:px-6">
      {failed ? <div role="alert">
        <p>{t("unavailable")}</p>
        <button type="button" disabled={saving} onClick={onRetry}>{t("retry")}</button>
      </div> : null}
      {options?.can_manage || value ? <>
        <label className="flex items-center gap-2 text-sm font-bold">
          <input type="checkbox" checked={Boolean(value)} disabled={saving || (!options?.can_manage && !value)}
            onChange={(event) => {
              if (!event.target.checked) { onChange(undefined); return; }
              const base = eligible.find((uom) => uom.code === "EACH");
              if (base && options?.currency_code) onChange({
                amount: "", purchase_uom_id: base.id, currency_code: options.currency_code,
              });
            }} />
          {t("enable")}
        </label>
        <p className="mt-2 text-xs text-slate-600">{t("hint")}</p>
        {value ? <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-bold">{t("amount")}
            <input inputMode="decimal" value={value.amount} disabled={!canEnter}
              onChange={(event) => onChange({ ...value, amount: event.target.value })}
              className="mt-1 block w-full rounded-xl border p-2" />
          </label>
          <label className="text-xs font-bold">{t("uom")}
            <select value={String(value.purchase_uom_id)} disabled={!canEnter}
              onChange={(event) => onChange({ ...value, purchase_uom_id: Number(event.target.value) })}
              className="mt-1 block w-full rounded-xl border p-2">
              {unavailableUom ? <option value={String(value.purchase_uom_id)} disabled>{t("chooseUom")}</option> : null}
              {eligible.map((uom) => <option key={uom.id} value={uom.id}>
                {t(`uom.${uom.code}`, { ns: "translation" })}
              </option>)}
            </select>
          </label>
          <p className="text-xs font-bold">{t("currency", { currency: value.currency_code })}</p>
          {unavailableUom ? <p role="alert">{t("changedUom")}</p> : null}
          {options?.can_manage === false ? <p role="alert">{t("denied")}</p> : null}
          {options?.currency_code && options.currency_code !== value.currency_code
            ? <p role="alert">{t("changedCurrency")}</p> : null}
        </div> : null}
      </> : null}
    </section>
  );
}
