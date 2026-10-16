import { AlertTriangle, CheckCircle2, CircleDashed, RefreshCcw, Save, Search, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { warehousePresentationCopy } from "@/pages/inventory/warehouse-locations/presentationI18n";
import { useTransferDestinationPolicy } from "./useTransferDestinationPolicy";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30";

export function QualityHandlingDestinationsCard({ compact = false, onSaved }: { compact?: boolean; onSaved?: () => void | Promise<void> } = {}) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const presentation = warehousePresentationCopy(language);
  const controller = useTransferDestinationPolicy(onSaved);
  const { canManage, policy, form, setForm, options, searchInput, setSearchInput,
    hasMoreLocations, loading, saving, pending, loadError, saveDraft, publish, canPublish } = controller;
  if (!canManage) return null;

  const select = (key: "quarantine" | "disposal" | "vendorReturn", labelKey: string, hintKey: string) => (
    <label className="block min-w-0">
      <span className="text-xs font-black text-slate-800">{t(labelKey)}</span>
      {!compact ? <span className="mt-0.5 block text-[10px] font-semibold leading-4 text-slate-500">{t(hintKey)}</span> : null}
      <select
        value={form[key] ?? ""}
        onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value ? Number(event.target.value) : null }))}
        className={`mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 ${focusRing}`}
      >
        <option value="">{t("inventoryWarehouses.qualityDestinations.choose")}</option>
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}{item.code ? ` · ${item.code}` : ""}</option>)}
      </select>
    </label>
  );

  return (
    <section
      dir={i18n.dir()}
      className="rounded-2xl border border-blue-100 bg-blue-50/35 p-3 sm:p-4"
      aria-labelledby="quality-destinations-title"
      data-warehouse-setup="quality-policy"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.14em] text-blue-700">
            <ShieldCheck aria-hidden="true" className="h-4 w-4" />
            {presentation.qualityPolicy}
          </div>
          <h3 id="quality-destinations-title" className="text-sm font-black text-slate-900">{t("transferDestinationSetup.setup")}</h3>
          {!compact ? (
            <div className="mt-1 max-w-3xl space-y-0.5 text-[10px] font-semibold leading-5 text-slate-500">
              <p>{t("transferDestinationSetup.hint")}</p>
              <p>{presentation.qualityPolicyHint}</p>
            </div>
          ) : null}
        </div>
        {!compact ? (
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[9px] font-black ${policy.published ? "bg-emerald-50 text-emerald-700" : "bg-white text-slate-600"}`}>
            {policy.published
              ? <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
              : <CircleDashed aria-hidden="true" className="h-3.5 w-3.5" />}
            {t(policy.published ? "inventoryWarehouses.qualityDestinations.active" : "inventoryWarehouses.qualityDestinations.notConfigured")}
          </span>
        ) : null}
      </div>

      {loadError && (
        <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
          <span className="flex min-w-0 items-center gap-2 break-words"><AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />{loadError}</span>
          <button type="button" onClick={() => void controller.loadPolicy()} className={`inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2 py-1 font-bold ${focusRing}`}>
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />{t("transferDestinationSetup.retry")}
          </button>
        </div>
      )}

      <form onSubmit={(event) => { event.preventDefault(); void saveDraft(); }}>
        <fieldset disabled={loading || saving || Boolean(pending) || Boolean(loadError)} className="min-w-0">
          <div className="relative mt-3">
            <Search aria-hidden="true" className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              aria-label={t("inventoryWarehouses.qualityDestinations.search")}
              placeholder={t("inventoryWarehouses.qualityDestinations.search")}
              className={`w-full rounded-xl border border-slate-200 bg-white py-2.5 ps-10 pe-3 text-sm ${focusRing}`}
            />
          </div>
          {hasMoreLocations ? <p className="mt-1 text-[9px] font-semibold text-slate-500">{t("inventoryWarehouses.qualityDestinations.searchMore")}</p> : null}
          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            {select("quarantine", "inventoryWarehouses.qualityDestinations.quarantine.label", "inventoryWarehouses.qualityDestinations.quarantine.hint")}
            {select("vendorReturn", "inventoryWarehouses.qualityDestinations.vendorReturn.label", "inventoryWarehouses.qualityDestinations.vendorReturn.hint")}
            {select("disposal", "inventoryWarehouses.qualityDestinations.disposal.label", "inventoryWarehouses.qualityDestinations.disposal.hint")}
          </div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <button type="submit" disabled={loading || saving} className={`inline-flex min-h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}>
              <Save aria-hidden="true" className="h-4 w-4" />{saving ? t("common.loading") : t("transferDestinationSetup.saveDraft")}
            </button>
            <button type="button" disabled={!canPublish || loading || saving} onClick={() => void publish()} className={`min-h-9 rounded-xl bg-blue-600 px-4 text-xs font-black text-white disabled:cursor-not-allowed disabled:opacity-40 ${focusRing}`}>
              {t("transferDestinationSetup.publish")}
            </button>
          </div>
        </fieldset>
      </form>

      {pending && (
        <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">
          <span className="flex min-w-0 items-center gap-2 break-words"><AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />{t("transferDestinationSetup.pending")}</span>
          <button type="button" disabled={saving} onClick={() => void controller.retry()} className={`inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-white px-2 py-1 font-bold disabled:opacity-40 ${focusRing}`}>
            <RefreshCcw aria-hidden="true" className="h-3.5 w-3.5" />{t("transferDestinationSetup.retry")}
          </button>
        </div>
      )}
    </section>
  );
}
