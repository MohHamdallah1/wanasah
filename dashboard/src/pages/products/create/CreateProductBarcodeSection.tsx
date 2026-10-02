import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductDraft,
} from "@/pages/products/create/types";

type Props = {
  draft: ProductDraft;
  onUnitBarcodeChange: (value: string) => void;
  onCopyBarcode: () => void;
  onPackageBarcodeChange: (value: string) => void;
};

export function CreateProductBarcodeSection({
  draft,
  onUnitBarcodeChange,
  onCopyBarcode,
  onPackageBarcodeChange,
}: Props) {
  const { t } = useTranslation();
  const packageLabel = t(
    `uom.${draft.package_uom_code}`
  );

  return (
    <section className="border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
      <div className="mb-3 flex items-center gap-2">
        <span
          aria-hidden="true"
          className="h-2 w-2 rounded-full bg-amber-400"
        />
        <h3 className="text-xs font-black text-slate-900">
          {t("products.barcodeSection")}
        </h3>
      </div>

      <div
        className={`grid gap-3 ${
          draft.has_package
            ? "sm:grid-cols-2"
            : "sm:max-w-[calc(50%-0.375rem)]"
        }`}
      >
        <label className="block text-xs font-black text-slate-600">
          <span className="flex h-8 items-center">
            {t("products.unitBarcode")}
          </span>
          <input
            value={draft.unit_barcode}
            onChange={(event) =>
              onUnitBarcodeChange(
                event.target.value
              )
            }
            className="mt-1 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm text-slate-950 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
          />
        </label>

        {draft.has_package ? (
          <label className="block text-xs font-black text-slate-600">
            <span className="flex h-8 items-center justify-between gap-2">
              <span>
                {t(
                  "products.quickCreate.packageBarcode",
                  {
                    package:
                      packageLabel,
                  }
                )}
              </span>
              <button
                type="button"
                disabled={
                  !draft.unit_barcode.trim()
                }
                onClick={onCopyBarcode}
                className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2 text-[10px] font-black text-slate-600 transition hover:border-slate-300 hover:bg-white hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-30"
              >
                <Copy className="h-3.5 w-3.5" />
                {t(
                  "products.copyBarcode"
                )}
              </button>
            </span>
            <input
              value={
                draft.package_barcode
              }
              onChange={(event) =>
                onPackageBarcodeChange(
                  event.target.value
                )
              }
              className="mt-1 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm text-slate-950 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
            />
          </label>
        ) : null}
      </div>
    </section>
  );
}
