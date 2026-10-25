import {
  useRef,
  useState,
} from "react";
import {
  ArchiveRestore,
  Barcode,
  CircleDollarSign,
  Eye,
  FolderTree,
  Link2,
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
  item: SimpleProduct;
  canEditPrice: boolean;
  canEditPurchaseReference?: boolean;
  canRenameProduct: boolean;
  canReassignFamily: boolean;
  canEditTracking: boolean;
  canManageBarcodes: boolean;
  canManageLifecycle: boolean;
  canViewProductLocations?: boolean;
  onOpenDetails: (
    item: SimpleProduct,
  ) => void;
  onRenameProduct: (
    item: SimpleProduct,
  ) => void;
  onEditPrice: (
    item: SimpleProduct,
  ) => void;
  onEditPurchaseReference?: (item: SimpleProduct) => void;
  onReassignFamily: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
  onManageBarcodes: (
    item: SimpleProduct,
  ) => void;
  onManageLifecycle: (
    item: SimpleProduct,
  ) => void;
  onManageProductLocations?: (
    item: SimpleProduct,
  ) => void;
};

export function ProductRowActions({
  item,
  canEditPrice,
  canEditPurchaseReference,
  canRenameProduct,
  canReassignFamily,
  canEditTracking,
  canManageBarcodes,
  canManageLifecycle,
  canViewProductLocations = false,
  onOpenDetails,
  onRenameProduct,
  onEditPrice,
  onEditPurchaseReference,
  onReassignFamily,
  onEditTracking,
  onManageBarcodes,
  onManageLifecycle,
  onManageProductLocations,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const direction =
    i18n.dir();
  const lifecycleEditable =
    ["ACTIVE", "RETIRING"].includes(
      item.lifecycle_status,
    );
  const [
    menuOpen,
    setMenuOpen,
  ] = useState(false);
  const pendingActionRef =
    useRef<(() => void) | null>(
      null,
    );

  const queueAfterMenuClose = (
    action: () => void,
  ) => {
    pendingActionRef.current =
      action;
  };

  const handleCloseAutoFocus =
    () => {
      const action =
        pendingActionRef.current;
      if (!action) {
        return;
      }

      pendingActionRef.current =
        null;
      queueMicrotask(action);
    };

  return (
    <DropdownMenu
      dir={direction}
      open={menuOpen}
      onOpenChange={(open) => {
        setMenuOpen(open);
        if (open) {
          pendingActionRef.current =
            null;
        }
      }}
    >
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t(
            "products.details.actions",
          )}
          title={t(
            "products.details.actions",
          )}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <MoreHorizontal className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        dir={direction}
        align="end"
        loop
        onCloseAutoFocus={
          handleCloseAutoFocus
        }
        className="w-64 rounded-xl border-slate-200 p-1.5 text-start shadow-xl"
      >
        <DropdownMenuItem
          onSelect={() =>
            queueAfterMenuClose(
              () =>
                onOpenDetails(item),
            )
          }
          className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
        >
          <Eye className="h-4 w-4 shrink-0 text-slate-400" />
          {t(
            "products.details.open",
          )}
        </DropdownMenuItem>

        {canViewProductLocations &&
        onManageProductLocations ? (
          <DropdownMenuItem
            disabled
            title={t("products.productLocationsV1Disabled")}
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-500"
          >
            <Link2 className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "catalogLifecycle.assignments.title",
            )}
          </DropdownMenuItem>
        ) : null}

        {(canRenameProduct &&
          lifecycleEditable) ||
        (canReassignFamily &&
          lifecycleEditable) ? (
          <DropdownMenuSeparator />
        ) : null}

        {canRenameProduct &&
        lifecycleEditable ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onRenameProduct(
                    item,
                  ),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <Pencil className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.rename.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canReassignFamily &&
        lifecycleEditable ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onReassignFamily(
                    item,
                  ),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <FolderTree className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.familyReassign.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {(canEditPrice &&
          item.simple_compatible) ||
        canEditPurchaseReference ||
        canEditTracking ||
        canManageBarcodes ||
        canManageLifecycle ? (
          <DropdownMenuSeparator />
        ) : null}

        {canEditPrice &&
        item.simple_compatible ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onEditPrice(item),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <CircleDollarSign className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.editPrice",
            )}
          </DropdownMenuItem>
        ) : null}

        {canEditPurchaseReference && onEditPurchaseReference ? (
          <DropdownMenuItem
            onSelect={() => queueAfterMenuClose(() => onEditPurchaseReference?.(item))}
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <CircleDollarSign className="h-4 w-4 shrink-0 text-slate-400" />
            {t("products.purchaseReference.action")}
          </DropdownMenuItem>
        ) : null}

        {canEditTracking ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () => onEditTracking(item),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <Waypoints className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.trackingEditor.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageBarcodes ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onManageBarcodes(
                    item,
                  ),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <Barcode className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.barcodeManager.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageLifecycle ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onManageLifecycle(
                    item,
                  ),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <ArchiveRestore className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.lifecycleManager.action",
            )}
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
