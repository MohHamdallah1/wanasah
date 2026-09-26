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
      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
      : product.lifecycle_status ===
          "RETIRING"
        ? "bg-amber-50 text-amber-800 ring-amber-200"
        : "bg-slate-100 text-slate-600 ring-slate-200";

  return (
    <header className="shrink-0 border-b border-slate-200 bg-white">
      <div className="flex h-12 items-center justify-between gap-3 border-b border-slate-100 px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500"
          />
          <p className="truncate text-[11px] font-black text-slate-700">
            {t(
              "products.details.title",
            )}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
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
            className="hidden h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 sm:inline-flex"
          >
            {expanded ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </button>

          <button
            type="button"
            onClick={onClose}
            aria-label={t(
              "common.close",
            )}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-[44px_minmax(0,1fr)] items-center gap-3 px-4 py-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-amber-200 bg-amber-50 text-amber-700">
          <Box className="h-5 w-5" />
        </div>

        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <h2
              id="product-detail-title"
              className="min-w-0 break-words text-base font-black leading-5 tracking-[-0.01em] text-slate-950"
            >
              {product.name}
            </h2>

            <span
              className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[9px] font-black ring-1 ring-inset ${lifecycleTone}`}
            >
              <span
                aria-hidden="true"
                className="me-1 h-1.5 w-1.5 rounded-full bg-current opacity-70"
              />
              {t(
                `products.details.lifecycleModes.${product.lifecycle_status}`,
              )}
            </span>

            {product.operational_hold !==
            "NONE" ? (
              <span className="inline-flex shrink-0 items-center rounded-full bg-rose-50 px-2 py-0.5 text-[9px] font-black text-rose-700 ring-1 ring-inset ring-rose-200">
                {t(
                  `products.details.holdModes.${product.operational_hold}`,
                )}
              </span>
            ) : null}
          </div>

          <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[10px] font-bold text-slate-500">
            <span className="break-words text-slate-600">
              {product.family_name}
            </span>
            <span
              aria-hidden="true"
              className="text-slate-300"
            >
              ·
            </span>
            <span className="break-all font-mono tracking-tight text-slate-400">
              {product.sku}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
