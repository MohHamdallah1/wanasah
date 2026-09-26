import {
  useCallback,
  useState,
} from "react";
import {
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
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
  type ProductDetailSection as ProductDetailSectionKey,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductDetailActionsMenu } from "@/pages/products/detail/ProductDetailActionsMenu";
import {
  ProductDetailField,
  ProductDetailSection,
} from "@/pages/products/detail/ProductDetailPrimitives";

type Props = {
  product: SimpleProduct | null;
  pricingVisible: boolean;
  canEditPrice: boolean;
  canRenameProduct: boolean;
  canReassignFamily: boolean;
  canEditTracking: boolean;
  canManageBarcodes: boolean;
  canManageLifecycle: boolean;
  canManageAdvancedUom: boolean;
  detailSections?: Record<
    ProductDetailSectionKey,
    boolean
  >;
  onClose: () => void;
  onRenameProduct: (
    product: SimpleProduct,
  ) => void;
  onReassignFamily: (
    product: SimpleProduct,
  ) => void;
  onEditPrice: (
    product: SimpleProduct,
  ) => void;
  onEditTracking: (
    product: SimpleProduct,
  ) => void;
  onManageBarcodes: (
    product: SimpleProduct,
  ) => void;
  onManageLifecycle: (
    product: SimpleProduct,
  ) => void;
  onManageAdvancedUom: (
    product: SimpleProduct,
  ) => void;
};

export function ProductDetailDrawer({
  product,
  pricingVisible,
  canEditPrice,
  canRenameProduct,
  canReassignFamily,
  canEditTracking,
  canManageBarcodes,
  canManageLifecycle,
  canManageAdvancedUom,
  detailSections =
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.detailSections,
  onClose,
  onRenameProduct,
  onReassignFamily,
  onEditPrice,
  onEditTracking,
  onManageBarcodes,
  onManageLifecycle,
  onManageAdvancedUom,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const locale =
    resolveI18nLocale(i18n);
  const [
    expanded,
    setExpanded,
  ] = useState(false);

  const handleClose =
    useCallback(() => {
      setExpanded(false);
      onClose();
    }, [onClose]);

  const dialogRef =
    useDialogFocusTrap<HTMLElement>(
      product !== null,
      handleClose,
    );

  if (!product) {
    return null;
  }

  const price = (
    value: string | null,
  ) =>
    formatLocaleMoney(
      value,
      product.currency_code,
      locale,
    );

  const baseUomLabel =
    product.base_uom_code
      ? t(
          `uom.${product.base_uom_code}`,
        )
      : t(
          "products.details.advancedUomManaged",
        );
  const packageUomLabel =
    product.package_uom_code
      ? t(
          `uom.${product.package_uom_code}`,
        )
      : null;
  const packageConversion =
    packageUomLabel &&
    product.units_per_package !== null
      ? t(
          "products.details.packageConversion",
          {
            package:
              packageUomLabel,
            units:
              formatLocaleDecimal(
                String(
                  product.units_per_package,
                ),
                locale,
              ),
            base:
              baseUomLabel,
          },
        )
      : t(
          "products.details.unitOnlyStructure",
          {
            base:
              baseUomLabel,
          },
        );

  const lifecycleTone =
    product.lifecycle_status === "ACTIVE"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : product.lifecycle_status ===
          "RETIRING"
        ? "bg-amber-50 text-amber-800 ring-amber-200"
        : "bg-slate-100 text-slate-600 ring-slate-200";

  return (
    <div className="fixed inset-0 z-[90]">
      <div
        aria-hidden="true"
        onClick={handleClose}
        className="absolute inset-0 bg-slate-950/30"
      />

      <aside
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-detail-title"
        dir={i18n.dir()}
        className={`absolute inset-y-0 end-0 flex w-full flex-col border-s border-slate-200 bg-white shadow-2xl transition-[width] duration-200 sm:max-w-none ${
          expanded
            ? "sm:w-[min(72vw,920px)]"
            : "sm:w-[min(44vw,620px)]"
        }`}
      >
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3 sm:px-5">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-black uppercase tracking-[0.08em] text-slate-400">
                {t(
                  "products.details.title",
                )}
              </p>
              <h2
                id="product-detail-title"
                className="mt-1 break-words text-lg font-black leading-6 text-slate-950"
              >
                {product.name}
              </h2>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[10px] font-bold text-slate-500">
                <span className="break-words">
                  {product.family_name}
                </span>
                <span
                  aria-hidden="true"
                  className="text-slate-300"
                >
                  ·
                </span>
                <span className="break-all font-mono text-slate-400">
                  {product.sku}
                </span>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5">
                <span
                  className={`inline-flex rounded-full px-2 py-1 text-[10px] font-black ring-1 ring-inset ${lifecycleTone}`}
                >
                  {t(
                    `products.details.lifecycleModes.${product.lifecycle_status}`,
                  )}
                </span>
                {product.operational_hold !==
                "NONE" ? (
                  <span className="inline-flex rounded-full bg-rose-50 px-2 py-1 text-[10px] font-black text-rose-700 ring-1 ring-inset ring-rose-200">
                    {t(
                      `products.details.holdModes.${product.operational_hold}`,
                    )}
                  </span>
                ) : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-1.5">
              <ProductDetailActionsMenu
                product={product}
                canEditPrice={
                  canEditPrice
                }
                canRenameProduct={
                  canRenameProduct
                }
                canReassignFamily={
                  canReassignFamily
                }
                canEditTracking={
                  canEditTracking
                }
                canManageBarcodes={
                  canManageBarcodes
                }
                canManageLifecycle={
                  canManageLifecycle
                }
                canManageAdvancedUom={
                  canManageAdvancedUom
                }
                onRenameProduct={
                  onRenameProduct
                }
                onReassignFamily={
                  onReassignFamily
                }
                onEditPrice={
                  onEditPrice
                }
                onEditTracking={
                  onEditTracking
                }
                onManageBarcodes={
                  onManageBarcodes
                }
                onManageLifecycle={
                  onManageLifecycle
                }
                onManageAdvancedUom={
                  onManageAdvancedUom
                }
              />

              <button
                type="button"
                onClick={() =>
                  setExpanded(
                    (current) =>
                      !current,
                  )
                }
                aria-pressed={
                  expanded
                }
                aria-label={t(
                  expanded
                    ? "products.details.compact"
                    : "products.details.expand",
                )}
                title={t(
                  expanded
                    ? "products.details.compact"
                    : "products.details.expand",
                )}
                className="hidden h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 sm:inline-flex"
              >
                {expanded ? (
                  <Minimize2 className="h-4 w-4" />
                ) : (
                  <Maximize2 className="h-4 w-4" />
                )}
              </button>

              <button
                type="button"
                onClick={handleClose}
                aria-label={t(
                  "common.close",
                )}
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <ProductDetailSection
            title={t(
              "products.details.identity",
            )}
          >
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
              <ProductDetailField
                label={t(
                  "products.fields.sku",
                )}
                mono
                hint={t(
                  "products.details.skuLockedPublished",
                )}
              >
                {product.sku}
              </ProductDetailField>
              <ProductDetailField
                label={t(
                  "products.details.lifecycle",
                )}
              >
                {t(
                  `products.details.lifecycleModes.${product.lifecycle_status}`,
                )}
              </ProductDetailField>
              <ProductDetailField
                label={t(
                  "products.details.operationalHold",
                )}
              >
                {t(
                  `products.details.holdModes.${product.operational_hold}`,
                )}
              </ProductDetailField>
            </dl>
          </ProductDetailSection>

          {detailSections.package ? (
            <ProductDetailSection
              title={t(
                "products.details.package",
              )}
            >
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                <ProductDetailField
                  label={t(
                    "products.details.baseUnit",
                  )}
                >
                  {baseUomLabel}
                </ProductDetailField>
                <ProductDetailField
                  label={t(
                    "products.columns.package",
                  )}
                >
                  {packageUomLabel ??
                    t("uom.NONE")}
                </ProductDetailField>
              </dl>
              <div className="mt-3 border-s-2 border-amber-300 ps-3">
                <p className="text-xs font-black leading-5 text-slate-800">
                  {packageConversion}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
                  {t(
                    "products.details.packageStructureLockedPublished",
                  )}
                </p>
              </div>
            </ProductDetailSection>
          ) : null}

          {detailSections.tracking ? (
            <ProductDetailSection
              title={t(
                "products.details.tracking",
              )}
            >
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                <ProductDetailField
                  label={t(
                    "products.tracking.shortLot",
                  )}
                >
                  {t(
                    `products.tracking.lotModes.${product.lot_control_mode}`,
                  )}
                </ProductDetailField>
                <ProductDetailField
                  label={t(
                    "products.tracking.shortExpiry",
                  )}
                >
                  {t(
                    `products.tracking.expiryModes.${product.expiry_control_mode}`,
                  )}
                </ProductDetailField>
              </dl>
            </ProductDetailSection>
          ) : null}

          {detailSections.barcodes ? (
            <ProductDetailSection
              title={t(
                "products.details.barcodes",
              )}
            >
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                <ProductDetailField
                  label={t(
                    "products.unitBarcode",
                  )}
                  mono
                >
                  {product.unit_barcode ??
                    t(
                      "products.details.notSet",
                    )}
                </ProductDetailField>
                <ProductDetailField
                  label={t(
                    "products.packageBarcode",
                  )}
                  mono
                >
                  {product.package_barcode ??
                    t(
                      "products.details.notSet",
                    )}
                </ProductDetailField>
              </dl>
            </ProductDetailSection>
          ) : null}

          {pricingVisible &&
          detailSections.pricing ? (
            <ProductDetailSection
              title={t(
                "products.details.pricing",
              )}
            >
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                <ProductDetailField
                  label={t(
                    "products.columns.packagePrice",
                  )}
                >
                  {price(
                    product.package_price,
                  )}
                </ProductDetailField>
                <ProductDetailField
                  label={t(
                    "products.columns.unitPrice",
                  )}
                >
                  {price(
                    product.unit_price,
                  )}
                </ProductDetailField>
              </dl>
            </ProductDetailSection>
          ) : null}

          {detailSections.compatibility ? (
            <ProductDetailSection
              title={t(
                "products.details.compatibility",
              )}
            >
              <p className="max-w-3xl text-xs font-bold leading-5 text-slate-600">
                {t(
                  product.simple_compatible
                    ? "products.details.simpleCompatible"
                    : "products.details.advancedOnly",
                )}
              </p>
            </ProductDetailSection>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
