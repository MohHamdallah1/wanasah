import { Check, Search, Warehouse, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProductWarehouseFilterOption } from "./warehouseFilterContract";

type Props = {
  enabled: boolean;
  searchInput: string;
  options: ProductWarehouseFilterOption[];
  selected: ProductWarehouseFilterOption[];
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  onSearchInputChange: (value: string) => void;
  onRetry: () => void;
  onChange: (value: ProductWarehouseFilterOption[]) => void;
};

export function ProductsWarehouseFilter({
  enabled,
  searchInput,
  options,
  selected,
  loading,
  error,
  hasMore,
  onSearchInputChange,
  onRetry,
  onChange,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const selectedIds = useMemo(
    () => new Set(selected.map((item) => item.id)),
    [selected],
  );
  const visibleOptions = useMemo(() => {
    const byId = new Map<number, ProductWarehouseFilterOption>();
    for (const item of selected) byId.set(item.id, item);
    for (const item of options) byId.set(item.id, item);
    return [...byId.values()];
  }, [options, selected]);

  if (!enabled) return null;

  const summary =
    selected.length === 0
      ? t("products.filters.warehousesAll")
      : selected.length === 1
        ? selected[0].name
        : t("products.filters.warehousesSelected", { count: selected.length });

  const toggle = (item: ProductWarehouseFilterOption) => {
    if (selectedIds.has(item.id)) {
      onChange(selected.filter((current) => current.id !== item.id));
      return;
    }
    if (selected.length >= 20) return;
    onChange([...selected, item].sort((a, b) => a.id - b.id));
  };

  return (
    <div className="space-y-1 xl:col-span-2">
      <span className="text-[11px] font-black text-slate-500">
        {t("products.filters.warehouses")}
      </span>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 text-start text-xs font-bold text-slate-700 outline-none transition hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-slate-100"
      >
        <span className="flex min-w-0 items-center gap-2">
          <Warehouse className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate">{summary}</span>
        </span>
        {selected.length > 0 ? (
          <span className="shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-600">
            {selected.length}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_14px_36px_-30px_rgba(15,23,42,0.45)]">
          <div className="border-b border-slate-100 p-2.5">
            <div className="relative">
              <Search className="absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchInput}
                maxLength={100}
                onChange={(event) => onSearchInputChange(event.target.value)}
                placeholder={t("products.filters.warehouseSearch")}
                className="h-8 w-full rounded-lg border border-slate-200 bg-slate-50 pe-2.5 ps-8 text-[11px] font-semibold text-slate-800 outline-none placeholder:font-normal placeholder:text-slate-400 focus:border-slate-300 focus:bg-white"
              />
            </div>
            <p className="mt-2 text-[9px] font-semibold leading-4 text-slate-500">
              {t("products.filters.warehouseIntersectionHint")}
            </p>
          </div>

          <div className="max-h-52 overflow-y-auto p-1.5">
            {loading ? (
              <p className="px-2 py-3 text-[10px] font-semibold text-slate-400">
                {t("common.loading")}
              </p>
            ) : error ? (
              <button
                type="button"
                onClick={onRetry}
                className="w-full rounded-lg px-2 py-3 text-start text-[10px] font-bold text-rose-700 hover:bg-rose-50"
              >
                {t("products.filters.warehouseLoadFailed")}
              </button>
            ) : visibleOptions.length === 0 ? (
              <p className="px-2 py-3 text-[10px] font-semibold text-slate-400">
                {t("products.filters.warehouseEmpty")}
              </p>
            ) : (
              visibleOptions.map((item) => {
                const checked = selectedIds.has(item.id);
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="checkbox"
                    aria-checked={checked}
                    onClick={() => toggle(item)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-start transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
                  >
                    <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${checked ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white text-transparent"}`}>
                      <Check className="h-3 w-3" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11px] font-black text-slate-800">{item.name}</span>
                      <span className="block truncate text-[9px] font-semibold text-slate-400">{item.code}</span>
                    </span>
                  </button>
                );
              })
            )}
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-2.5 py-2">
            <span className="text-[9px] font-semibold text-slate-400">
              {hasMore ? t("products.filters.warehouseSearchMore") : t("products.filters.warehouseSelectionLimit")}
            </span>
            {selected.length > 0 ? (
              <button
                type="button"
                onClick={() => onChange([])}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[9px] font-black text-slate-500 hover:bg-slate-100 hover:text-slate-800"
              >
                <X className="h-3 w-3" />
                {t("products.filters.clearWarehouses")}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
