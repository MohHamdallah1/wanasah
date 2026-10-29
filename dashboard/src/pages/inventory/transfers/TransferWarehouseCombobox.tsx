import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronsUpDown, X } from "lucide-react";
import type { TransferWarehouse } from "./draftStorage";

type Props = {
  label: string;
  selected: TransferWarehouse | null;
  options: TransferWarehouse[];
  search: string;
  loading: boolean;
  error: unknown;
  disabled?: boolean;
  placeholder: string;
  emptyLabel: string;
  loadingLabel: string;
  retryLabel: string;
  clearLabel: string;
  onSearchChange: (value: string) => void;
  onSelect: (value: string) => void;
  onRetry: () => void;
};

export function TransferWarehouseCombobox({
  label,
  selected,
  options,
  search,
  loading,
  error,
  disabled = false,
  placeholder,
  emptyLabel,
  loadingLabel,
  retryLabel,
  clearLabel,
  onSearchChange,
  onSelect,
  onRetry,
}: Props) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    const update = () => {
      const input = inputRef.current;
      if (!input) return;
      const rect = input.getBoundingClientRect();
      const gap = 6;
      setPosition({
        top: rect.bottom + gap,
        left: rect.left,
        width: rect.width,
        maxHeight: Math.max(120, Math.min(280, window.innerHeight - rect.bottom - gap - 16)),
      });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (!rootRef.current?.contains(target) && !listRef.current?.contains(target)) {
        setOpen(false);
        onSearchChange("");
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [onSearchChange, open]);

  const select = (warehouse: TransferWarehouse) => {
    onSelect(String(warehouse.id));
    onSearchChange("");
    setOpen(false);
  };

  const listbox = open && position && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={listRef}
          id={id}
          role="listbox"
          style={{ top: position.top, left: position.left, width: position.width, maxHeight: position.maxHeight }}
          className="fixed z-[120] overflow-y-auto rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl"
        >
          {loading ? (
            <div className="px-3 py-5 text-center text-xs font-bold text-slate-400">{loadingLabel}</div>
          ) : error ? (
            <div className="px-3 py-4 text-center">
              <p className="text-xs font-bold text-red-700">{emptyLabel}</p>
              <button type="button" onClick={onRetry} className="mt-2 text-xs font-black text-blue-700 underline">{retryLabel}</button>
            </div>
          ) : options.length ? (
            options.map((warehouse) => (
              <button
                key={warehouse.id}
                type="button"
                role="option"
                aria-selected={warehouse.id === selected?.id}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(warehouse)}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-start text-xs font-bold text-slate-700 hover:bg-blue-50 hover:text-slate-950"
              >
                <span className="min-w-0 flex-1 truncate">{warehouse.name}</span>
                <span className="shrink-0 text-[10px] font-semibold text-slate-400">{warehouse.code}</span>
              </button>
            ))
          ) : (
            <div className="px-3 py-5 text-center text-xs font-bold text-slate-400">{emptyLabel}</div>
          )}
        </div>,
        document.body,
      )
    : null;

  const selectedLabel = selected ? `${selected.name} (${selected.code})` : "";

  return (
    <>
      <label className="block space-y-1 text-xs font-black text-slate-700">
        <span>{label}</span>
        <div ref={rootRef} className="relative">
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-label={label}
            aria-autocomplete="list"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={id}
            disabled={disabled}
            value={open ? search : selectedLabel}
            placeholder={placeholder}
            maxLength={100}
            onClick={() => {
              if (!disabled) setOpen(true);
            }}
            onChange={(event) => {
              if (!open) setOpen(true);
              onSearchChange(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setOpen(false);
                onSearchChange("");
                return;
              }
              if (!open && !disabled && (event.key === "ArrowDown" || event.key === "Enter")) {
                event.preventDefault();
                setOpen(true);
              }
            }}
            className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 pe-16 text-sm font-bold text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-60"
          />
          <ChevronsUpDown className="pointer-events-none absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          {selected ? (
            <button
              type="button"
              aria-label={clearLabel}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                onSelect("");
                onSearchChange("");
                setOpen(true);
                queueMicrotask(() => inputRef.current?.focus());
              }}
              className="absolute end-9 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </label>
      {listbox}
    </>
  );
}
