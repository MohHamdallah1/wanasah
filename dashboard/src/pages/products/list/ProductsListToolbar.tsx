import type {
  ReactNode,
} from "react";
import {
  ListFilter,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

type Props = {
  searchInput: string;
  filtersOpen: boolean;
  hasActiveControls: boolean;
  filtersContent: ReactNode;
  onSearchInputChange: (
    value: string,
  ) => void;
  onFiltersOpenChange: (
    open: boolean,
  ) => void;
};

export function ProductsListToolbar({
  searchInput,
  filtersOpen,
  hasActiveControls,
  filtersContent,
  onSearchInputChange,
  onFiltersOpenChange,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const direction =
    i18n.dir();

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="relative min-w-0 flex-1">
        <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          value={searchInput}
          maxLength={100}
          onChange={(event) =>
            onSearchInputChange(
              event.target.value,
            )
          }
          placeholder={t(
            "products.searchPlaceholder",
          )}
          aria-label={t(
            "products.searchPlaceholder",
          )}
          className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pe-3 ps-10 text-sm font-normal text-slate-900 outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20"
        />
      </div>

      <div className="flex items-center gap-2">
        <Popover
          open={filtersOpen}
          onOpenChange={
            onFiltersOpenChange
          }
        >
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-expanded={
                filtersOpen
              }
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
                  : "products.filters.show",
              )}
              {hasActiveControls &&
              !filtersOpen ? (
                <span
                  aria-hidden="true"
                  className="absolute -end-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-amber-400"
                />
              ) : null}
            </button>
          </PopoverTrigger>

          <PopoverContent
            dir={direction}
            align={
              direction === "rtl"
                ? "start"
                : "end"
            }
            sideOffset={8}
            className="max-h-[70vh] w-[min(94vw,68rem)] overflow-y-auto rounded-2xl border-slate-200 bg-white p-4 text-start shadow-2xl"
          >
            {filtersContent}
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}
