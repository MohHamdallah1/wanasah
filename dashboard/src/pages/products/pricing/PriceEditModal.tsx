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

export function PriceEditModal({
  product,
  saving,
  online,
  packagePrice,
  unitPrice,
  fieldError,
  independentPrices,
  packagePriceRef,
  unitPriceRef,
  onClose,
  onCancel,
  onSubmit,
  onPackagePriceChange,
  onUnitPriceChange,
}: Props) {
  const { t } = useTranslation();

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
      <div className="space-y-4">
        <p className="rounded-2xl bg-sky-50 p-3 text-xs font-bold leading-6 text-sky-900">
          {t(
            "products.priceHelp"
          )}
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          {product?.package_uom_code ? (
            <label className="text-xs font-black text-slate-600">
              {t(
                "products.packagePrice"
              )}
              <input
                ref={packagePriceRef}
                inputMode="decimal"
                value={packagePrice}
                onChange={(event) =>
                  onPackagePriceChange(
                    event.target.value
                  )
                }
                aria-invalid={
                  fieldError?.field ===
                  "packagePrice"
                    ? "true"
                    : undefined
                }
                aria-describedby={
                  fieldError?.field ===
                  "packagePrice"
                    ? "edit-package-price-error"
                    : undefined
                }
                className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
              />
              {fieldError?.field ===
              "packagePrice" ? (
                <span
                  id="edit-package-price-error"
                  role="alert"
                  className="mt-1 block text-[11px] font-bold text-rose-700"
                >
                  {fieldError.message}
                </span>
              ) : null}
            </label>
          ) : null}

          <label className="text-xs font-black text-slate-600">
            {t(
              "products.unitPrice"
            )}
            <input
              ref={unitPriceRef}
              inputMode="decimal"
              value={unitPrice}
              onChange={(event) =>
                onUnitPriceChange(
                  event.target.value
                )
              }
              aria-invalid={
                fieldError?.field ===
                "unitPrice"
                  ? "true"
                  : undefined
              }
              aria-describedby={
                fieldError?.field ===
                "unitPrice"
                  ? "edit-unit-price-error"
                  : undefined
              }
              className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
            />
            {fieldError?.field ===
            "unitPrice" ? (
              <span
                id="edit-unit-price-error"
                role="alert"
                className="mt-1 block text-[11px] font-bold text-rose-700"
              >
                {fieldError.message}
              </span>
            ) : null}
          </label>
        </div>

        {independentPrices ? (
          <p className="text-xs font-bold text-slate-500">
            {t(
              "products.independentPrices"
            )}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
