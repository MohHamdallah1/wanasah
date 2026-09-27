import {
  useEffect,
  useState,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { ProductFamilyCombobox } from "@/pages/products/family/ProductFamilyCombobox";
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
  const { t } =
    useTranslation();
  const [
    familySearchInput,
    setFamilySearchInput,
  ] = useState("");

  useEffect(() => {
    if (
      draft.family_mode !==
      "existing"
    ) {
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
              <div className="mt-2">
                <ProductFamilyCombobox
                  selectedName={
                    draft.family_id
                      ? draft.family
                      : ""
                  }
                  searchValue={
                    familySearchInput
                  }
                  options={
                    familyOptions
                  }
                  placeholder={t(
                    "products.familyExistingPlaceholder"
                  )}
                  clearLabel={t(
                    "products.quickCreate.clearFamilySearch"
                  )}
                  emptyLabel={t(
                    "products.noMatchingFamilies"
                  )}
                  loading={
                    familyOptionsLoading
                  }
                  loadingLabel={t(
                    "common.loading"
                  )}
                  error={
                    familyOptionsError
                  }
                  errorLabel={t(
                    "products.errors.familiesLoad"
                  )}
                  retryLabel={t(
                    "common.retry"
                  )}
                  onRetry={
                    onRetryFamilyOptions
                  }
                  onSearchChange={(
                    value
                  ) => {
                    setFamilySearchInput(
                      value
                    );
                    onFamilyChange(
                      value,
                      null
                    );
                  }}
                  onSelect={(
                    family
                  ) => {
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
                  }}
                  onClear={() =>
                    onFamilyChange(
                      "",
                      null
                    )
                  }
                  formatOptionMeta={(
                    family
                  ) =>
                    t(
                      "products.variantCount",
                      {
                        count:
                          family.variant_count,
                      }
                    )
                  }
                  inputClassName="h-10 w-full rounded-xl border border-slate-200 bg-white pe-10 ps-3 text-sm font-bold text-slate-900 outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                />
              </div>

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
