import {
  ArchiveRestore,
  Barcode,
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
};

export function ProductDetailActionsMenu({
  product,
  canEditPrice,
  canRenameProduct,
  canReassignFamily,
  canEditTracking,
  canManageBarcodes,
  canManageLifecycle,
  onRenameProduct,
  onReassignFamily,
  onEditPrice,
  onEditTracking,
  onManageBarcodes,
  onManageLifecycle,
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
    canManageLifecycle;

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
          className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[10px] font-black text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
          <span>
            {t(
              "products.details.actions",
            )}
          </span>
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        className="z-[120] w-64 rounded-xl border-slate-200 p-1.5 shadow-xl"
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
