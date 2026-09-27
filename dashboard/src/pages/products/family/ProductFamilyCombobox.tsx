import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { X } from "lucide-react";

import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import type {
  ProductFamily,
} from "@/pages/products/contracts";

type Props = {
  selectedName: string;
  searchValue: string;
  options: ProductFamily[];
  placeholder: string;
  clearLabel: string;
  emptyLabel: string;
  loading?: boolean;
  loadingLabel?: string;
  error?: boolean;
  errorLabel?: string;
  retryLabel?: string;
  onRetry?: () => void;
  allOptionLabel?: string;
  onSelectAll?: () => void;
  onSearchChange: (value: string) => void;
  onSelect: (family: ProductFamily) => void;
  onClear: () => void;
  formatOptionMeta?: (
    family: ProductFamily,
  ) => string;
  inputClassName: string;
};

export function ProductFamilyCombobox({
  selectedName,
  searchValue,
  options,
  placeholder,
  clearLabel,
  emptyLabel,
  loading = false,
  loadingLabel,
  error = false,
  errorLabel,
  retryLabel,
  onRetry,
  allOptionLabel,
  onSelectAll,
  onSearchChange,
  onSelect,
  onClear,
  formatOptionMeta,
  inputClassName,
}: Props) {
  const [
    open,
    setOpen,
  ] = useState(false);
  const [
    activeIndex,
    setActiveIndex,
  ] = useState(-1);
  const inputRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const optionRefs =
    useRef<
      Array<HTMLButtonElement | null>
    >([]);
  const listboxId = useId();

  const hasAllOption =
    Boolean(
      allOptionLabel &&
        onSelectAll
    );
  const itemCount =
    options.length +
    (hasAllOption ? 1 : 0);
  const displayValue =
    searchValue || selectedName;

  useEffect(() => {
    setActiveIndex(-1);
  }, [
    searchValue,
    options,
  ]);

  useEffect(() => {
    if (
      activeIndex < 0
    ) {
      return;
    }
    optionRefs.current[
      activeIndex
    ]?.scrollIntoView?.({
      block: "nearest",
    });
  }, [activeIndex]);

  const selectIndex = (
    index: number,
  ) => {
    if (
      hasAllOption &&
      index === 0
    ) {
      onSelectAll?.();
      setOpen(false);
      setActiveIndex(-1);
      return;
    }

    const option =
      options[
        index -
          (hasAllOption ? 1 : 0)
      ];
    if (!option) {
      return;
    }

    onSelect(option);
    setOpen(false);
    setActiveIndex(-1);
  };

  const handleKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    if (
      event.key === "ArrowDown"
    ) {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      }
      setActiveIndex(
        (current) =>
          itemCount === 0
            ? -1
            : current < 0
              ? 0
              : Math.min(
                  current + 1,
                  itemCount - 1
                )
      );
      return;
    }

    if (
      event.key === "ArrowUp"
    ) {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      }
      setActiveIndex(
        (current) =>
          itemCount === 0
            ? -1
            : current < 0
              ? itemCount - 1
              : Math.max(
                  current - 1,
                  0
                )
      );
      return;
    }

    if (
      event.key === "Enter"
    ) {
      if (!open) {
        event.preventDefault();
        setOpen(true);
        return;
      }
      if (activeIndex >= 0) {
        event.preventDefault();
        selectIndex(
          activeIndex
        );
      }
      return;
    }

    if (
      event.key === "Escape" &&
      open
    ) {
      event.preventDefault();
      setOpen(false);
      setActiveIndex(-1);
    }
  };

  const activeId =
    activeIndex >= 0
      ? `${listboxId}-option-${activeIndex}`
      : undefined;

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
    >
      <div className="relative">
        <PopoverAnchor asChild>
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={
              listboxId
            }
            aria-activedescendant={
              activeId
            }
            value={displayValue}
            maxLength={100}
            onClick={(event) => {
              if (
                selectedName &&
                !searchValue
              ) {
                event.currentTarget.select();
              }
              setOpen(true);
            }}
            onChange={(event) => {
              onSearchChange(
                event.target.value
              );
              setOpen(true);
            }}
            onKeyDown={
              handleKeyDown
            }
            placeholder={
              placeholder
            }
            className={
              inputClassName
            }
          />
        </PopoverAnchor>

        {displayValue ? (
          <button
            type="button"
            onMouseDown={(event) =>
              event.preventDefault()
            }
            onClick={() => {
              onClear();
              setOpen(true);
              queueMicrotask(() =>
                inputRef.current?.focus()
              );
            }}
            aria-label={clearLabel}
            className="absolute end-1.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      <PopoverContent
        side="bottom"
        align="start"
        sideOffset={5}
        avoidCollisions={false}
        onOpenAutoFocus={(event) =>
          event.preventDefault()
        }
        onCloseAutoFocus={(event) =>
          event.preventDefault()
        }
        onInteractOutside={(event) => {
          if (
            event.target ===
            inputRef.current
          ) {
            event.preventDefault();
          }
        }}
        className="z-[70] w-[var(--radix-popover-anchor-width)] overflow-hidden rounded-xl border-slate-200 bg-white p-1.5 shadow-xl"
      >
        <div
          id={listboxId}
          role="listbox"
          className="max-h-64 overflow-y-auto"
        >
          {loading ? (
            <div className="px-3 py-6 text-center text-xs font-bold text-slate-400">
              {loadingLabel}
            </div>
          ) : error ? (
            <div className="px-3 py-5 text-center">
              <p className="text-xs font-bold text-rose-700">
                {errorLabel}
              </p>
              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-2 text-xs font-black text-slate-900 underline underline-offset-4"
                >
                  {retryLabel}
                </button>
              ) : null}
            </div>
          ) : (
            <>
              {hasAllOption ? (
                <button
                  ref={(node) => {
                    optionRefs.current[
                      0
                    ] = node;
                  }}
                  id={`${listboxId}-option-0`}
                  type="button"
                  role="option"
                  aria-selected={
                    activeIndex === 0
                  }
                  onMouseDown={(event) =>
                    event.preventDefault()
                  }
                  onMouseEnter={() =>
                    setActiveIndex(
                      0
                    )
                  }
                  onClick={() =>
                    selectIndex(0)
                  }
                  className={`flex w-full items-center rounded-lg px-3 py-2.5 text-start text-xs font-bold transition ${
                    activeIndex === 0
                      ? "bg-amber-100 text-amber-950"
                      : "text-slate-700 hover:bg-amber-50 hover:text-slate-950"
                  }`}
                >
                  {allOptionLabel}
                </button>
              ) : null}

              {options.map(
                (family, optionIndex) => {
                  const index =
                    optionIndex +
                    (hasAllOption
                      ? 1
                      : 0);
                  return (
                    <button
                      key={family.id}
                      ref={(node) => {
                        optionRefs.current[
                          index
                        ] = node;
                      }}
                      id={`${listboxId}-option-${index}`}
                      type="button"
                      role="option"
                      aria-selected={
                        activeIndex ===
                        index
                      }
                      onMouseDown={(
                        event
                      ) =>
                        event.preventDefault()
                      }
                      onMouseEnter={() =>
                        setActiveIndex(
                          index
                        )
                      }
                      onClick={() =>
                        selectIndex(
                          index
                        )
                      }
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-start text-xs transition ${
                        activeIndex ===
                        index
                          ? "bg-amber-100 text-amber-950"
                          : "text-slate-700 hover:bg-amber-50 hover:text-slate-950"
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate font-bold">
                        {family.name}
                      </span>
                      {formatOptionMeta ? (
                        <span className="shrink-0 text-[10px] font-semibold text-slate-400">
                          {formatOptionMeta(
                            family
                          )}
                        </span>
                      ) : null}
                    </button>
                  );
                }
              )}

              {options.length === 0 &&
              !hasAllOption ? (
                <div className="px-3 py-5 text-center text-xs font-bold text-slate-400">
                  {emptyLabel}
                </div>
              ) : null}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
