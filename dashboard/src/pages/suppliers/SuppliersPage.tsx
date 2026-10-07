import { useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Plus,
  RefreshCw,
  Search,
  UsersRound,
  WifiOff,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import { Modal } from "@/components/ui/modal";
import { useSupplierSearch } from "@/features/suppliers/useSupplierSearch";
import { supplierDraftKey, type Supplier } from "@/features/suppliers/contracts";
import { apiErrorMessage } from "@/lib/apiErrors";
import { SupplierEditor } from "./SupplierEditor";
import { SupplierTable } from "./SupplierTable";
import { useSupplierCommands } from "./useSupplierCommands";

const filterOptions = [
  { value: true, key: "suppliers.active" },
  { value: false, key: "suppliers.inactive" },
  { value: null, key: "suppliers.all" },
] as const;

export default function SuppliersPage() {
  const { t, i18n } = useTranslation();
  const [active, setActive] = useState<boolean | null>(true);
  const search = useSupplierSearch(active);
  const commands = useSupplierCommands(search.access.data?.company_id, search.access.data?.driver_id);
  const [editor, setEditor] = useState<{ supplier: Supplier | null } | null>(null);
  const [stateRow, setStateRow] = useState<Supplier | null>(null);
  const manage = search.access.can("supplier.manage");
  const blocked = !commands.online || commands.busy || commands.pending !== null;
  const items = search.query.isError ? [] : search.query.data?.items ?? [];

  if (search.access.isPending) {
    return <div className="grid h-full place-items-center text-sm font-semibold text-slate-500" role="status">{t("common.loading")}</div>;
  }
  if (!search.access.can("supplier.read")) {
    return <div className="grid h-full place-items-center p-6" role="alert"><div className="rounded-2xl border border-rose-200/70 bg-rose-50/80 px-5 py-4 font-bold text-rose-700 shadow-sm">{t("suppliers.denied")}</div></div>;
  }

  return <main className="relative flex min-h-0 flex-1 flex-col overflow-visible text-foreground" dir={i18n.dir()}>
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="absolute -right-20 top-12 h-72 w-72 rounded-full bg-cyan-200/25 blur-3xl" />
      <div className="absolute bottom-10 left-12 h-72 w-72 rounded-full bg-amber-100/[0.35] blur-3xl" />
    </div>

    <WorkspaceTopBar variant="page" className="shrink-0">
      <header className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-lg font-black leading-6 text-white sm:text-xl">{t("suppliers.title")}</h1>
          <p className="mt-0.5 hidden text-[11px] font-semibold leading-5 text-slate-300/80 sm:block">{t("suppliers.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          {manage ? <button type="button" disabled={blocked} onClick={() => setEditor({ supplier: null })}
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-amber-400 px-4 text-sm font-black text-slate-950 shadow-[0_8px_24px_-12px_rgba(251,191,36,0.9)] transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50">
            <Plus className="h-4 w-4" />{t("suppliers.add")}
          </button> : null}
          <button type="button" onClick={() => void search.query.refetch()} disabled={search.query.isFetching}
            aria-label={t("common.refresh")} title={t("common.refresh")}
            className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.07] text-slate-200 transition hover:bg-white/[0.12] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-60">
            <RefreshCw className={`h-4 w-4 ${search.query.isFetching ? "animate-spin" : ""}`} />
          </button>
        </div>
      </header>
    </WorkspaceTopBar>

    <div className="relative z-10 min-h-0 flex-1 overflow-auto px-4 pb-5 pt-4 sm:px-5">
      <section className="mx-auto w-full max-w-[1500px] space-y-3">
        {!commands.online ? <div role="status" className="flex items-center gap-2 rounded-2xl border border-amber-200/70 bg-amber-50/80 px-4 py-3 text-sm font-bold text-amber-800 shadow-sm backdrop-blur-xl"><WifiOff className="h-4 w-4" />{t("suppliers.offline")}</div> : null}
        {commands.error ? <div role="alert" className="flex items-center gap-2 rounded-2xl border border-rose-200/70 bg-rose-50/[0.85] px-4 py-3 text-sm font-bold text-rose-700 shadow-sm backdrop-blur-xl"><AlertTriangle className="h-4 w-4" />{commands.error}</div> : null}
        {commands.pending ? <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200/70 bg-white/75 px-4 py-3 shadow-sm backdrop-blur-xl">
          <span className="text-sm font-bold text-slate-700">{t("suppliers.pending")}</span>
          <button type="button" disabled={commands.busy || !commands.online || !manage} onClick={() => void commands.execute()}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">{t("common.retry")}</button>
        </div> : null}

        <div className="rounded-[22px] border border-white/80 bg-white/[0.68] p-2.5 shadow-[0_18px_50px_-36px_rgba(15,23,42,0.55)] backdrop-blur-2xl">
          <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute start-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input aria-label={t("suppliers.search")} placeholder={t("suppliers.search")} type="search" maxLength={100}
                value={search.input} onChange={event => search.setInput(event.target.value)}
                className="h-11 w-full rounded-2xl border border-slate-200/80 bg-white/[0.82] pe-10 ps-10 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:ring-4 focus:ring-cyan-100/60" />
              {search.input ? <button type="button" aria-label={t("suppliers.clearSearch")} onClick={() => search.setInput("")}
                className="absolute end-2.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"><X className="h-3.5 w-3.5" /></button> : null}
            </div>
            <div className="flex min-w-max items-center rounded-2xl border border-slate-200/70 bg-slate-100/[0.65] p-1" aria-label={t("suppliers.filterLabel")}>
              {filterOptions.map(option => {
                const selected = active === option.value;
                return <button key={String(option.value)} type="button" aria-pressed={selected}
                  onClick={() => { search.resetPagination(); setActive(option.value); }}
                  className={`h-9 rounded-xl px-3.5 text-xs font-black transition ${selected ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/70" : "text-slate-500 hover:text-slate-800"}`}>
                  {t(option.key)}
                </button>;
              })}
            </div>
          </div>
        </div>

        {search.query.isError ? <div role="alert" className="rounded-[24px] border border-rose-200/70 bg-white/75 p-6 text-center shadow-sm backdrop-blur-xl">
          <p className="font-bold text-rose-700">{apiErrorMessage(search.query.error, t("suppliers.loadFailed"))}</p>
          <button type="button" onClick={() => void search.query.refetch()} className="mt-3 rounded-xl bg-slate-900 px-4 py-2 text-sm font-black text-white">{t("common.retry")}</button>
        </div> : null}

        {!search.query.isError && !search.query.isFetching && items.length === 0 ? <div className="grid min-h-[360px] place-items-center rounded-[28px] border border-white/80 bg-white/[0.58] px-6 text-center shadow-[0_20px_60px_-44px_rgba(15,23,42,0.6)] backdrop-blur-2xl">
          <div className="max-w-sm">
            <div className="mx-auto grid h-16 w-16 place-items-center rounded-[22px] border border-white bg-gradient-to-br from-cyan-50 to-amber-50 shadow-sm"><UsersRound className="h-7 w-7 text-slate-600" /></div>
            <h2 className="mt-4 text-base font-black text-slate-900">{t("suppliers.empty")}</h2>
            <p className="mt-1.5 text-sm font-semibold leading-6 text-slate-500">{t("suppliers.emptyHint")}</p>
            {manage && !search.input && active === true ? <button type="button" disabled={blocked} onClick={() => setEditor({ supplier: null })}
              className="mt-4 inline-flex h-10 items-center gap-2 rounded-xl bg-slate-900 px-4 text-sm font-black text-white transition hover:bg-slate-800 disabled:opacity-50"><Plus className="h-4 w-4" />{t("suppliers.add")}</button> : null}
          </div>
        </div> : null}

        {!search.query.isError && items.length > 0 ? <div className="overflow-hidden rounded-[26px] border border-white/[0.85] bg-white/[0.62] shadow-[0_22px_65px_-46px_rgba(15,23,42,0.65)] backdrop-blur-2xl">
          <SupplierTable items={items} manage={manage} disabled={blocked} onEdit={supplier => setEditor({ supplier })} onState={setStateRow} />
          <footer className="flex items-center justify-between border-t border-slate-200/70 bg-white/[0.55] px-3 py-2.5 sm:px-4">
            <span className="text-xs font-bold text-slate-400">{t("suppliers.visibleCount", { count: items.length })}</span>
            <div className="flex items-center gap-2">
              <button type="button" disabled={!search.hasBack || search.query.isFetching} onClick={search.back} aria-label={t("suppliers.previous")}
                className="inline-flex h-9 items-center gap-1 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35">{i18n.dir() === "rtl" ? <ArrowRight className="h-3.5 w-3.5" /> : <ArrowLeft className="h-3.5 w-3.5" />}{t("suppliers.previous")}</button>
              <button type="button" disabled={!search.query.data?.has_more || search.query.isFetching} onClick={search.next} aria-label={t("suppliers.next")}
                className="inline-flex h-9 items-center gap-1 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35">{t("suppliers.next")}{i18n.dir() === "rtl" ? <ArrowLeft className="h-3.5 w-3.5" /> : <ArrowRight className="h-3.5 w-3.5" />}</button>
            </div>
          </footer>
        </div> : null}
      </section>
    </div>

    {editor ? <SupplierEditor supplier={editor.supplier} busy={commands.busy} blocked={blocked || !manage}
      error={commands.error} blockedReason={commands.pending ? t("suppliers.pending") : !commands.online ? t("suppliers.offline") : undefined}
      onRetry={commands.pending && commands.online && manage ? () => commands.execute() : undefined}
      storageKey={supplierDraftKey(search.access.data?.company_id, search.access.data?.driver_id, editor.supplier?.id ?? "new")}
      onClose={() => setEditor(null)} onSave={async details => {
        const saved = await commands.execute({ endpoint: editor.supplier ? `/suppliers/${editor.supplier.id}` : "/suppliers", method: editor.supplier ? "PUT" : "POST",
          body: { ...details, ...(editor.supplier ? { expected_version: editor.supplier.version } : {}) } });
        if (saved && !editor.supplier) { search.resetPagination(); search.setInput(""); setActive(true); }
        return saved;
      }} /> : null}

    {stateRow ? <Modal isOpen title={t(stateRow.is_active ? "suppliers.deactivate" : "suppliers.activate")} onClose={() => { if (!commands.busy) setStateRow(null); }}>
      <form className="space-y-4" onSubmit={async event => {
        event.preventDefault(); if (blocked || !manage) return;
        if (await commands.execute({ endpoint: `/suppliers/${stateRow.id}/state`, method: "PATCH", body: { expected_version: stateRow.version, is_active: !stateRow.is_active } })) setStateRow(null);
      }}>
        <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 p-4"><p className="text-sm font-bold leading-6 text-slate-700">{t("suppliers.stateConfirmation", { name: stateRow.name })}</p></div>
        <div className="flex justify-end gap-2"><button type="button" onClick={() => setStateRow(null)} disabled={commands.busy} className="h-10 rounded-xl px-4 text-sm font-black text-slate-600 hover:bg-slate-100">{t("common.cancel")}</button>
          <button type="submit" disabled={blocked || !manage} className={`h-10 rounded-xl px-4 text-sm font-black text-white ${stateRow.is_active ? "bg-rose-600 hover:bg-rose-500" : "bg-emerald-600 hover:bg-emerald-500"}`}>{t("common.confirm")}</button></div>
      </form>
    </Modal> : null}
  </main>;
}
