import {
  Boxes,
  FileSpreadsheet,
  FolderTree,
  LockKeyhole,
  PackagePlus,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";

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
    <header className="shrink-0 rounded-[22px] border border-white/70 bg-white/85 px-4 py-4 shadow-sm backdrop-blur-xl sm:rounded-[26px] sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0 flex flex-1 items-center gap-3 sm:flex-none">
          <span className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-slate-950 text-white">
            <Boxes className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <h1 className="break-words text-xl font-black text-slate-950">
              {t(
                "products.title"
              )}
            </h1>
            <p className="mt-0.5 break-words text-xs font-semibold text-slate-500">
              {t(
                "products.subtitle"
              )}
            </p>
          </div>
        </div>

        <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:flex-wrap sm:items-center [&>button]:min-w-0 [&>button]:justify-center [&>button]:whitespace-normal [&>button]:text-center">
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-600"
          >
            <RefreshCw
              className={`h-4 w-4 ${
                isFetching
                  ? "animate-spin"
                  : ""
              }`}
            />
            {t(
              "common.refresh"
            )}
          </button>

          <button
            type="button"
            onClick={
              onOpenDisplayPreferences
            }
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
          >
            <SlidersHorizontal className="h-4 w-4" />
            {t(
              "products.displayPreferences.action"
            )}
          </button>

          {canManageCatalog ? (
            <button
              type="button"
              disabled={
                trackingDefaultsLoading
              }
              onClick={
                onOpenTrackingDefaults
              }
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 disabled:opacity-40"
            >
              <Settings2 className="h-4 w-4" />
              {t(
                "products.trackingSettings.action"
              )}
            </button>
          ) : null}

          {canImportProducts ? (
            <button
              type="button"
              onClick={onOpenImport}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
            >
              <FileSpreadsheet className="h-4 w-4" />
              {t(
                "products.importFile"
              )}
            </button>
          ) : null}

          {canManageCatalog ? (
            <>
              <button
                type="button"
                onClick={
                  onOpenAdvancedUom
                }
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
              >
                <Settings2 className="h-4 w-4" />
                {t(
                  "products.advancedUom.action"
                )}
              </button>

              <button
                type="button"
                disabled
                title={t(
                  "products.advancedPricingHint"
                )}
                className="inline-flex cursor-not-allowed items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-black text-slate-400"
              >
                <LockKeyhole className="h-4 w-4" />
                {t(
                  "products.advancedPricing"
                )}
              </button>
            </>
          ) : null}

          {canManageFamilies ? (
            <button
              type="button"
              onClick={onOpenFamilies}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
            >
              <FolderTree className="h-4 w-4" />
              {t(
                "products.families"
              )}
            </button>
          ) : null}

          {canCreateSimpleProduct ? (
            <button
              type="button"
              onClick={
                onOpenCreateProduct
              }
              className="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white"
            >
              <PackagePlus className="h-4 w-4" />
              {t(
                "products.addProduct"
              )}
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
