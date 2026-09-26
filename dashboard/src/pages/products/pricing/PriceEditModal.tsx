import {
  Calculator,
  CircleDollarSign,
  PackageOpen,
} from "lucide-react";
import type {
  RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import type {
  PriceFieldError,
} from "@/pages/products/pricing/types";

type Props = {
  product: SimpleProduct | null;
  saving: boolean;
  online: boolean;
  packagePrice: string;
  unitPrice: string;
  fieldError: PriceFieldError | null;
  independentPrices: boolean;
  derivedPackagePrice: string | null;
  derivedUnitPrice: string | null;
  packagePriceRef: RefObject<HTMLInputElement | null>;
  unitPriceRef: RefObject<HTMLInputElement | null>;
  onClose: () => void;
  onCancel: () => void;
  onSubmit: () => void;
  onPackagePriceChange: (
    value: string,
  ) => void;
  onUnitPriceChange: (
    value: string,
  ) => void;
};

type PriceInputProps = {
  label: string;
  currencyCode: string;
  value: string;
  fieldName:
    | "packagePrice"
    | "unitPrice";
  fieldError: PriceFieldError | null;
  inputRef: RefObject<HTMLInputElement | null>;
  errorId: string;
  onChange: (
    value: string,
  ) => void;
  icon:
    | "package"
    | "unit";
};

function PriceInput({
  label,
  currencyCode,
  value,
  fieldName,
  fieldError,
  inputRef,
  errorId,
  onChange,
  icon,
}: PriceInputProps) {
  const Icon =
    icon === "package"
      ? PackageOpen
      : CircleDollarSign;
  const invalid =
    fieldError?.field ===
    fieldName;

  return (
    <label className="min-w-0 rounded-xl border border-slate-200 bg-white p-3">
      <span className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-xs font-black text-slate-700">
          <Icon className="h-4 w-4 shrink-0 text-slate-400" />
          <span className="truncate">
            {label}
          </span>
        </span>
        <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-black text-slate-500">
          {currencyCode}
        </span>
      </span>

      <input
        ref={inputRef}
        inputMode="decimal"
        value={value}
        onChange={(event) =>
          onChange(
            event.target.value,
          )
        }
        aria-invalid={
          invalid
            ? "true"
            : undefined
        }
        aria-describedby={
          invalid
            ? errorId
            : undefined
        }
        className="mt-2 h-10 w-full rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm font-black tabular-nums text-slate-950 outline-none transition focus:border-slate-400 focus:bg-white focus:ring-2 focus:ring-slate-100"
      />

      {invalid ? (
        <span
          id={errorId}
          role="alert"
          className="mt-1.5 block text-[10px] font-bold leading-4 text-rose-700"
        >
          {fieldError.message}
        </span>
      ) : null}
    </label>
  );
}

export function PriceEditModal({
  product,
  saving,
  online,
  packagePrice,
  unitPrice,
  fieldError,
  independentPrices,
  derivedPackagePrice,
  derivedUnitPrice,
  packagePriceRef,
  unitPriceRef,
  onClose,
  onCancel,
  onSubmit,
  onPackagePriceChange,
  onUnitPriceChange,
}: Props) {
  const { t } = useTranslation();

  const hasPackage =
    Boolean(
      product?.package_uom_code,
    );
  const hasPreview =
    product !== null &&
    derivedUnitPrice !== null &&
    (
      !hasPackage ||
      derivedPackagePrice !== null
    );

  return (
    <Modal
      isOpen={product !== null}
      onClose={onClose}
      title={`${t(
        "products.editPrice"
      )} — ${product?.name ?? ""}`}
      maxWidth="max-w-xl"
      footer={
        <>
          <button
            type="button"
            disabled={saving}
            onClick={onCancel}
            className="px-4 py-2 text-sm font-bold text-slate-600"
          >
            {t(
              "common.cancel"
            )}
          </button>
          <button
            type="button"
            disabled={
              saving ||
              !online
            }
            onClick={onSubmit}
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
          >
            {t(
              "products.savePrice"
            )}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-xl border border-sky-100 bg-sky-50/70 px-3 py-2.5">
          <Calculator className="mt-0.5 h-4 w-4 shrink-0 text-sky-700" />
          <p className="text-[10px] font-bold leading-4 text-sky-900">
            {t(
              "products.priceHelp"
            )}
          </p>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2">
          {hasPackage &&
          product ? (
            <PriceInput
              label={t(
                "products.packagePrice"
              )}
              currencyCode={
                product.currency_code
              }
              value={packagePrice}
              fieldName="packagePrice"
              fieldError={
                fieldError
              }
              inputRef={
                packagePriceRef
              }
              errorId="edit-package-price-error"
              onChange={
                onPackagePriceChange
              }
              icon="package"
            />
          ) : null}

          {product ? (
            <PriceInput
              label={t(
                "products.unitPrice"
              )}
              currencyCode={
                product.currency_code
              }
              value={unitPrice}
              fieldName="unitPrice"
              fieldError={
                fieldError
              }
              inputRef={
                unitPriceRef
              }
              errorId="edit-unit-price-error"
              onChange={
                onUnitPriceChange
              }
              icon="unit"
            />
          ) : null}
        </div>

        {hasPreview ? (
          <div
            className={`rounded-xl border px-3 py-2.5 ${
              independentPrices
                ? "border-amber-200 bg-amber-50/70"
                : "border-emerald-200 bg-emerald-50/70"
            }`}
          >
            <p
              className={`text-[10px] font-black leading-4 ${
                independentPrices
                  ? "text-amber-900"
                  : "text-emerald-800"
              }`}
            >
              {t(
                independentPrices
                  ? "products.independentPrices"
                  : hasPackage
                    ? "products.derivedPrice"
                    : "products.unitPrice"
              )}
            </p>

            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-bold tabular-nums text-slate-600">
              {hasPackage &&
              derivedPackagePrice !==
                null ? (
                <span>
                  {t(
                    "products.packagePrice"
                  )}
                  :{" "}
                  <strong className="font-black text-slate-900">
                    {derivedPackagePrice}{" "}
                    {product?.currency_code}
                  </strong>
                </span>
              ) : null}

              {derivedUnitPrice !==
              null ? (
                <span>
                  {t(
                    "products.unitPrice"
                  )}
                  :{" "}
                  <strong className="font-black text-slate-900">
                    {derivedUnitPrice}{" "}
                    {product?.currency_code}
                  </strong>
                </span>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
