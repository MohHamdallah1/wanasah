import {
  Plus,
  ScanBarcode,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductBarcodeType,
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct;
  barcode: string;
  barcodeType: ProductBarcodeType;
  target: "base" | "package";
  isPrimary: boolean;
  pendingCreate: boolean;
  pendingCreateBlocked: boolean;
  canEditCreate: boolean;
  canMutate: boolean;
  targetUomId: number | null;
  onBarcodeChange: (value: string) => void;
  onBarcodeTypeChange: (
    value: ProductBarcodeType,
  ) => void;
  onTargetChange: (
    value: "base" | "package",
  ) => void;
  onPrimaryChange: (value: boolean) => void;
  onSave: () => void;
};

const BARCODE_TYPES: ProductBarcodeType[] = [
  "INTERNAL",
  "EAN8",
  "EAN13",
  "UPC_A",
  "GTIN14",
  "GS1_128",
];

export function ProductBarcodeCreatePanel({
  product,
  barcode,
  barcodeType,
  target,
  isPrimary,
  pendingCreate,
  pendingCreateBlocked,
  canEditCreate,
  canMutate,
  targetUomId,
  onBarcodeChange,
  onBarcodeTypeChange,
  onTargetChange,
  onPrimaryChange,
  onSave,
}: Props) {
  const { t } = useTranslation();

  return (
    <section className="border-t border-slate-200 bg-slate-50/50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-400 text-slate-950">
          <ScanBarcode className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h3 className="text-xs font-black text-slate-900">
            {t(
              "products.barcodeManager.add"
            )}
          </h3>
          <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
            {t(
              "products.barcodeManager.historyHint"
            )}
          </p>
        </div>
      </div>

      {pendingCreate ? (
        <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[10px] font-bold leading-4 text-amber-900">
          {t(
            "products.barcodeManager.pendingRetry"
          )}
        </p>
      ) : null}

      {pendingCreateBlocked ? (
        <p className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-[10px] font-bold leading-4 text-rose-800">
          {t(
            "products.barcodeManager.pendingBlocked"
          )}
        </p>
      ) : null}

      {product.package_uom_id !== null &&
      product.package_uses_base_barcode ? (
        <p className="mb-3 rounded-lg bg-white px-3 py-2 text-[10px] font-bold leading-4 text-slate-600 ring-1 ring-inset ring-slate-200">
          {t(
            "products.barcodeManager.sharedPackageHint"
          )}
        </p>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-[minmax(0,0.72fr)_minmax(0,0.85fr)_minmax(0,1.5fr)_auto] sm:items-end">
        <label className="text-[11px] font-black text-slate-600">
          {t(
            "products.barcodeManager.scope"
          )}
          <select
            value={target}
            disabled={!canEditCreate}
            onChange={(event) =>
              onTargetChange(
                event.target.value as
                  | "base"
                  | "package"
              )
            }
            className="mt-1 h-10 w-full rounded-xl border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-40"
          >
            <option value="base">
              {t(
                "products.barcodeManager.unit"
              )}
            </option>
            {product.package_uom_id !==
              null &&
            !product.package_uses_base_barcode ? (
              <option value="package">
                {t(
                  "products.barcodeManager.package"
                )}
              </option>
            ) : null}
          </select>
        </label>

        <label className="text-[11px] font-black text-slate-600">
          {t(
            "products.barcodeManager.type"
          )}
          <select
            value={barcodeType}
            disabled={!canEditCreate}
            onChange={(event) =>
              onBarcodeTypeChange(
                event.target
                  .value as ProductBarcodeType
              )
            }
            className="mt-1 h-10 w-full rounded-xl border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-40"
          >
            {BARCODE_TYPES.map(
              (value) => (
                <option
                  key={value}
                  value={value}
                >
                  {t(
                    `products.barcodeManager.types.${value}`
                  )}
                </option>
              )
            )}
          </select>
        </label>

        <label className="text-[11px] font-black text-slate-600">
          {t(
            "products.barcodeManager.value"
          )}
          <input
            value={barcode}
            disabled={!canEditCreate}
            onChange={(event) =>
              onBarcodeChange(
                event.target.value
              )
            }
            maxLength={128}
            className="mt-1 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm font-bold outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-40"
          />
        </label>

        <button
          type="button"
          disabled={
            !canMutate ||
            pendingCreateBlocked ||
            (!pendingCreate &&
              (!barcode.trim() ||
                targetUomId === null))
          }
          onClick={onSave}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800 disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
          {pendingCreate
            ? t(
                "products.barcodeManager.retryPending"
              )
            : t(
                "products.barcodeManager.save"
              )}
        </button>
      </div>

      <label className="mt-3 inline-flex items-center gap-2 text-[11px] font-bold text-slate-600">
        <input
          type="checkbox"
          checked={isPrimary}
          disabled={!canEditCreate}
          onChange={(event) =>
            onPrimaryChange(
              event.target.checked
            )
          }
          className="h-4 w-4"
        />
        {t(
          "products.barcodeManager.makePrimary"
        )}
      </label>
    </section>
  );
}
