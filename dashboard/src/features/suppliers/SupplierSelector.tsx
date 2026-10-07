import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { cn } from "@/lib/utils";
import { parseSupplier } from "./contracts";
import { useSupplierSearch } from "./useSupplierSearch";

/** Public, bounded Supplier selector; Inventory consumes identity, never page internals. */
export function SupplierSelector({ value, onChange, disabled = false }: {
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const search = useSupplierSearch(true);
  const authFetch = useAuthFetch();
  const selected = useQuery({
    queryKey: ["supplier-selection", search.access.data?.company_id, search.access.data?.driver_id, value],
    enabled: value !== null && search.access.can("supplier.read"),
    retry: false,
    staleTime: 0,
    queryFn: async ({ signal }) => parseSupplier(await authFetch(`/suppliers/${value}`, { signal })),
  });
  const blocked = !search.access.can("supplier.read");
  const items = search.query.data?.items ?? [];
  const current = items.find((row) => row.id === value) ?? selected.data;
  const controlDisabled = disabled || blocked;

  return (
    <div className="space-y-2" dir={i18n.dir()}>
      <label id={`${id}-label`} className="block text-sm font-semibold">
        {t("suppliers.select")}
      </label>
      {blocked && !search.access.isPending ? <p role="alert">{t("suppliers.denied")}</p> : null}

      <Popover
        open={open && !controlDisabled}
        onOpenChange={(next) => {
          if (controlDisabled) return;
          setOpen(next);
          if (!next) search.setInput("");
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            role="combobox"
            aria-labelledby={`${id}-label`}
            aria-expanded={open}
            aria-controls={`${id}-options`}
            disabled={controlDisabled}
            className="flex min-h-10 w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 text-start text-sm font-bold text-slate-900 outline-none transition hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className={cn("truncate", !current && "text-slate-400")}>
              {current
                ? `${current.name}${current.code ? ` · ${current.code}` : ""}`
                : t("suppliers.choose")}
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 text-slate-400" />
          </button>
        </PopoverTrigger>

        <PopoverContent
          align="start"
          className="w-[var(--radix-popover-trigger-width)] min-w-64 overflow-hidden rounded-xl border-slate-200 p-0 shadow-xl"
        >
          <div className="flex items-center border-b border-slate-100 px-3">
            <Search className="me-2 h-4 w-4 shrink-0 text-slate-400" />
            <input
              id={`${id}-search`}
              type="search"
              value={search.input}
              onChange={(event) => search.setInput(event.target.value)}
              placeholder={t("suppliers.search")}
              maxLength={100}
              autoFocus
              className="h-11 w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
            />
          </div>

          <div id={`${id}-options`} role="listbox" className="max-h-64 overflow-y-auto p-1">
            {search.query.isFetching ? (
              <div role="status" className="px-3 py-3 text-xs font-bold text-slate-500">
                {t("common.loading")}
              </div>
            ) : null}
            {!search.query.isFetching && items.length === 0 ? (
              <p className="px-3 py-5 text-center text-xs font-bold text-slate-500">
                {t("suppliers.empty")}
              </p>
            ) : null}
            {items.map((row) => (
              <button
                key={row.id}
                type="button"
                role="option"
                aria-selected={row.id === value}
                onClick={() => {
                  onChange(row.id);
                  setOpen(false);
                  search.setInput("");
                }}
                className="flex min-h-10 w-full items-center gap-2 rounded-lg px-3 text-start text-xs font-bold text-slate-800 transition hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline-none"
              >
                <Check className={cn("h-4 w-4 shrink-0", row.id === value ? "opacity-100" : "opacity-0")} />
                <span className="truncate">
                  {row.name}{row.code ? ` · ${row.code}` : ""}
                </span>
              </button>
            ))}
          </div>

          {(search.hasBack || search.query.data?.has_more) ? (
            <div className="flex items-center justify-between gap-2 border-t border-slate-100 p-2">
              <button
                type="button"
                disabled={!search.hasBack || search.query.isFetching}
                onClick={search.back}
                className="rounded-lg px-2 py-1.5 text-[10px] font-black text-slate-600 hover:bg-slate-100 disabled:opacity-30"
              >
                {t("suppliers.previous")}
              </button>
              <button
                type="button"
                disabled={!search.query.data?.has_more || search.query.isFetching}
                onClick={search.next}
                className="rounded-lg px-2 py-1.5 text-[10px] font-black text-slate-600 hover:bg-slate-100 disabled:opacity-30"
              >
                {t("suppliers.next")}
              </button>
            </div>
          ) : null}
        </PopoverContent>
      </Popover>

      {search.query.isError || selected.isError ? (
        <p role="alert" className="text-xs font-bold text-rose-700">
          {apiErrorMessage(search.query.error ?? selected.error, t("suppliers.loadFailed"))}
          <button
            type="button"
            className="ms-2 underline"
            onClick={() => {
              void search.query.refetch();
              void selected.refetch();
            }}
          >
            {t("common.retry")}
          </button>
        </p>
      ) : null}
      {current && !current.is_active ? <p role="alert">{t("suppliers.inactiveSelection")}</p> : null}
    </div>
  );
}
