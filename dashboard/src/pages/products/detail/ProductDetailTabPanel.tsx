import {
  Boxes,
  PackageCheck,
  ScanBarcode,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  resolveI18nLocale,
} from "@/lib/locale";
import {
  formatLocaleDecimal,
} from "@/lib/localeNumbers";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import {
  ProductDetailField,
  ProductDetailSection,
} from "@/pages/products/detail/ProductDetailPrimitives";
import type {
  ProductDetailTabKey,
} from "@/pages/products/detail/ProductDetailTabs";

type Props = {
  product: SimpleProduct;
  activeTab: ProductDetailTabKey;
  expanded: boolean;
  showPackage: boolean;
  showCompatibility: boolean;
  showTracking: boolean;
  showBarcodes: boolean;
};

export function ProductDetailTabPanel({
  product,
  activeTab,
  expanded,
  showPackage,
  showCompatibility,
  showTracking,
  showBarcodes,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const locale =
    resolveI18nLocale(i18n);

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

  const packageBarcodeRelation =
    !product.package_uom_code
      ? null
      : product.package_uses_base_barcode
        ? t(
            "products.details.packageBarcodeShared",
          )
        : product.package_barcode
          ? t(
              "products.details.packageBarcodeSeparate",
            )
          : t(
              "products.details.packageBarcodeMissing",
            );

  return (
    <div
      id={`product-detail-panel-${activeTab}`}
      role="tabpanel"
      aria-labelledby={`product-detail-tab-${activeTab}`}
      tabIndex={0}
      className="outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
    >
      {activeTab ===
      "overview" ? (
        <div
          className={
            expanded &&
            showPackage &&
            showCompatibility
              ? "grid gap-3 sm:grid-cols-2"
              : "space-y-3"
          }
        >
          {showPackage ? (
            <ProductDetailSection
              icon={PackageCheck}
              title={t(
                "products.details.structure",
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

          {showCompatibility ? (
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
      ) : null}

      {activeTab ===
      "tracking" ? (
        <div
          className={
            expanded &&
            showTracking &&
            showBarcodes
              ? "grid gap-3 sm:grid-cols-2"
              : "space-y-3"
          }
        >
          {showTracking ? (
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

          {showBarcodes ? (
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

                {packageBarcodeRelation ? (
                  <ProductDetailField
                    label={t(
                      "products.details.packageBarcodeRelation",
                    )}
                  >
                    {packageBarcodeRelation}
                  </ProductDetailField>
                ) : null}
              </dl>
            </ProductDetailSection>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
