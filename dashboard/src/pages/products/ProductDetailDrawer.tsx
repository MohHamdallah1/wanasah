import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useDialogFocusTrap } from "@/hooks/useDialogFocusTrap";
import {
  resolveI18nLocale,
} from "@/lib/locale";
import {
  formatLocaleDecimal,
  formatLocaleMoney,
} from "@/lib/localeNumbers";
import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
  type ProductDetailSection,
} from "@/lib/productDisplayPreferences";
import type { SimpleProduct } from "@/pages/products/contracts";


type Props = {
  product: SimpleProduct | null;
  pricingVisible: boolean;
  canEditPrice: boolean;
  canEditTracking: boolean;
  canManageBarcodes: boolean;
  canManageAdvancedUom: boolean;
  detailSections?: Record<
    ProductDetailSection,
    boolean
  >;
  onClose: () => void;
  onEditPrice: (product: SimpleProduct) => void;
  onEditTracking: (product: SimpleProduct) => void;
  onManageBarcodes: (product: SimpleProduct) => void;
  onManageAdvancedUom: (product: SimpleProduct) => void;
};

export function ProductDetailDrawer({
  product,
  pricingVisible,
  canEditPrice,
  canEditTracking,
  canManageBarcodes,
  canManageAdvancedUom,
  detailSections =
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.detailSections,
  onClose,
  onEditPrice,
  onEditTracking,
  onManageBarcodes,
  onManageAdvancedUom,
}: Props) {
  const { t, i18n } = useTranslation();
  const locale =
    resolveI18nLocale(i18n);

  const dialogRef =
    useDialogFocusTrap<HTMLElement>(
      product !== null,
      onClose,
    );

  if (!product) {
    return null;
  }

  const price = (
    value: string | null
  ) =>
    formatLocaleMoney(
      value,
      product.currency_code,
      locale,
    );

  return (
    <div className="fixed inset-0 z-[90]">
      <div
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/35 backdrop-blur-[1px]"
      />

      <aside
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-detail-title"
        dir={i18n.dir()}
        className="absolute inset-y-0 end-0 flex w-full max-w-xl flex-col border-s border-slate-200 bg-white shadow-2xl"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 sm:gap-4 sm:px-5 sm:py-4">
          <div className="min-w-0">
            <p className="text-xs font-black text-slate-400">
              {t(
                "products.details.title"
              )}
            </p>
            <h2
              id="product-detail-title"
              className="mt-1 break-words text-lg font-black text-slate-950 sm:truncate sm:text-xl"
            >
              {product.name}
            </h2>
            <p className="mt-1 text-xs font-bold text-slate-500">
              {product.family_name}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 hover:bg-slate-50"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 sm:space-y-4 sm:p-5">
          <section className="rounded-2xl border border-slate-200 p-4">
            <h3 className="text-sm font-black text-slate-900">
              {t(
                "products.details.identity"
              )}
            </h3>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-[11px] font-black text-slate-400">
                  {t(
                    "products.fields.sku"
                  )}
                </dt>
                <dd className="mt-1 font-mono text-sm font-black text-slate-800">
                  {product.sku}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-black text-slate-400">
                  {t(
                    "products.details.lifecycle"
                  )}
                </dt>
                <dd className="mt-1 text-sm font-black text-slate-800">
                  {t(
                    `products.details.lifecycleModes.${product.lifecycle_status}`
                  )}
                </dd>
              </div>
            </dl>
          </section>

          {detailSections.package ? (
            <section className="rounded-2xl border border-slate-200 p-4">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.details.package"
                )}
              </h3>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.columns.package"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {product.package_uom_code
                      ? t(
                          `uom.${product.package_uom_code}`
                        )
                      : t("uom.NONE")}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.columns.unitsPerPackage"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {product.package_uom_code &&
                    product.units_per_package !==
                      null
                      ? formatLocaleDecimal(
                          String(
                            product.units_per_package
                          ),
                          locale,
                        )
                      : "—"}
                  </dd>
                </div>
              </dl>
            </section>
          ) : null}

          {detailSections.tracking ? (
            <section className="rounded-2xl border border-slate-200 p-4">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.details.tracking"
                )}
              </h3>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.tracking.shortLot"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {t(
                      `products.tracking.lotModes.${product.lot_control_mode}`
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.tracking.shortExpiry"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {t(
                      `products.tracking.expiryModes.${product.expiry_control_mode}`
                    )}
                  </dd>
                </div>
              </dl>
            </section>
          ) : null}

          {detailSections.barcodes ? (
            <section className="rounded-2xl border border-slate-200 p-4">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.details.barcodes"
                )}
              </h3>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.unitBarcode"
                    )}
                  </dt>
                  <dd className="mt-1 break-all font-mono text-sm font-black text-slate-800">
                    {product.unit_barcode ??
                      t(
                        "products.details.notSet"
                      )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.packageBarcode"
                    )}
                  </dt>
                  <dd className="mt-1 break-all font-mono text-sm font-black text-slate-800">
                    {product.package_barcode ??
                      t(
                        "products.details.notSet"
                      )}
                  </dd>
                </div>
              </dl>
            </section>
          ) : null}

          {pricingVisible &&
          detailSections.pricing ? (
            <section className="rounded-2xl border border-slate-200 p-4">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.details.pricing"
                )}
              </h3>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.columns.packagePrice"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {price(
                      product.package_price
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] font-black text-slate-400">
                    {t(
                      "products.columns.unitPrice"
                    )}
                  </dt>
                  <dd className="mt-1 text-sm font-black text-slate-800">
                    {price(
                      product.unit_price
                    )}
                  </dd>
                </div>
              </dl>
            </section>
          ) : null}

          {detailSections.compatibility ? (
            <section className="rounded-2xl border border-slate-200 p-4">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.details.compatibility"
                )}
              </h3>
              <p className="mt-2 text-xs font-bold leading-6 text-slate-600">
                {t(
                  product.simple_compatible
                    ? "products.details.simpleCompatible"
                    : "products.details.advancedOnly"
                )}
              </p>
            </section>
          ) : null}
        </div>

        {canEditPrice ||
        canEditTracking ||
        canManageBarcodes ||
        (canManageAdvancedUom &&
          !product.simple_compatible) ? (
          <footer className="grid shrink-0 grid-cols-1 gap-2 border-t border-slate-100 bg-slate-50 px-3 py-3 sm:flex sm:flex-wrap sm:justify-end sm:px-5 sm:py-4">
            {canEditPrice &&
            product.simple_compatible ? (
              <button
                type="button"
                onClick={() =>
                  onEditPrice(product)
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-700 hover:bg-slate-50 sm:w-auto"
              >
                {t(
                  "products.editPrice"
                )}
              </button>
            ) : null}

            {canManageBarcodes ? (
              <button
                type="button"
                onClick={() =>
                  onManageBarcodes(product)
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-700 hover:bg-slate-50 sm:w-auto"
              >
                {t(
                  "products.barcodeManager.action"
                )}
              </button>
            ) : null}

            {canManageAdvancedUom &&
            !product.simple_compatible ? (
              <button
                type="button"
                onClick={() =>
                  onManageAdvancedUom(
                    product
                  )
                }
                className="w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-xs font-black text-amber-900 hover:bg-amber-100 sm:w-auto"
              >
                {t(
                  "products.advancedUom.productAction"
                )}
              </button>
            ) : null}

            {canEditTracking ? (
              <button
                type="button"
                onClick={() =>
                  onEditTracking(product)
                }
                className="w-full rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white sm:w-auto"
              >
                {t(
                  "products.trackingEditor.action"
                )}
              </button>
            ) : null}
          </footer>
        ) : null}
      </aside>
    </div>
  );
}
