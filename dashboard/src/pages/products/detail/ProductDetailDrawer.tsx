import {
  useCallback,
  useState,
} from "react";
import {
  BadgeDollarSign,
  Boxes,
  Fingerprint,
  PackageCheck,
  ScanBarcode,
  ShieldCheck,
  Waypoints,
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
import { ProductDetailHero } from "@/pages/products/detail/ProductDetailHero";
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

  const contentLayout = expanded
    ? "grid content-start gap-2.5 sm:grid-cols-2"
    : "space-y-2.5";

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
            ? "sm:w-[min(60vw,860px)]"
            : "sm:w-[min(36vw,520px)]"
        }`}
      >
        <ProductDetailHero
          product={product}
          expanded={expanded}
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
          onToggleExpanded={() =>
            setExpanded(
              (current) =>
                !current,
            )
          }
          onClose={handleClose}
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

        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/70 p-2.5 sm:p-3">
          <div className={contentLayout}>
            <ProductDetailSection
              icon={Fingerprint}
              title={t(
                "products.details.identity",
              )}
            >
              <dl
                className={`grid gap-x-4 gap-y-2.5 ${
                  expanded
                    ? "sm:grid-cols-3"
                    : "sm:grid-cols-2"
                }`}
              >
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
                icon={PackageCheck}
                title={t(
                  "products.details.package",
                )}
              >
                <dl className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
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

                <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50/70 px-2.5 py-2 ring-1 ring-inset ring-amber-100">
                  <Boxes
                    aria-hidden="true"
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700"
                  />
                  <div className="min-w-0">
                    <p className="text-[11px] font-black leading-5 text-slate-800">
                      {packageConversion}
                    </p>
                    <p className="mt-0.5 text-[9px] font-semibold leading-4 text-slate-500">
                      {t(
                        "products.details.packageStructureLockedPublished",
                      )}
                    </p>
                  </div>
                </div>
              </ProductDetailSection>
            ) : null}

            {detailSections.tracking ? (
              <ProductDetailSection
                icon={Waypoints}
                title={t(
                  "products.details.tracking",
                )}
              >
                <dl className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
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
                icon={ScanBarcode}
                title={t(
                  "products.details.barcodes",
                )}
              >
                <dl className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
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
                icon={BadgeDollarSign}
                title={t(
                  "products.details.pricing",
                )}
              >
                <dl className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
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
                icon={ShieldCheck}
                title={t(
                  "products.details.compatibility",
                )}
              >
                <p className="text-[11px] font-bold leading-5 text-slate-600">
                  {t(
                    product.simple_compatible
                      ? "products.details.simpleCompatible"
                      : "products.details.advancedOnly",
                  )}
                </p>
              </ProductDetailSection>
            ) : null}
          </div>
        </div>
      </aside>
    </div>
  );
}
