import type {
  RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  PackageUom,
} from "@/pages/products/contracts";
import { ProductPackagingHelp } from "@/pages/products/shared/ProductPackagingHelp";
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
  const { t, i18n } =
    useTranslation();
  const packageLabel = t(
    `uom.${draft.package_uom_code}`
  );

  return (
    <section className="border-b border-slate-200 bg-slate-50/60 px-4 py-4 sm:px-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="h-2 w-2 rounded-full bg-amber-400"
          />
          <h3 className="text-xs font-black text-slate-900">
            {t(
              "products.packagingModeLabel"
            )}
          </h3>
          <ProductPackagingHelp compact />
        </div>

        <div
          role="group"
          aria-label={t(
            "products.packagingModeLabel"
          )}
          className="grid w-full grid-cols-2 rounded-xl border border-slate-200 bg-white p-1 sm:w-auto"
        >
          <button
            type="button"
            aria-pressed={draft.has_package}
            onClick={() =>
              onHasPackageChange(true)
            }
            className={`min-h-9 rounded-lg px-4 text-[11px] font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
              draft.has_package
                ? "bg-amber-400 text-slate-950 shadow-sm"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            {t(
              "products.packagingMode.withPackage",
              {
                package:
                  packageLabel,
              }
            )}
          </button>
          <button
            type="button"
            aria-pressed={!draft.has_package}
            onClick={() =>
              onHasPackageChange(false)
            }
            className={`min-h-9 rounded-lg px-4 text-[11px] font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
              !draft.has_package
                ? "bg-slate-900 text-white shadow-sm"
                : "text-slate-500 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            {t(
              "products.packagingMode.unitOnly"
            )}
          </button>
        </div>
      </div>

      <div
        className={`mt-3 grid gap-3 sm:grid-cols-2 ${
          draft.has_package
            ? "lg:grid-cols-4"
            : ""
        }`}
      >
        {draft.has_package ? (
          packageUomsLoading ? (
            <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs font-bold text-slate-500">
              {t("common.loading")}
            </div>
          ) : packageUomsError ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-3 sm:col-span-2"
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
                "products.quickCreate.packageTypeLabel"
              )}
              <Select
                dir={i18n.dir()}
                value={
                  draft.package_uom_code
                }
                onValueChange={
                  onPackageUomChange
                }
              >
                <SelectTrigger className="mt-1.5 h-10 rounded-xl border-slate-200 bg-white text-start font-bold focus:ring-slate-200">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  dir={i18n.dir()}
                  position="popper"
                  side="bottom"
                  align="start"
                  sideOffset={6}
                  avoidCollisions={false}
                  className="z-[70] rounded-xl border-slate-200"
                >
                  {packageUoms.map(
                    (uom) => (
                      <SelectItem
                        key={uom.code}
                        value={uom.code}
                        className="text-start font-bold"
                      >
                        {t(
                          `uom.${uom.code}`
                        )}
                      </SelectItem>
                    )
                  )}
                </SelectContent>
              </Select>
            </label>
          )
        ) : null}

        {draft.has_package ? (
          <label className="text-xs font-black text-slate-600">
            {t(
              "products.quickCreate.unitsPerPackage",
              {
                package:
                  packageLabel,
              }
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
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
        ) : null}

        {draft.has_package ? (
          <label className="text-xs font-black text-slate-600">
            {t(
              "products.quickCreate.packagePrice",
              {
                package:
                  packageLabel,
              }
            )}
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
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          {t("products.unitPrice")}
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
            className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition placeholder:text-sm placeholder:font-normal placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
        <p className="mt-2 text-[10px] font-bold leading-4 text-emerald-700">
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
