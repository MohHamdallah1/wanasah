import { Save, Search, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTransferDestinationPolicy } from "./useTransferDestinationPolicy";

export function QualityHandlingDestinationsCard({ compact = false, onSaved }: { compact?: boolean; onSaved?: () => void | Promise<void> } = {}) {
  const { t, i18n } = useTranslation();
  const controller = useTransferDestinationPolicy(onSaved);
  const { canManage, policy, form, setForm, options, searchInput, setSearchInput,
    hasMoreLocations, loading, saving, pending, loadError, saveDraft, publish, canPublish } = controller;
  if (!canManage) return null;

  const select = (key: "quarantine" | "disposal" | "vendorReturn", labelKey: string, hintKey: string) => (
    <label className="block min-w-0">
      <span className="text-xs font-black text-slate-800">{t(labelKey)}</span>
      {!compact ? <span className="mt-0.5 block text-[10px] font-semibold leading-4 text-slate-500">{t(hintKey)}</span> : null}
      <select value={form[key] ?? ""} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value ? Number(event.target.value) : null }))}
        className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
        <option value="">{t("inventoryWarehouses.qualityDestinations.choose")}</option>
        {options.map((item) => <option key={item.id} value={item.id}>{item.name}{item.code ? ` · ${item.code}` : ""}</option>)}
      </select>
    </label>
  );

  return <section dir={i18n.dir()} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-3" aria-labelledby="quality-destinations-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 id="quality-destinations-title" className="flex items-center gap-2 text-sm font-black text-slate-900"><ShieldCheck className="h-4 w-4 text-blue-600" />{t("transferDestinationSetup.setup")}</h3>
        {!compact ? <p className="mt-1 max-w-3xl text-[10px] font-semibold leading-5 text-slate-500">{t("transferDestinationSetup.hint")}</p> : null}
      </div>
      {!compact ? <span className={`rounded-full px-2.5 py-1 text-[9px] font-black ${policy.published ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{t(policy.published ? "inventoryWarehouses.qualityDestinations.active" : "inventoryWarehouses.qualityDestinations.notConfigured")}</span> : null}
    </div>
    {loadError && <div role="alert"><p>{loadError}</p><button type="button" onClick={() => void controller.loadPolicy()}>{t("transferDestinationSetup.retry")}</button></div>}
    <form onSubmit={event => { event.preventDefault(); void saveDraft(); }}>
    <fieldset disabled={loading || saving || Boolean(pending) || Boolean(loadError)} className="min-w-0">
    <div className="mt-3 relative"><Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} aria-label={t("inventoryWarehouses.qualityDestinations.search")} placeholder={t("inventoryWarehouses.qualityDestinations.search")} className="w-full rounded-xl border border-slate-200 bg-white py-2.5 ps-10 pe-3 text-sm outline-none focus:ring-2 focus:ring-blue-500/20" /></div>
    {hasMoreLocations ? <p className="mt-1 text-[9px] font-semibold text-slate-500">{t("inventoryWarehouses.qualityDestinations.searchMore")}</p> : null}
    <div className="mt-3 grid gap-3 lg:grid-cols-3">
      {select("quarantine", "inventoryWarehouses.qualityDestinations.quarantine.label", "inventoryWarehouses.qualityDestinations.quarantine.hint")}
      {select("vendorReturn", "inventoryWarehouses.qualityDestinations.vendorReturn.label", "inventoryWarehouses.qualityDestinations.vendorReturn.hint")}
      {select("disposal", "inventoryWarehouses.qualityDestinations.disposal.label", "inventoryWarehouses.qualityDestinations.disposal.hint")}
    </div>
    <div className="mt-3 flex justify-end"><button type="submit" disabled={loading || saving} className="inline-flex min-h-9 items-center gap-2 rounded-xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"><Save className="h-4 w-4" />{saving ? t("common.loading") : t("transferDestinationSetup.saveDraft")}</button></div>
    <button type="button" disabled={!canPublish || loading || saving} onClick={() => void publish()} className="mt-3 rounded-xl border px-4 py-2">{t("transferDestinationSetup.publish")}</button>
    </fieldset></form>
    {pending && <div role="alert"><p>{t("transferDestinationSetup.pending")}</p><button type="button" disabled={saving} onClick={() => void controller.retry()}>{t("transferDestinationSetup.retry")}</button></div>}
  </section>;
}
