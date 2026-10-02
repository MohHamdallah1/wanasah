import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { useDialogFocusTrap } from "@/hooks/useDialogFocusTrap";
import {
  DEFAULT_PRODUCT_DISPLAY_PREFERENCES,
  type ProductDetailSection as ProductDetailSectionKey,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductDetailHero } from "@/pages/products/detail/ProductDetailHero";
import { ProductDetailTabPanel } from "@/pages/products/detail/ProductDetailTabPanel";
import {
  ProductDetailTabs,
  type ProductDetailTabKey,
} from "@/pages/products/detail/ProductDetailTabs";

type Props = {
  product: SimpleProduct | null;
  detailSections?: Record<
    ProductDetailSectionKey,
    boolean
  >;
  onClose: () => void;
};

export function ProductDetailDrawer({
  product,
  detailSections =
    DEFAULT_PRODUCT_DISPLAY_PREFERENCES.detailSections,
  onClose,
}: Props) {
  const { i18n } =
    useTranslation();
  const [
    expanded,
    setExpanded,
  ] = useState(false);
  const [
    activeTab,
    setActiveTab,
  ] =
    useState<ProductDetailTabKey>(
      "overview",
    );

  const tabs =
    useMemo<
      ProductDetailTabKey[]
    >(
      () => [
        "overview",
        ...(
          detailSections.tracking ||
          detailSections.barcodes
            ? ([
                "tracking",
              ] as const)
            : []
        ),
      ],
      [
        detailSections.barcodes,
        detailSections.tracking,
      ],
    );

  useEffect(() => {
    setActiveTab("overview");
  }, [product?.id]);

  useEffect(() => {
    if (
      !tabs.includes(activeTab)
    ) {
      setActiveTab(
        "overview",
      );
    }
  }, [activeTab, tabs]);

  const handleClose =
    useCallback(() => {
      setExpanded(false);
      setActiveTab("overview");
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
        className={`absolute inset-y-0 end-0 flex w-full flex-col overflow-hidden border-s border-slate-200 bg-white shadow-2xl transition-[width] duration-200 sm:inset-y-4 sm:end-4 sm:max-w-none sm:rounded-2xl sm:border sm:border-slate-200 ${
          expanded
            ? "sm:w-[min(60vw,860px)]"
            : "sm:w-[min(36vw,520px)]"
        }`}
      >
        <ProductDetailHero
          product={product}
          expanded={expanded}
          onToggleExpanded={() =>
            setExpanded(
              (current) =>
                !current,
            )
          }
          onClose={handleClose}
        />

        <ProductDetailTabs
          tabs={tabs}
          activeTab={activeTab}
          onChange={
            setActiveTab
          }
        />

        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/70 p-2.5 sm:p-3">
          <ProductDetailTabPanel
            product={product}
            activeTab={activeTab}
            expanded={expanded}
            showPackage={
              detailSections.package
            }
            showCompatibility={
              detailSections.compatibility
            }
            showTracking={
              detailSections.tracking
            }
            showBarcodes={
              detailSections.barcodes
            }
          />
        </div>
      </aside>
    </div>
  );
}
