import {
  Boxes,
  PackagePlus,
  RefreshCw,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";

import { WorkspaceTopBar } from "@/components/dashboard/WorkspaceTopBar";
import { ProductsCatalogToolsMenu } from "@/pages/products/header/ProductsCatalogToolsMenu";

type Props = {
  isFetching: boolean;
  trackingDefaultsLoading: boolean;
  canManageCatalog: boolean;
  canImportProducts: boolean;
  canManageFamilies: boolean;
  canCreateSimpleProduct: boolean;
  onRefresh: () => void;
  onOpenDisplayPreferences: () => void;
  onOpenTrackingDefaults: () => void;
  onOpenImport: () => void;
  onOpenAdvancedUom: () => void;
  onOpenFamilies: () => void;
  onOpenCreateProduct: () => void;
};

export function ProductsPageHeader({
  isFetching,
  trackingDefaultsLoading,
  canManageCatalog,
  canImportProducts,
  canManageFamilies,
  canCreateSimpleProduct,
  onRefresh,
  onOpenDisplayPreferences,
  onOpenTrackingDefaults,
  onOpenImport,
  onOpenAdvancedUom,
  onOpenFamilies,
  onOpenCreateProduct,
}: Props) {
  const { t } = useTranslation();

  return (
    <WorkspaceTopBar
      variant="page"
      className="mb-2 shrink-0"
    >
      <header className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-amber-300">
            <Boxes className="h-4 w-4" />
          </span>

          <div className="min-w-0">
            <h1 className="break-words text-lg font-black leading-6 text-white sm:text-xl">
              {t("products.title")}
            </h1>
            <p className="mt-0.5 hidden break-words text-[11px] font-semibold leading-5 text-slate-300/80 sm:block">
              {t("products.subtitle")}
            </p>
          </div>
        </div>

        <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:justify-end">
          <button
            type="button"
            onClick={onRefresh}
            aria-label={t("common.refresh")}
            title={t("common.refresh")}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-slate-200 transition hover:border-white/15 hover:bg-white/[0.1] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <RefreshCw
              className={`h-4 w-4 ${
                isFetching
                  ? "animate-spin"
                  : ""
              }`}
            />
          </button>

          <ProductsCatalogToolsMenu
            triggerVariant="topbar"
            trackingDefaultsLoading={
              trackingDefaultsLoading
            }
            canManageCatalog={
              canManageCatalog
            }
            canImportProducts={
              canImportProducts
            }
            canManageFamilies={
              canManageFamilies
            }
            onOpenDisplayPreferences={
              onOpenDisplayPreferences
            }
            onOpenTrackingDefaults={
              onOpenTrackingDefaults
            }
            onOpenImport={
              onOpenImport
            }
            onOpenAdvancedUom={
              onOpenAdvancedUom
            }
            onOpenFamilies={
              onOpenFamilies
            }
          />

          {canCreateSimpleProduct ? (
            <button
              type="button"
              onClick={
                onOpenCreateProduct
              }
              className="inline-flex min-h-10 min-w-0 flex-1 items-center justify-center gap-2 rounded-xl bg-amber-400 px-4 text-xs font-black text-slate-950 shadow-sm transition hover:bg-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 sm:flex-none"
            >
              <PackagePlus className="h-4 w-4 shrink-0" />
              <span className="break-words">
                {t("products.addProduct")}
              </span>
            </button>
          ) : null}
        </div>
      </header>
    </WorkspaceTopBar>
  );
}
