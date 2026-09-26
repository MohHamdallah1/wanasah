import {
  ListFilter,
  Search,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

type Props = {
  searchInput: string;
  filtersOpen: boolean;
  hasActiveControls: boolean;
  onSearchInputChange: (value: string) => void;
  onToggleFilters: () => void;
  onClearControls: () => void;
};

export function ProductsListToolbar({
  searchInput,
  filtersOpen,
  hasActiveControls,
  onSearchInputChange,
  onToggleFilters,
  onClearControls,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="relative min-w-0 flex-1">
        <Search className="absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          value={searchInput}
          maxLength={100}
          onChange={(event) =>
            onSearchInputChange(
              event.target.value
            )
          }
          placeholder={t(
            "products.searchPlaceholder"
          )}
          aria-label={t(
            "products.searchPlaceholder"
          )}
          className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50/70 py-2 pe-10 ps-3 text-sm font-bold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
        />
      </div>

      <div className="flex items-center gap-2">
        {hasActiveControls ? (
          <button
            type="button"
            onClick={onClearControls}
            className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl px-2.5 text-xs font-black text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <X className="h-3.5 w-3.5" />
            {t(
              "products.filters.clear"
            )}
          </button>
        ) : null}

        <button
          type="button"
          onClick={onToggleFilters}
          aria-pressed={filtersOpen}
          className={`relative inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-3 text-xs font-black shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
            filtersOpen
              ? "border-slate-300 bg-slate-950 text-white"
              : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
          }`}
        >
          <ListFilter className="h-4 w-4" />
          {t(
            filtersOpen
              ? "products.filters.hide"
              : "products.filters.show"
          )}
          {hasActiveControls &&
          !filtersOpen ? (
            <span
              aria-hidden="true"
              className="absolute -end-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400"
            />
          ) : null}
        </button>
      </div>
    </div>
  );
}
