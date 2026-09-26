import type {
  RefObject,
} from "react";
import {
  Tags,
} from "lucide-react";
import { useTranslation } from "react-i18next";

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
  onRetryFamilyOptions: () => void;
};

export function CreateProductIdentitySection({
  draft,
  createFieldError,
  familyOptions,
  familyOptionsError,
  createNameRef,
  createFamilyRef,
  onNameChange,
  onFamilyModeChange,
  onFamilyChange,
  onRetryFamilyOptions,
}: Props) {
  const { t } = useTranslation();

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-950 text-white">
          <Tags className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-black text-slate-950">
            {t("products.productName")}
          </h3>
          <p className="mt-0.5 text-[11px] font-semibold text-slate-500">
            {t("products.family")}
            {" · "}
            {t("common.optional")}
          </p>
        </div>
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
            className="mt-1.5 h-11 w-full rounded-xl border border-slate-200 bg-slate-50/60 px-3 text-sm font-black text-slate-950 outline-none transition placeholder:font-semibold placeholder:text-slate-400 focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
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
                onClick={() =>
                  onFamilyModeChange(mode)
                }
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
              <input
                ref={createFamilyRef}
                list="product-family-options"
                value={draft.family}
                onChange={(event) => {
                  const value =
                    event.target.value;
                  const normalized = value
                    .trim()
                    .toLocaleLowerCase();
                  const selected =
                    familyOptions.find(
                      (family) =>
                        family.name
                          .trim()
                          .toLocaleLowerCase() ===
                        normalized
                    );
                  onFamilyChange(
                    value,
                    selected?.id ?? null
                  );
                }}
                placeholder={t(
                  "products.familyExistingPlaceholder"
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
              <datalist id="product-family-options">
                {familyOptions.map(
                  (family) => (
                    <option
                      key={family.id}
                      value={family.name}
                    />
                  )
                )}
              </datalist>
              <p className="mt-1 text-[10px] font-semibold leading-4 text-slate-500">
                {t(
                  "products.familyExistingHint"
                )}
              </p>
              {familyOptionsError ? (
                <button
                  type="button"
                  onClick={() =>
                    onRetryFamilyOptions()
                  }
                  className="mt-1 text-[11px] font-black text-rose-700"
                >
                  {t(
                    "products.errors.familiesLoad"
                  )}
                </button>
              ) : null}
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
