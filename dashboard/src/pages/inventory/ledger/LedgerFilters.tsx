import type { TFunction } from "i18next";
import { RefreshCcw, Search } from "lucide-react";

import { ledgerMovementLabel, ledgerText } from "./ledgerI18n";

interface Props {
  t: TFunction;
  language: string;
  search: string;
  onSearchChange: (value: string) => void;
  filterType: string;
  onFilterTypeChange: (value: string) => void;
  availableTypes: string[];
  loading: boolean;
  onRefresh: () => void;
}

export function LedgerFilters({
  t,
  language,
  search,
  onSearchChange,
  filterType,
  onFilterTypeChange,
  availableTypes,
  loading,
  onRefresh,
}: Props) {
  const text = (key: Parameters<typeof ledgerText>[2]) => ledgerText(t, language, key);
  return (
    <div className="flex flex-col gap-2 border-b border-slate-100 bg-slate-50 p-3 sm:flex-row sm:items-center">
      <div className="relative min-w-0 flex-1">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          maxLength={100}
          aria-label={text("search")}
          placeholder={text("search")}
          className="h-10 w-full rounded-xl border border-slate-200 bg-white ps-9 pe-3 text-xs font-bold text-slate-800 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
        />
      </div>
      <select
        value={filterType}
        onChange={(event) => onFilterTypeChange(event.target.value)}
        aria-label={text("movement")}
        className="h-10 min-w-48 rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
      >
        <option value="ALL">{text("allTypes")}</option>
        {availableTypes.map((type) => (
          <option key={type} value={type}>{ledgerMovementLabel(t, language, type)}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        aria-label={text("refresh")}
        title={text("refresh")}
        className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 outline-none hover:bg-slate-50 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-blue-300"
      >
        <RefreshCcw aria-hidden="true" className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        <span className="sm:sr-only">{text("refresh")}</span>
      </button>
    </div>
  );
}
