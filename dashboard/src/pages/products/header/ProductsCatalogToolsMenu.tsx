import {
  useRef,
  useState,
} from "react";
import {
  ChevronDown,
  FolderTree,
  LockKeyhole,
  Settings2,
  SlidersHorizontal,
  Waypoints,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Props = {
  triggerVariant?: "default" | "topbar";
  trackingDefaultsLoading: boolean;
  canManageCatalog: boolean;
  canManageFamilies: boolean;
  onOpenDisplayPreferences: () => void;
  onOpenTrackingDefaults: () => void;
  onOpenFamilies: () => void;
};

export function ProductsCatalogToolsMenu({
  triggerVariant = "default",
  trackingDefaultsLoading,
  canManageCatalog,
  canManageFamilies,
  onOpenDisplayPreferences,
  onOpenTrackingDefaults,
  onOpenFamilies,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const direction =
    i18n.dir();
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
          className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-3 text-xs font-black transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 ${
            triggerVariant === "topbar"
              ? "border-white/10 bg-white/[0.06] text-slate-100 hover:border-white/15 hover:bg-white/[0.1] hover:text-white"
              : "border-slate-200 bg-white text-slate-700 shadow-sm hover:border-slate-300 hover:bg-slate-50"
          }`}
        >
          <Settings2 className="h-4 w-4 shrink-0" />
          <span>
            {t(
              "products.catalogTools",
            )}
          </span>
          <ChevronDown
            className={`h-3.5 w-3.5 ${
              triggerVariant === "topbar"
                ? "text-slate-300"
                : "text-slate-400"
            }`}
          />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        dir={direction}
        align="end"
        loop
        onCloseAutoFocus={
          handleCloseAutoFocus
        }
        className="w-72 rounded-xl border-slate-200 p-1.5 text-start shadow-xl"
      >
        <DropdownMenuLabel className="px-2.5 py-2 text-start text-[11px] font-black text-slate-400">
          {t(
            "products.catalogTools",
          )}
        </DropdownMenuLabel>

        {canManageCatalog ? (
          <DropdownMenuItem
            disabled={
              trackingDefaultsLoading
            }
            onSelect={() =>
              queueAfterMenuClose(
                onOpenTrackingDefaults
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <Waypoints className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.trackingSettings.action",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageFamilies ? (
          <DropdownMenuItem
            onSelect={() =>
              queueAfterMenuClose(
                onOpenFamilies
              )
            }
            className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
          >
            <FolderTree className="h-4 w-4 shrink-0 text-slate-400" />
            {t(
              "products.families",
            )}
          </DropdownMenuItem>
        ) : null}

        {canManageCatalog ||
        canManageFamilies ? (
          <DropdownMenuSeparator />
        ) : null}

        <DropdownMenuItem
          onSelect={() =>
            queueAfterMenuClose(
              onOpenDisplayPreferences
            )
          }
          className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-700"
        >
          <SlidersHorizontal className="h-4 w-4 shrink-0 text-slate-400" />
          {t(
            "products.displayPreferences.action",
          )}
        </DropdownMenuItem>

        {canManageCatalog ? (
          <>
            <DropdownMenuItem
              disabled
              title={t(
                "products.advancedUom.deferredHint",
              )}
              className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-400"
            >
              <LockKeyhole className="h-4 w-4 shrink-0" />
              <span className="min-w-0 text-start">
                <span className="block">
                  {t(
                    "products.advancedUom.action",
                  )}
                </span>
                <span className="mt-0.5 block text-[10px] font-semibold leading-4 text-slate-400">
                  {t(
                    "products.advancedUom.deferredHint",
                  )}
                </span>
              </span>
            </DropdownMenuItem>

            <DropdownMenuItem
              disabled
              title={t(
                "products.advancedPricingHint",
              )}
              className="gap-3 rounded-lg px-2.5 py-2.5 text-start text-xs font-bold text-slate-400"
            >
              <LockKeyhole className="h-4 w-4 shrink-0" />
              <span className="min-w-0 text-start">
                <span className="block">
                  {t(
                    "products.advancedPricing",
                  )}
                </span>
                <span className="mt-0.5 block text-[10px] font-semibold leading-4 text-slate-400">
                  {t(
                    "products.advancedPricingHint",
                  )}
                </span>
              </span>
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
