import {
  Box,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductDetailActionsMenu } from "@/pages/products/detail/ProductDetailActionsMenu";

type Props = {
  product: SimpleProduct;
  expanded: boolean;
  canEditPrice: boolean;
  canRenameProduct: boolean;
  canReassignFamily: boolean;
  canEditTracking: boolean;
  canManageBarcodes: boolean;
  canManageLifecycle: boolean;
  canManageAdvancedUom: boolean;
  onToggleExpanded: () => void;
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

export function ProductDetailHero({
  product,
  expanded,
  canEditPrice,
  canRenameProduct,
  canReassignFamily,
  canEditTracking,
  canManageBarcodes,
  canManageLifecycle,
  canManageAdvancedUom,
  onToggleExpanded,
  onClose,
  onRenameProduct,
  onReassignFamily,
  onEditPrice,
  onEditTracking,
  onManageBarcodes,
  onManageLifecycle,
  onManageAdvancedUom,
}: Props) {
  const { t } = useTranslation();

  const lifecycleTone =
    product.lifecycle_status === "ACTIVE"
      ? "bg-emerald-400/15 text-emerald-200 ring-emerald-400/25"
      : product.lifecycle_status ===
          "RETIRING"
        ? "bg-amber-300/15 text-amber-100 ring-amber-300/25"
        : "bg-white/10 text-slate-200 ring-white/10";

  return (
    <header className="relative shrink-0 overflow-hidden border-b border-slate-800 bg-slate-950 text-white">
      <div
        aria-hidden="true"
        className="absolute inset-y-0 end-0 w-1 bg-amber-400"
      />
      <div
        aria-hidden="true"
        className="absolute -end-16 -top-20 h-56 w-56 rounded-full border border-white/[0.04]"
      />

      <div className="relative px-4 pb-4 pt-3 sm:px-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[10px] font-black uppercase tracking-[0.14em] text-slate-400">
            {t(
              "products.details.title",
            )}
          </p>

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
              onClick={
                onToggleExpanded
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
              className="hidden h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.07] text-slate-300 transition hover:bg-white/[0.13] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 sm:inline-flex"
            >
              {expanded ? (
                <Minimize2 className="h-4 w-4" />
              ) : (
                <Maximize2 className="h-4 w-4" />
              )}
            </button>

            <button
              type="button"
              onClick={onClose}
              aria-label={t(
                "common.close",
              )}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.07] text-slate-300 transition hover:bg-white/[0.13] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-[44px_minmax(0,1fr)] items-start gap-3 sm:grid-cols-[52px_minmax(0,1fr)] sm:gap-4">
          <div className="relative flex h-11 w-11 items-center justify-center rounded-xl border border-amber-300/20 bg-amber-300/10 text-amber-300 sm:h-12 sm:w-12">
            <Box className="h-5 w-5 sm:h-6 sm:w-6" />
            <span
              aria-hidden="true"
              className="absolute -bottom-1 -end-1 h-2.5 w-2.5 rounded-sm bg-amber-400 ring-2 ring-slate-950"
            />
          </div>

          <div className="min-w-0">
            <h2
              id="product-detail-title"
              className="break-words text-lg font-black leading-6 tracking-[-0.015em] text-white sm:text-xl"
            >
              {product.name}
            </h2>

            <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[10px] font-bold text-slate-400">
              <span className="break-words text-slate-300">
                {product.family_name}
              </span>
              <span
                aria-hidden="true"
                className="text-slate-600"
              >
                /
              </span>
              <span className="break-all font-mono tracking-tight">
                {product.sku}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-black ring-1 ring-inset ${lifecycleTone}`}
              >
                <span
                  aria-hidden="true"
                  className="me-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-80"
                />
                {t(
                  `products.details.lifecycleModes.${product.lifecycle_status}`,
                )}
              </span>

              {product.operational_hold !==
              "NONE" ? (
                <span className="inline-flex items-center rounded-full bg-rose-400/15 px-2.5 py-1 text-[10px] font-black text-rose-200 ring-1 ring-inset ring-rose-400/25">
                  <span
                    aria-hidden="true"
                    className="me-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-80"
                  />
                  {t(
                    `products.details.holdModes.${product.operational_hold}`,
                  )}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
