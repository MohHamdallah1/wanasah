import {
  useEffect,
  useState,
  type RefObject,
} from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import type {
  ProductFamily,
} from "@/pages/products/contracts";
import type {
  CreateFieldError,
  ProductDraft,
  ProductFamilyMode,
} from "@/pages/products/create/types";

type Props = {
  draft: ProductDraft;
  createFieldError: CreateFieldError | null;
  familyOptions: ProductFamily[];
  familyOptionsLoading: boolean;
  familyOptionsError: boolean;
  createNameRef: RefObject<HTMLInputElement>;
  createFamilyRef: RefObject<HTMLInputElement>;
  onNameChange: (value: string) => void;
  onFamilyModeChange: (
    mode: ProductFamilyMode,
  ) => void;
  onFamilyChange: (
    value: string,
    familyId?: number | null,
  ) => void;
  onFamilySearchChange: (
    value: string,
  ) => void;
  onRetryFamilyOptions: () => void;
};

export function CreateProductIdentitySection({
  draft,
  createFieldError,
  familyOptions,
  familyOptionsLoading,
  familyOptionsError,
  createNameRef,
  createFamilyRef,
  onNameChange,
  onFamilyModeChange,
  onFamilyChange,
  onFamilySearchChange,
  onRetryFamilyOptions,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const [
    familyPickerOpen,
    setFamilyPickerOpen,
  ] = useState(false);
  const [
    familySearchInput,
    setFamilySearchInput,
  ] = useState("");

  useEffect(() => {
    if (
      draft.family_mode !==
      "existing"
    ) {
      setFamilyPickerOpen(false);
      setFamilySearchInput("");
      onFamilySearchChange("");
      return;
    }

    const timer =
      window.setTimeout(() => {
        onFamilySearchChange(
          familySearchInput
            .trim()
            .slice(0, 100),
        );
      }, 250);

    return () =>
      window.clearTimeout(timer);
  }, [
    draft.family_mode,
    familySearchInput,
    onFamilySearchChange,
  ]);

  const familyInputValue =
    familyPickerOpen
      ? familySearchInput
      : draft.family;

  const clearFamilySearch = () => {
    setFamilySearchInput("");
    onFamilySearchChange("");
    onFamilyChange("", null);
    setFamilyPickerOpen(true);
    queueMicrotask(() =>
      createFamilyRef.current?.focus()
    );
  };

  return (
    <section className="border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(340px,0.8fr)]">
        <label className="block min-w-0 text-xs font-black text-slate-700">
          {t("products.productName")}
          <input
            ref={createNameRef}
            value={draft.name}
            onChange={(event) =>
              onNameChange(event.target.value)
            }
            placeholder={t(
              "products.productNamePlaceholder"
            )}
            aria-invalid={
              createFieldError?.field === "name"
                ? "true"
                : undefined
            }
            aria-describedby={
              createFieldError?.field === "name"
                ? "product-name-error"
                : undefined
            }
            className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-950 outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          />
          {createFieldError?.field === "name" ? (
            <span
              id="product-name-error"
              role="alert"
              className="mt-1 block text-[11px] font-bold text-rose-700"
            >
              {createFieldError.message}
            </span>
          ) : null}
        </label>

        <fieldset className="min-w-0">
          <legend className="text-xs font-black text-slate-700">
            {t("products.family")}{" "}
            <span className="font-bold text-slate-400">
              {t("common.optional")}
            </span>
          </legend>

          <div
            role="group"
            aria-label={t(
              "products.familyModeLabel"
            )}
            className="mt-1.5 grid grid-cols-3 rounded-xl border border-slate-200 bg-slate-50 p-1"
          >
            {(
              [
                "existing",
                "new",
                "none",
              ] as const
            ).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={
                  draft.family_mode === mode
                }
                onClick={() => {
                  onFamilyModeChange(mode);
                  setFamilySearchInput("");
                  onFamilySearchChange("");
                }}
                className={`min-h-9 rounded-lg px-2 text-[11px] font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
                  draft.family_mode === mode
                    ? "bg-slate-900 text-white shadow-sm"
                    : "text-slate-500 hover:bg-white hover:text-slate-900"
                }`}
              >
                {t(
                  `products.familyMode.${mode}`
                )}
              </button>
            ))}
          </div>

          {draft.family_mode ===
          "existing" ? (
            <>
              <Popover
                open={familyPickerOpen}
                onOpenChange={(open) => {
                  setFamilyPickerOpen(open);
                  if (open) {
                    setFamilySearchInput(
                      draft.family
                    );
                    onFamilySearchChange(
                      draft.family
                    );
                  }
                }}
              >
                <div className="relative mt-2">
                  <PopoverAnchor asChild>
                    <input
                      ref={createFamilyRef}
                      value={familyInputValue}
                      onFocus={() => {
                        setFamilyPickerOpen(
                          true
                        );
                      }}
                      onChange={(event) => {
                        const value =
                          event.target.value;
                        setFamilySearchInput(
                          value
                        );
                        onFamilyChange(
                          value,
                          null
                        );
                        setFamilyPickerOpen(
                          true
                        );
                      }}
                      onKeyDown={(event) => {
                        if (
                          event.key ===
                          "ArrowDown"
                        ) {
                          setFamilyPickerOpen(
                            true
                          );
                        }
                      }}
                      placeholder={t(
                        "products.familyExistingPlaceholder"
                      )}
                      aria-expanded={
                        familyPickerOpen
                      }
                      aria-invalid={
                        createFieldError?.field ===
                        "family"
                          ? "true"
                          : undefined
                      }
                      aria-describedby={
                        createFieldError?.field ===
                        "family"
                          ? "product-family-error"
                          : undefined
                      }
                      className="h-10 w-full rounded-xl border border-slate-200 bg-white pe-10 ps-3 text-sm font-bold text-slate-900 outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                    />
                  </PopoverAnchor>

                  {familyInputValue ? (
                    <button
                      type="button"
                      onClick={
                        clearFamilySearch
                      }
                      aria-label={t(
                        "products.quickCreate.clearFamilySearch"
                      )}
                      className="absolute end-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>

                <PopoverContent
                  dir={i18n.dir()}
                  side="bottom"
                  align="start"
                  sideOffset={6}
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
                      createFamilyRef.current
                    ) {
                      event.preventDefault();
                    }
                  }}
                  className="z-[70] w-[var(--radix-popover-trigger-width)] overflow-hidden rounded-xl border-slate-200 bg-white p-1.5 shadow-xl"
                >
                  <Command
                    dir={i18n.dir()}
                    shouldFilter={false}
                  >
                    <CommandList className="max-h-64">
                      {familyOptionsLoading ? (
                        <div className="px-3 py-6 text-center text-xs font-bold text-slate-400">
                          {t("common.loading")}
                        </div>
                      ) : familyOptionsError ? (
                        <div className="px-3 py-5 text-center">
                          <p className="text-xs font-bold text-rose-700">
                            {t(
                              "products.errors.familiesLoad"
                            )}
                          </p>
                          <button
                            type="button"
                            onClick={() =>
                              onRetryFamilyOptions()
                            }
                            className="mt-2 text-xs font-black text-slate-900 underline underline-offset-4"
                          >
                            {t("common.retry")}
                          </button>
                        </div>
                      ) : familyOptions.length ? (
                        <CommandGroup>
                          {familyOptions.map(
                            (family) => (
                              <CommandItem
                                key={family.id}
                                value={family.name}
                                onSelect={() => {
                                  onFamilyChange(
                                    family.name,
                                    family.id
                                  );
                                  setFamilySearchInput(
                                    ""
                                  );
                                  onFamilySearchChange(
                                    ""
                                  );
                                  setFamilyPickerOpen(
                                    false
                                  );
                                }}
                                className="gap-3 rounded-lg px-3 py-2.5 text-start"
                              >
                                <span className="min-w-0 flex-1 truncate font-bold">
                                  {family.name}
                                </span>
                                <span className="shrink-0 text-[10px] font-semibold text-slate-400">
                                  {t(
                                    "products.variantCount",
                                    {
                                      count:
                                        family.variant_count,
                                    }
                                  )}
                                </span>
                              </CommandItem>
                            )
                          )}
                        </CommandGroup>
                      ) : (
                        <CommandEmpty>
                          {t(
                            "products.noMatchingFamilies"
                          )}
                        </CommandEmpty>
                      )}
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>

              <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
                {t(
                  "products.familyExistingHint"
                )}
              </p>
            </>
          ) : draft.family_mode ===
            "new" ? (
            <>
              <input
                ref={createFamilyRef}
                value={draft.family}
                maxLength={150}
                onChange={(event) =>
                  onFamilyChange(
                    event.target.value,
                    null
                  )
                }
                placeholder={t(
                  "products.familyNewPlaceholder"
                )}
                aria-invalid={
                  createFieldError?.field ===
                  "family"
                    ? "true"
                    : undefined
                }
                aria-describedby={
                  createFieldError?.field ===
                  "family"
                    ? "product-family-error"
                    : undefined
                }
                className="mt-2 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              />
              <p className="mt-1 text-[10px] font-semibold leading-4 text-amber-700">
                {t(
                  "products.familyNewHint"
                )}
              </p>
            </>
          ) : (
            <p className="mt-2 text-[10px] font-semibold leading-4 text-slate-400">
              {t(
                "products.familyNoneHint"
              )}
            </p>
          )}

          {createFieldError?.field ===
          "family" ? (
            <span
              id="product-family-error"
              role="alert"
              className="mt-1 block text-[11px] font-bold text-rose-700"
            >
              {createFieldError.message}
            </span>
          ) : null}
        </fieldset>
      </div>
    </section>
  );
}
