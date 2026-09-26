import {
  ArchiveRestore,
  Barcode,
  Boxes,
  CircleDollarSign,
  FolderTree,
  MoreHorizontal,
  Pencil,
  Waypoints,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct;
  canEditPrice: boolean;
  canRenameProduct: boolean;
  canReassignFamily: boolean;
  canEditTracking: boolean;
  canManageBarcodes: boolean;
  canManageLifecycle: boolean;
  canManageAdvancedUom: boolean;
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

export function ProductDetailActionsMenu({
  product,
  canEditPrice,
  canRenameProduct,
  canReassignFamily,
  canEditTracking,
  canManageBarcodes,
  canManageLifecycle,
  canManageAdvancedUom,
  onRenameProduct,
  onReassignFamily,
  onEditPrice,
  onEditTracking,
  onManageBarcodes,
  onManageLifecycle,
  onManageAdvancedUom,
}: Props) {
  const { t } = useTranslation();
  const lifecycleEditable =
    ["ACTIVE", "RETIRING"].includes(
      product.lifecycle_status,
    );

  const hasActions =
    (canRenameProduct &&
      lifecycleEditable) ||
    (canReassignFamily &&
      lifecycleEditable) ||
    (canEditPrice &&
      product.simple_compatible) ||
    canEditTracking ||
    canManageBarcodes ||
    canManageLifecycle ||
    (canManageAdvancedUom &&
      !product.simple_compatible);

  if (!hasActions) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t(
            "products.details.actions",
          )}
          title={t(
            "products.details.actions",
          )}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        className="w-64 rounded-xl border-slate-200 p-1.5 shadow-xl"
      >
        {canRenameProduct &&
        lifecycleEditable ? (
          <DropdownMenuItem
            onSelect={() =>
              onRenameProduct(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <Pencil className="h-4 w-4 text-slate-400" />
            {t(
              "products.rename.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canReassignFamily &&
        lifecycleEditable ? (
          <DropdownMenuItem
            onSelect={() =>
              onReassignFamily(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <FolderTree className="h-4 w-4 text-slate-400" />
            {t(
              "products.familyReassign.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canEditPrice &&
        product.simple_compatible ? (
          <DropdownMenuItem
            onSelect={() =>
              onEditPrice(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <CircleDollarSign className="h-4 w-4 text-slate-400" />
            {t(
              "products.editPrice",
            )}
          </DropdownMenuItem>
        ) : null}

        {(canRenameProduct &&
          lifecycleEditable) ||
        (canReassignFamily &&
          lifecycleEditable) ||
        (canEditPrice &&
          product.simple_compatible) ? (
          <DropdownMenuSeparator />
        ) : null}

        {canManageLifecycle ? (
          <DropdownMenuItem
            onSelect={() =>
              onManageLifecycle(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <ArchiveRestore className="h-4 w-4 text-slate-400" />
            {t(
              "products.lifecycleManager.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageBarcodes ? (
          <DropdownMenuItem
            onSelect={() =>
              onManageBarcodes(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <Barcode className="h-4 w-4 text-slate-400" />
            {t(
              "products.barcodeManager.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageAdvancedUom &&
        !product.simple_compatible ? (
          <DropdownMenuItem
            onSelect={() =>
              onManageAdvancedUom(
                product,
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <Boxes className="h-4 w-4 text-slate-400" />
            {t(
              "products.advancedUom.productAction",
            )}
          </DropdownMenuItem>
        ) : null}

        {canEditTracking ? (
          <DropdownMenuItem
            onSelect={() =>
              onEditTracking(product)
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-xs font-bold"
          >
            <Waypoints className="h-4 w-4 text-slate-400" />
            {t(
              "products.trackingEditor.action",
            )}
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
