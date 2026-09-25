import {
  Search,
  Settings2,
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
    <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
      <div className="relative col-span-2 w-full min-w-0 sm:max-w-md sm:flex-1">
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
          className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pe-9 ps-3 text-sm font-bold outline-none focus:border-slate-400 focus:bg-white"
        />
      </div>

      <button
        type="button"
        onClick={onToggleFilters}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-center text-xs font-black text-slate-700 sm:w-auto"
      >
        <Settings2 className="h-4 w-4" />
        {t(
          filtersOpen
            ? "products.filters.hide"
            : "products.filters.show"
        )}
      </button>

      {hasActiveControls ? (
        <button
          type="button"
          onClick={onClearControls}
          className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-center text-xs font-black text-slate-600 sm:w-auto"
        >
          {t(
            "products.filters.clear"
          )}
        </button>
      ) : null}
    </div>
  );
}
