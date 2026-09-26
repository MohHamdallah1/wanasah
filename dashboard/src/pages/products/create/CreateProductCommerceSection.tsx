import type {
  RefObject,
} from "react";
import {
  PackageOpen,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  PackageUom,
} from "@/pages/products/contracts";
import type {
  CreateFieldError,
  ProductDraft,
} from "@/pages/products/create/types";

type Props = {
  draft: ProductDraft;
  createFieldError: CreateFieldError | null;
  packageUoms: PackageUom[];
  packageUomsLoading: boolean;
  packageUomsError: boolean;
  draftDerived: {
    independent: boolean;
  } | null;
  createUnitsRef: RefObject<HTMLInputElement>;
  createPackagePriceRef: RefObject<HTMLInputElement>;
  createUnitPriceRef: RefObject<HTMLInputElement>;
  onHasPackageChange: (checked: boolean) => void;
  onRetryPackageUoms: () => void;
  onPackageUomChange: (value: string) => void;
  onUnitsPerPackageChange: (value: string) => void;
  onPackagePriceChange: (value: string) => void;
  onUnitPriceChange: (value: string) => void;
};

export function CreateProductCommerceSection({
  draft,
  createFieldError,
  packageUoms,
  packageUomsLoading,
  packageUomsError,
  draftDerived,
  createUnitsRef,
  createPackagePriceRef,
  createUnitPriceRef,
  onHasPackageChange,
  onRetryPackageUoms,
  onPackageUomChange,
  onUnitsPerPackageChange,
  onPackagePriceChange,
  onUnitPriceChange,
}: Props) {
  const { t } = useTranslation();

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-400 text-slate-950">
            <PackageOpen className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-black text-slate-950">
              {draft.has_package
                ? t(
                    "products.hasOuterPackage"
                  )
                : t(
                    "products.noOuterPackage"
                  )}
            </h3>
            <p className="mt-0.5 text-[11px] font-semibold text-slate-500">
              {t("products.unitPrice")}
            </p>
          </div>
        </div>

        <label className="inline-flex shrink-0 cursor-pointer items-center gap-2 text-[11px] font-black text-slate-600">
          <input
            type="checkbox"
            checked={draft.has_package}
            onChange={(event) =>
              onHasPackageChange(
                event.target.checked
              )
            }
            className="h-4 w-4"
          />
          {t("products.packageType")}
        </label>
      </div>

      {draft.has_package ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {packageUomsLoading ? (
            <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
              {t("common.loading")}
            </div>
          ) : packageUomsError ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 rounded-xl bg-rose-50 p-3"
            >
              <span className="text-xs font-bold text-rose-800">
                {t(
                  "products.errors.packageUomsLoad"
                )}
              </span>
              <button
                type="button"
                onClick={() =>
                  onRetryPackageUoms()
                }
                className="shrink-0 text-xs font-black text-rose-800"
              >
                {t("common.retry")}
              </button>
            </div>
          ) : (
            <label className="text-xs font-black text-slate-600">
              {t(
                "products.packageType"
              )}
              <select
                value={
                  draft.package_uom_code
                }
                onChange={(event) =>
                  onPackageUomChange(
                    event.target.value
                  )
                }
                className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              >
                {packageUoms.map(
                  (uom) => (
                    <option
                      key={uom.code}
                      value={uom.code}
                    >
                      {t(
                        `uom.${uom.code}`
                      )}
                    </option>
                  )
                )}
              </select>
            </label>
          )}

          <label className="text-xs font-black text-slate-600">
            {t(
              "products.unitsPerPackage"
            )}
            <input
              ref={createUnitsRef}
              inputMode="numeric"
              value={
                draft.units_per_package
              }
              onChange={(event) =>
                onUnitsPerPackageChange(
                  event.target.value
                )
              }
              aria-invalid={
                createFieldError?.field ===
                "units"
                  ? "true"
                  : undefined
              }
              aria-describedby={
                createFieldError?.field ===
                "units"
                  ? "product-units-error"
                  : undefined
              }
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-black outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            />
            {createFieldError?.field ===
            "units" ? (
              <span
                id="product-units-error"
                role="alert"
                className="mt-1 block text-[11px] font-bold text-rose-700"
              >
                {createFieldError.message}
              </span>
            ) : null}
          </label>
        </div>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {draft.has_package ? (
          <label className="text-xs font-black text-slate-600">
            {t(
              "products.packagePrice"
            )}{" "}
            <span className="font-bold text-slate-400">
              {t("common.optional")}
            </span>
            <input
              ref={createPackagePriceRef}
              inputMode="decimal"
              value={
                draft.package_price
              }
              onChange={(event) =>
                onPackagePriceChange(
                  event.target.value
                )
              }
              placeholder={t(
                "products.packagePricePlaceholder"
              )}
              aria-invalid={
                createFieldError?.field ===
                "packagePrice"
                  ? "true"
                  : undefined
              }
              aria-describedby={
                createFieldError?.field ===
                "packagePrice"
                  ? "product-package-price-error"
                  : undefined
              }
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-black outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            />
            {createFieldError?.field ===
            "packagePrice" ? (
              <span
                id="product-package-price-error"
                role="alert"
                className="mt-1 block text-[11px] font-bold text-rose-700"
              >
                {createFieldError.message}
              </span>
            ) : null}
          </label>
        ) : null}

        <label className="text-xs font-black text-slate-600">
          {t("products.unitPrice")}{" "}
          {draft.has_package ? (
            <span className="font-bold text-slate-400">
              {t("common.optional")}
            </span>
          ) : null}
          <input
            ref={createUnitPriceRef}
            inputMode="decimal"
            value={draft.unit_price}
            onChange={(event) =>
              onUnitPriceChange(
                event.target.value
              )
            }
            placeholder={t(
              "products.unitPricePlaceholder"
            )}
            aria-invalid={
              createFieldError?.field ===
              "unitPrice"
                ? "true"
                : undefined
            }
            aria-describedby={
              createFieldError?.field ===
              "unitPrice"
                ? "product-unit-price-error"
                : undefined
            }
            className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-black outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          />
          {createFieldError?.field ===
          "unitPrice" ? (
            <span
              id="product-unit-price-error"
              role="alert"
              className="mt-1 block text-[11px] font-bold text-rose-700"
            >
              {createFieldError.message}
            </span>
          ) : null}
        </label>
      </div>

      {draftDerived ? (
        <p className="mt-3 border-t border-slate-100 pt-3 text-[10px] font-bold leading-4 text-emerald-700">
          {draft.has_package &&
          draftDerived.independent
            ? t(
                "products.independentPrices"
              )
            : draft.has_package
              ? t(
                  "products.derivedPrice"
                )
              : t(
                  "products.unitPrice"
                )}
        </p>
      ) : null}
    </section>
  );
}
