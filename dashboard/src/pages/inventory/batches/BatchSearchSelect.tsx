import { useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { batchUiNote } from "./batchUiNotes";

type Choice = { id: number; name: string; sku?: string | null };

interface Props<T extends Choice> {
  label: string;
  allLabel: string;
  language: string;
  value: number | null;
  options: T[];
  search: string;
  onSearchChange: (value: string) => void;
  onSelect: (value: number | null) => void;
  onOpen: () => void;
  onClose: () => void;
  discovery: {
    cursor: string | null;
    loading: boolean;
    loadingMore: boolean;
    error: boolean;
  };
  onMore: () => void;
  onRetry: () => void;
  searchLabel: string;
}

export function BatchSearchSelect<T extends Choice>({
  label, allLabel, language, value, options, search,
  onSearchChange, onSelect, onOpen, onClose,
  discovery, onMore, onRetry, searchLabel,
}: Props<T>) {
  const [open, setOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const selected = options.find(item => item.id === value);
  const labelText = selected
    ? selected.name
    : value === null ? allLabel : batchUiNote(language, "selectedNotShown");

  const choose = (id: number | null) => {
    onSelect(id);
    setOpen(false);
    onClose();
  };

  return (
    <Popover open={open} onOpenChange={next => {
      setOpen(next);
      if (next) {
        onSearchChange("");
        onOpen();
      } else {
        onClose();
      }
    }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          aria-haspopup="listbox"
          title={labelText}
          className="flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-semibold text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
        >
          <span className="min-w-0 truncate text-start">{labelText}</span>
          <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={4}
        className="w-[min(21rem,calc(100vw-1.5rem))] border border-slate-200 bg-white p-2 shadow-lg"
        onOpenAutoFocus={event => {
          event.preventDefault();
          searchRef.current?.focus();
        }}
      >
        <div className="relative">
          <Search aria-hidden="true" className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            ref={searchRef}
            type="search"
            value={search}
            maxLength={100}
            aria-label={searchLabel}
            placeholder={searchLabel}
            onChange={event => onSearchChange(event.target.value)}
            onKeyDown={event => {
              if (event.key === "Enter" && options.length === 1 && search.trim().length >= 2) {
                event.preventDefault();
                choose(options[0].id);
              }
            }}
            className="h-9 w-full rounded-lg border border-slate-200 bg-white ps-8 pe-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
          />
        </div>
        <div role="listbox" aria-label={label} className="mt-1 max-h-64 overflow-y-auto p-0.5">
          <button
            role="option"
            aria-selected={value === null}
            type="button"
            onClick={() => choose(null)}
            className="flex w-full items-center justify-between rounded-lg px-2 py-2 text-start text-xs hover:bg-slate-100 focus-visible:bg-slate-100"
          >
            <span>{allLabel}</span>
            {value === null ? <Check aria-hidden="true" className="h-3.5 w-3.5" /> : null}
          </button>
          {options.map(item => (
            <button
              key={item.id}
              role="option"
              aria-selected={value === item.id}
              data-choice-id={item.id}
              type="button"
              onClick={() => choose(item.id)}
              className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-start text-xs hover:bg-slate-100 focus-visible:bg-slate-100"
            >
              <span className="min-w-0 break-words">{item.name}{item.sku ? ` · ${item.sku}` : ""}</span>
              {value === item.id ? <Check aria-hidden="true" className="h-3.5 w-3.5 shrink-0" /> : null}
            </button>
          ))}
        </div>
        {search.trim().length === 1 ? <p className="px-2 py-1 text-xs text-slate-500">{batchUiNote(language, "searchMin")}</p> : null}
        {discovery.loading ? <p role="status" className="px-2 py-1 text-xs text-slate-500">{batchUiNote(language, "loading")}</p> : null}
        {discovery.error ? (
          <button type="button" onClick={onRetry} className="px-2 py-1 text-xs font-semibold text-red-700 underline">{batchUiNote(language, "retry")}</button>
        ) : null}
        {discovery.cursor ? (
          <button type="button" disabled={discovery.loadingMore} onClick={onMore} className="px-2 py-1 text-xs font-semibold text-slate-700 underline disabled:opacity-50">{batchUiNote(language, "loadMore")}</button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
