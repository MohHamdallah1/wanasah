import {
  useRef,
  useState,
} from "react";
import {
  CircleDollarSign,
  Eye,
  FolderTree,
  MoreHorizontal,
  Waypoints,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  item: SimpleProduct;
  canEditPrice: boolean;
  canReassignFamily: boolean;
  canEditTracking: boolean;
  onOpenDetails: (
    item: SimpleProduct,
  ) => void;
  onEditPrice: (
    item: SimpleProduct,
  ) => void;
  onReassignFamily: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
};

export function ProductRowActions({
  item,
  canEditPrice,
  canReassignFamily,
  canEditTracking,
  onOpenDetails,
  onEditPrice,
  onReassignFamily,
  onEditTracking,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const direction =
    i18n.dir();
  const familyReassignAllowed =
    canReassignFamily &&
    ["ACTIVE", "RETIRING"].includes(
      item.lifecycle_status,
    );
  const [
    menuOpen,
    setMenuOpen,
  ] = useState(false);
  const pendingActionRef =
    useRef<(() => void) | null>(
      null
    );

  const queueAfterMenuClose = (
    action: () => void,
  ) => {
    pendingActionRef.current =
      action;
  };

  const handleCloseAutoFocus = () => {
    const action =
      pendingActionRef.current;
    if (!action) {
      return;
    }

    pendingActionRef.current =
      null;
    window.requestAnimationFrame(
      action,
    );
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
            "products.columns.action",
          )}
          title={t(
            "products.columns.action",
          )}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-slate-400 transition hover:border-slate-200 hover:bg-white hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
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
        className="w-52 rounded-xl border-slate-200 p-1.5 text-start shadow-xl"
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
          <Eye className="h-4 w-4 text-slate-400" />
          {t(
            "products.details.open",
          )}
        </DropdownMenuItem>

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
            <CircleDollarSign className="h-4 w-4 text-slate-400" />
            {t(
              "products.editPrice",
            )}
          </DropdownMenuItem>
        ) : null}

        {familyReassignAllowed ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onReassignFamily(
                    item
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

        {canEditTracking ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                () =>
                  onEditTracking(item),
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
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
