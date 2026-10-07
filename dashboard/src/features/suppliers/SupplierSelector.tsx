import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { parseSupplier } from "./contracts";
import { useSupplierSearch } from "./useSupplierSearch";

/** Public, bounded Supplier selector; Inventory consumes identity, never page internals. */
export function SupplierSelector({ value, onChange, disabled = false }: {
  value: number | null; onChange: (value: number | null) => void; disabled?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const search = useSupplierSearch(true);
  const authFetch = useAuthFetch();
  const selected = useQuery({
    queryKey: ["supplier-selection", search.access.data?.company_id, search.access.data?.driver_id, value],
    enabled: value !== null && search.access.can("supplier.read"), retry: false, staleTime: 0,
    queryFn: async ({ signal }) => parseSupplier(await authFetch(`/suppliers/${value}`, { signal })),
  });
  const blocked = !search.access.can("supplier.read");
  const items = search.query.data?.items ?? [];
  const current = items.find(row => row.id === value) ?? selected.data;
  return <div className="space-y-2" dir={i18n.dir()}>
    <label htmlFor={`${id}-search`} className="block text-sm font-semibold">{t("suppliers.select")}</label>
    {blocked && !search.access.isPending ? <p role="alert">{t("suppliers.denied")}</p> : null}
    <input id={`${id}-search`} type="search" maxLength={100} disabled={disabled || blocked}
      value={search.input} onChange={event => search.setInput(event.target.value)}
      placeholder={t("suppliers.search")} className="w-full rounded-lg border bg-background p-2 text-foreground focus-visible:ring-2 focus-visible:ring-ring" />
    <select aria-label={t("suppliers.select")} value={value ?? ""} disabled={disabled || blocked}
      onChange={event => onChange(event.target.value ? Number(event.target.value) : null)}
      className="w-full rounded-lg border bg-background p-2 text-foreground focus-visible:ring-2 focus-visible:ring-ring">
      <option value="">{t("suppliers.choose")}</option>
      {current && !items.some(row => row.id === current.id) ? <option value={current.id} disabled={!current.is_active}>
        {current.name}{current.code ? ` · ${current.code}` : ""}{!current.is_active ? ` · ${t("suppliers.inactive")}` : ""}
      </option> : null}
      {items.map(row => <option key={row.id} value={row.id}>{row.name}{row.code ? ` · ${row.code}` : ""}</option>)}
    </select>
    {search.query.isFetching ? <p role="status">{t("common.loading")}</p> : null}
    {search.query.isError || selected.isError ? <p role="alert">{apiErrorMessage(search.query.error ?? selected.error, t("suppliers.loadFailed"))}
      <button type="button" onClick={() => { void search.query.refetch(); void selected.refetch(); }}>{t("common.retry")}</button></p> : null}
    {current && !current.is_active ? <p role="alert">{t("suppliers.inactiveSelection")}</p> : null}
    {!blocked && !search.query.isFetching && !search.query.isError && items.length === 0 ? <p>{t("suppliers.empty")}</p> : null}
    <div className="flex gap-2">
      <button type="button" disabled={disabled || !search.hasBack || search.query.isFetching} onClick={search.back}>{t("suppliers.previous")}</button>
      <button type="button" disabled={disabled || !search.query.data?.has_more || search.query.isFetching} onClick={search.next}>{t("suppliers.next")}</button>
    </div>
  </div>;
}
