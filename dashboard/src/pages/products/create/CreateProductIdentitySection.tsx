import {
  useEffect,
  useState,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
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

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="mb-4 min-w-0">
        <h3 className="text-sm font-black text-slate-950">
          {t("products.productName")}
        </h3>
        <p className="mt-0.5 text-[11px] font-semibold text-slate-500">
          {t("products.family")}
          {" · "}
          {t("common.optional")}
        </p>
      </div>

      <div className="space-y-4">
        <label className="block text-xs font-black text-slate-600">
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
            className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-black text-slate-950 outline-none transition placeholder:font-semibold placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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

        <fieldset>
          <legend className="text-xs font-black text-slate-600">
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
            className="mt-1.5 inline-flex max-w-full rounded-xl bg-slate-100 p-1"
          >
            {(
              [
                "none",
                "existing",
                "new",
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
                className={`min-h-8 rounded-lg px-3 text-[11px] font-black transition ${
                  draft.family_mode === mode
                    ? "bg-white text-slate-950 shadow-sm"
                    : "text-slate-500 hover:text-slate-800"
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
                    setFamilySearchInput("");
                    onFamilySearchChange("");
                  }
                }}
              >
                <PopoverTrigger asChild>
                  <button
                    type="button"
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
                    className="mt-2 flex h-10 w-full items-center rounded-xl border border-slate-200 bg-white px-3 text-start text-sm font-bold text-slate-900 outline-none transition focus-visible:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-100"
                  >
                    <span
                      className={
                        draft.family_id
                          ? "min-w-0 truncate"
                          : "min-w-0 truncate text-slate-400"
                      }
                    >
                      {draft.family_id
                        ? draft.family
                        : t(
                            "products.familyExistingPlaceholder"
                          )}
                    </span>
                  </button>
                </PopoverTrigger>

                <PopoverContent
                  dir={i18n.dir()}
                  side="bottom"
                  align="start"
                  sideOffset={6}
                  className="w-[var(--radix-popover-trigger-width)] overflow-hidden rounded-xl border-slate-200 bg-white p-0 shadow-xl"
                >
                  <Command
                    dir={i18n.dir()}
                    shouldFilter={false}
                  >
                    <CommandInput
                      ref={createFamilyRef}
                      autoFocus
                      value={familySearchInput}
                      onValueChange={
                        setFamilySearchInput
                      }
                      placeholder={t(
                        "products.familyExistingPlaceholder"
                      )}
                      className="font-normal"
                    />

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
                                  setFamilyPickerOpen(
                                    false
                                  );
                                  setFamilySearchInput(
                                    ""
                                  );
                                  onFamilySearchChange(
                                    ""
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
                className="mt-2 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
