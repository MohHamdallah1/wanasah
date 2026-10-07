import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiErrorMessage } from "@/lib/apiErrors";
import { Modal } from "@/components/ui/modal";
import { useSupplierSearch } from "@/features/suppliers/useSupplierSearch";
import { supplierDraftKey, type Supplier } from "@/features/suppliers/contracts";
import { SupplierEditor } from "./SupplierEditor";
import { SupplierTable } from "./SupplierTable";
import { useSupplierCommands } from "./useSupplierCommands";

export default function SuppliersPage() {
  const { t, i18n } = useTranslation();
  const [active, setActive] = useState<boolean | null>(true);
  const search = useSupplierSearch(active);
  const commands = useSupplierCommands(search.access.data?.company_id, search.access.data?.driver_id);
  const [editor, setEditor] = useState<{ supplier: Supplier | null } | null>(null);
  const [stateRow, setStateRow] = useState<Supplier | null>(null);
  const manage = search.access.can("supplier.manage");
  const blocked = !commands.online || commands.busy || commands.pending !== null;
  if (search.access.isPending) return <p role="status">{t("common.loading")}</p>;
  if (!search.access.can("supplier.read")) return <p role="alert">{t("suppliers.denied")}</p>;
  return <main className="h-full overflow-auto p-4 text-foreground" dir={i18n.dir()}>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-bold">{t("suppliers.title")}</h1>
      {manage ? <button type="button" disabled={blocked} onClick={() => setEditor({ supplier: null })} className="rounded-lg bg-primary px-4 py-2 text-primary-foreground">{t("suppliers.add")}</button> : null}
    </div>
    {!commands.online ? <p role="status">{t("suppliers.offline")}</p> : null}
    {commands.error ? <p role="alert" className="my-2 text-destructive">{commands.error}</p> : null}
    {commands.pending ? <div role="status" className="my-3 rounded-lg border p-3">
      <p>{t("suppliers.pending")}</p>
      <button type="button" disabled={commands.busy || !commands.online || !manage} onClick={() => { void commands.execute(); }}>{t("common.retry")}</button>
    </div> : null}
    <div className="mb-4 flex flex-wrap gap-3">
      <input aria-label={t("suppliers.search")} placeholder={t("suppliers.search")} type="search" maxLength={100}
        value={search.input} onChange={event => search.setInput(event.target.value)} className="rounded-lg border bg-background p-2 text-foreground" />
      <select aria-label={t("suppliers.fields.status")} value={active === null ? "all" : String(active)}
        onChange={event => { search.resetPagination(); setActive(event.target.value === "all" ? null : event.target.value === "true"); }} className="rounded-lg border bg-background p-2 text-foreground">
        <option value="true">{t("suppliers.active")}</option><option value="false">{t("suppliers.inactive")}</option><option value="all">{t("suppliers.all")}</option>
      </select>
    </div>
    {search.query.isFetching ? <p role="status">{t("common.loading")}</p> : null}
    {search.query.isError ? <p role="alert">{apiErrorMessage(search.query.error, t("suppliers.loadFailed"))}
      <button type="button" onClick={() => { void search.query.refetch(); }}>{t("common.retry")}</button></p> : null}
    {!search.query.isFetching && !search.query.isError && search.query.data?.items.length === 0 ? <p>{t("suppliers.empty")}</p> : null}
    <SupplierTable items={search.query.isError ? [] : search.query.data?.items ?? []} manage={manage} disabled={blocked}
      onEdit={supplier => setEditor({ supplier })} onState={setStateRow} />
    <div className="mt-3 flex gap-3">
      <button type="button" disabled={!search.hasBack || search.query.isFetching} onClick={search.back}>{t("suppliers.previous")}</button>
      <button type="button" disabled={!search.query.data?.has_more || search.query.isFetching} onClick={search.next}>{t("suppliers.next")}</button>
    </div>
    {editor ? <SupplierEditor supplier={editor.supplier} busy={commands.busy} blocked={blocked || !manage}
      error={commands.error}
      blockedReason={commands.pending ? t("suppliers.pending") : !commands.online ? t("suppliers.offline") : undefined}
      onRetry={commands.pending && commands.online && manage ? () => commands.execute() : undefined}
      storageKey={supplierDraftKey(search.access.data?.company_id, search.access.data?.driver_id, editor.supplier?.id ?? "new")}
      onClose={() => setEditor(null)} onSave={async details => {
        const saved = await commands.execute({
        endpoint: editor.supplier ? `/suppliers/${editor.supplier.id}` : "/suppliers", method: editor.supplier ? "PUT" : "POST",
        body: { ...details, ...(editor.supplier ? { expected_version: editor.supplier.version } : {}) },
        });
        if (saved && !editor.supplier) { search.resetPagination(); search.setInput(""); setActive(true); }
        return saved;
      }} /> : null}
    {stateRow ? <Modal isOpen title={t(stateRow.is_active ? "suppliers.deactivate" : "suppliers.activate")} onClose={() => { if (!commands.busy) setStateRow(null); }}>
      <form onSubmit={async event => {
        event.preventDefault(); if (blocked || !manage) return;
        if (await commands.execute({ endpoint: `/suppliers/${stateRow.id}/state`, method: "PATCH",
          body: { expected_version: stateRow.version, is_active: !stateRow.is_active } })) setStateRow(null);
      }}>
        <p>{t("suppliers.stateConfirmation", { name: stateRow.name })}</p>
        <div className="mt-4 flex justify-end gap-3"><button type="button" onClick={() => setStateRow(null)} disabled={commands.busy}>{t("common.cancel")}</button>
          <button type="submit" disabled={blocked || !manage}>{t("common.confirm")}</button></div>
      </form>
    </Modal> : null}
  </main>;
}
