import type {
  ComponentProps,
} from "react";
import { useTranslation } from "react-i18next";

import { ProductBarcodeCreatePanel } from "@/pages/products/barcode/ProductBarcodeCreatePanel";
import { ProductBarcodeList } from "@/pages/products/barcode/ProductBarcodeList";

type Props = {
  open: boolean;
  onOpenChange: (
    open: boolean,
  ) => void;
  listProps: ComponentProps<
    typeof ProductBarcodeList
  >;
  createProps: ComponentProps<
    typeof ProductBarcodeCreatePanel
  >;
};

export function ProductBarcodeAdvancedPanel({
  open,
  onOpenChange,
  listProps,
  createProps,
}: Props) {
  const { t } = useTranslation();

  return (
    <details
      open={open}
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white"
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          onOpenChange(!open);
        }}
        className="cursor-pointer select-none px-4 py-3 text-[11px] font-black text-slate-600 transition hover:bg-slate-50"
      >
        {t(
          "products.barcodeManager.advanced",
        )}
      </summary>

      {open ? (
        <div className="border-t border-slate-100">
          <p className="px-4 pt-3 text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              "products.barcodeManager.advancedHint",
            )}
          </p>
          <ProductBarcodeList
            {...listProps}
          />
          <ProductBarcodeCreatePanel
            {...createProps}
          />
        </div>
      ) : null}
    </details>
  );
}
