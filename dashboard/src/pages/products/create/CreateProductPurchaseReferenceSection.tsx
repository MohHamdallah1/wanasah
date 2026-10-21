import { useEffect, useMemo, useState } from "react";
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
  const eligible = useMemo(() => options?.uoms.filter((uom) => uom.code === "EACH"
    || (draft.has_package && uom.code === draft.package_uom_code)) ?? [],
  [draft.has_package, draft.package_uom_code, options?.uoms]);
  const defaultUom = (draft.has_package
    ? eligible.find((uom) => uom.code === draft.package_uom_code)
    : undefined) ?? eligible.find((uom) => uom.code === "EACH") ?? eligible[0];
  const [pendingUomId, setPendingUomId] = useState<number | null>(null);

  useEffect(() => {
    setPendingUomId(value?.purchase_uom_id ?? defaultUom?.id ?? null);
  }, [defaultUom?.id, value?.purchase_uom_id]);

  if (!options?.can_manage && !value && !failed) return null;

  const unavailableUom = Boolean(value && !eligible.some((uom) => uom.id === value.purchase_uom_id));
  const selectedUomId = value?.purchase_uom_id ?? pendingUomId ?? defaultUom?.id ?? null;
  const currencyCode = value?.currency_code ?? options?.currency_code ?? null;
  const canEnter = options?.can_manage === true && !saving && selectedUomId !== null && Boolean(currencyCode);

  return (
    <div dir={i18n.dir()} className="mt-4 border-t border-slate-200 pt-4">
      {failed ? <div role="alert" className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
        <p className="text-xs font-bold text-amber-900">{t("unavailable")}</p>
        <button type="button" disabled={saving} onClick={onRetry}
          className="shrink-0 text-xs font-black text-amber-900 underline underline-offset-4">{t("retry")}</button>
      </div> : null}
      {options?.can_manage || value ? <>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-black text-slate-600">
            {t("amount")}
            <input
              inputMode="decimal"
              aria-label={t("amount")}
              value={value?.amount ?? ""}
              disabled={!canEnter}
              placeholder={t("amountPlaceholder")}
              onChange={(event) => {
                const amount = event.target.value.replace(/[^0-9.]/g, "");
                if (!amount) {
                  onChange(undefined);
                  return;
                }
                if (selectedUomId === null || !currencyCode) return;
                onChange({ amount, purchase_uom_id: selectedUomId, currency_code: currencyCode });
              }}
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:bg-slate-100"
            />
          </label>
          <label className="text-xs font-black text-slate-600">
            {t("uom")}
            <select
              aria-label={t("uom")}
              value={selectedUomId === null ? "" : String(selectedUomId)}
              disabled={!options?.can_manage || saving || eligible.length === 0}
              onChange={(event) => {
                const purchaseUomId = Number(event.target.value);
                setPendingUomId(purchaseUomId);
                if (value) onChange({ ...value, purchase_uom_id: purchaseUomId });
              }}
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:bg-slate-100"
            >
              {unavailableUom ? <option value={String(value?.purchase_uom_id)} disabled>{t("chooseUom")}</option> : null}
              {eligible.map((uom) => <option key={uom.id} value={uom.id}>
                {t(`uom.${uom.code}`, { ns: "translation" })}
              </option>)}
            </select>
          </label>
        </div>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] font-bold">
          <p className="text-slate-500">{t("hint")}</p>
          {currencyCode ? <p className="text-slate-700">{t("currency", { currency: currencyCode })}</p> : null}
        </div>
        {unavailableUom ? <p role="alert" className="mt-2 text-xs font-bold text-rose-700">{t("changedUom")}</p> : null}
        {options?.can_manage === false ? <p role="alert" className="mt-2 text-xs font-bold text-rose-700">{t("denied")}</p> : null}
        {options?.currency_code && value && options.currency_code !== value.currency_code
          ? <p role="alert" className="mt-2 text-xs font-bold text-rose-700">{t("changedCurrency")}</p> : null}
      </> : null}
    </div>
  );
}
