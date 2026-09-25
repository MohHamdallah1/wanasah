import {
  useEffect,
} from "react";
import {
  useQueryClient,
} from "@tanstack/react-query";
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
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  readProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import { ProductBarcodeManager } from "@/pages/products/ProductBarcodeManager";
import { ProductDetailDrawer } from "@/pages/products/ProductDetailDrawer";
import { useProductBarcodeState } from "@/pages/products/barcode/useProductBarcodeState";
import { createProductDetailActions } from "@/pages/products/detail/createProductDetailActions";
import { useProductDetailState } from "@/pages/products/detail/useProductDetailState";
import { ProductDisplayPreferencesModal } from "@/pages/products/display-preferences/ProductDisplayPreferencesModal";
import { createProductDisplayPreferenceActions } from "@/pages/products/display-preferences/createProductDisplayPreferenceActions";
import { useProductDisplayPreferencesState } from "@/pages/products/display-preferences/useProductDisplayPreferencesState";
import { ProductFamiliesManager } from "@/pages/products/ProductFamiliesManager";
import { useProductFamiliesState } from "@/pages/products/family/useProductFamiliesState";
import { ProductLifecycleManager } from "@/pages/products/ProductLifecycleManager";
import { useProductLifecycleState } from "@/pages/products/lifecycle/useProductLifecycleState";
import { CreateProductModal } from "@/pages/products/create/CreateProductModal";
import { createProductDraftActions } from "@/pages/products/create/createProductDraftActions";
import { deriveCreateProductViewState } from "@/pages/products/create/deriveCreateProductViewState";
import { productDraftStorageKey } from "@/pages/products/create/productDraftStorageKey";
import { useCreateFamilyOptionParams } from "@/pages/products/create/useCreateFamilyOptionParams";
import { useCreateFamilyOptionsQuery } from "@/pages/products/create/useCreateFamilyOptionsQuery";
import { useCreateFamilyOptionSearchDebounce } from "@/pages/products/create/useCreateFamilyOptionSearchDebounce";
import { useCreateFamilyOptionSearchState } from "@/pages/products/create/useCreateFamilyOptionSearchState";
import { useCreateProductDraftPersistence } from "@/pages/products/create/useCreateProductDraftPersistence";
import { useCreateProductMutation } from "@/pages/products/create/useCreateProductMutation";
import { useCreateTrackingDefaultsSync } from "@/pages/products/create/useCreateTrackingDefaultsSync";
import { usePackageUomsQuery } from "@/pages/products/create/usePackageUomsQuery";
import {
  useCreateProductState,
} from "@/pages/products/create/useCreateProductState";
import { ImportProductModal } from "@/pages/products/import/ImportProductModal";
import { createImportDownloads } from "@/pages/products/import/createImportDownloads";
import { createImportFileActions } from "@/pages/products/import/createImportFileActions";
import {
  deriveImportProductViewState,
} from "@/pages/products/import/helpers";
import { productImportSessionKey } from "@/pages/products/import/productImportSessionKey";
import { useImportProductCommands } from "@/pages/products/import/useImportProductCommands";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";
import { useImportProductState } from "@/pages/products/import/useImportProductState";
import { useImportProductUpload } from "@/pages/products/import/useImportProductUpload";
import { useImportSessionResume } from "@/pages/products/import/useImportSessionResume";
import { useImportTrackingDefaultsSync } from "@/pages/products/import/useImportTrackingDefaultsSync";
import { ProductsFiltersPanel } from "@/pages/products/list/ProductsFiltersPanel";
import { ProductsListResults } from "@/pages/products/list/ProductsListResults";
import { ProductsListToolbar } from "@/pages/products/list/ProductsListToolbar";
import { createProductsListActions } from "@/pages/products/list/createProductsListActions";
import { deriveProductsListViewState } from "@/pages/products/list/deriveProductsListViewState";
import { PriceEditModal } from "@/pages/products/pricing/PriceEditModal";
import { usePriceEditMutation } from "@/pages/products/pricing/usePriceEditMutation";
import { usePriceEditState } from "@/pages/products/pricing/usePriceEditState";
import { useProductsListDebounce } from "@/pages/products/list/useProductsListDebounce";
import { useProductsListParams } from "@/pages/products/list/useProductsListParams";
import { useProductsListQueries } from "@/pages/products/list/useProductsListQueries";
import { useProductsListState } from "@/pages/products/list/useProductsListState";
import { ProductRenameDialog } from "@/pages/products/ProductRenameDialog";
import { deriveProductsCapabilities } from "@/pages/products/deriveProductsCapabilities";
import { useProductRenameState } from "@/pages/products/rename/useProductRenameState";
import { ProductTrackingEditor } from "@/pages/products/ProductTrackingEditor";
import { ProductTrackingSettings } from "@/pages/products/ProductTrackingSettings";
import { createProductTrackingActions } from "@/pages/products/tracking/createProductTrackingActions";
import { useProductTrackingEditState } from "@/pages/products/tracking/useProductTrackingEditState";
import { useProductTrackingMutations } from "@/pages/products/tracking/useProductTrackingMutations";
import { useTrackingDefaultsQuery } from "@/pages/products/tracking/useTrackingDefaultsQuery";
import { useTrackingDefaultsState } from "@/pages/products/tracking/useTrackingDefaultsState";

export default function ProductsDashboard() {
  const { t, i18n } =
    useTranslation();
  const navigate =
    useNavigate();
  const authFetch =
    useAuthFetch();
  const queryClient =
    useQueryClient();
  const access =
    useInventoryAccess();
  const isOnline =
    useNetworkStatus();
  const isNarrowViewport =
    useMediaQuery(
      "(max-width: 767px)"
    );

  const companyId =
    access.data?.company_id ??
    null;
  const driverId =
    access.data?.driver_id ??
    null;

  const {
    canManageCatalog,
    canViewPricing,
    canCreateSimpleProduct,
    canImportProducts,
    canManageFamilies,
    canEditSimplePrice,
    canManageLifecycle,
  } = deriveProductsCapabilities({
    isCompanyAdmin:
      access.isCompanyAdmin,
    can: access.can,
    canAny: access.canAny,
  });

  const {
    searchInput,
    setSearchInput,
    search,
    setSearch,
    cursor,
    setCursor,
    history,
    setHistory,
    filtersOpen,
    setFiltersOpen,
    familyFilterSearchInput,
    setFamilyFilterSearchInput,
    familyFilterSearch,
    setFamilyFilterSearch,
    familyFilterId,
    setFamilyFilterId,
    familyFilterName,
    setFamilyFilterName,
    lifecycleFilter,
    setLifecycleFilter,
    trackingTypeFilter,
    setTrackingTypeFilter,
    compatibilityFilter,
    setCompatibilityFilter,
    barcodeFilter,
    setBarcodeFilter,
    priceFilter,
    setPriceFilter,
    lotFilter,
    setLotFilter,
    expiryFilter,
    setExpiryFilter,
    sortBy,
    setSortBy,
    sortDir,
    setSortDir,
    resetProductPagination,
  } = useProductsListState();

  const {
    displayPreferences,
    setDisplayPreferences,
    displayPreferencesOpen,
    setDisplayPreferencesOpen,
    openDisplayPreferences,
    closeDisplayPreferences,
  } =
    useProductDisplayPreferencesState();

  const {
    createOpen,
    setCreateOpen,
    openCreateProduct,
    createTrackingExpanded,
    setCreateTrackingExpanded,
    createAdvancedExpanded,
    setCreateAdvancedExpanded,
    draft,
    setDraft,
    restoredDraftKey,
    createFieldError,
    setCreateFieldError,
    createNameRef,
    createUnitsRef,
    createPackagePriceRef,
    createUnitPriceRef,
  } = useCreateProductState();

  const {
    trackingDefaultsOpen,
    setTrackingDefaultsOpen,
    trackingDefaultsLot,
    setTrackingDefaultsLot,
    trackingDefaultsExpiry,
    setTrackingDefaultsExpiry,
    closeTrackingDefaults,
  } = useTrackingDefaultsState();

  const {
    detailProduct,
    setDetailProduct,
    openProductDetails,
    closeProductDetails,
  } = useProductDetailState();
  const {
    renameProduct,
    setRenameProduct,
    openRenameProduct,
    closeRenameProduct,
  } = useProductRenameState();
  const {
    barcodeProduct,
    setBarcodeProduct,
    openBarcodeManager,
    closeBarcodeManager,
  } = useProductBarcodeState();
  const {
    lifecycleProduct,
    openLifecycleManager,
    closeLifecycleManager,
  } = useProductLifecycleState();
  const {
    trackingEdit,
    setTrackingEdit,
    trackingEditLot,
    setTrackingEditLot,
    trackingEditExpiry,
    setTrackingEditExpiry,
    closeTrackingEditor,
  } = useProductTrackingEditState();

  const {
    priceEdit,
    setPriceEdit,
    editPackagePrice,
    setEditPackagePrice,
    editUnitPrice,
    setEditUnitPrice,
    priceFieldError,
    setPriceFieldError,
    editPackagePriceRef,
    editUnitPriceRef,
    openPriceEditor,
    cancelPriceEdit,
    updatePackagePrice,
    updateUnitPrice,
    editDerived,
  } = usePriceEditState();

  const {
    familiesOpen,
    openFamilies,
    closeFamilies,
  } = useProductFamiliesState();
  const [
    familyOptionSearch,
    setFamilyOptionSearch,
  ] =
    useCreateFamilyOptionSearchState();

  const {
    importOpen,
    setImportOpen,
    importFile,
    setImportFile,
    importJobId,
    setImportJobId,
    importStatus,
    setImportStatus,
    importPollError,
    setImportPollError,
    mapping,
    setMapping,
    importPollKey,
    setImportPollKey,
    importLotControlMode,
    setImportLotControlMode,
    importExpiryControlMode,
    setImportExpiryControlMode,
    importTrackingExpanded,
    setImportTrackingExpanded,
    dragging,
    setDragging,
    fileRef,
  } = useImportProductState();

  const draftStorageKey =
    productDraftStorageKey(
      companyId,
      driverId
    );
  const importSessionKey =
    productImportSessionKey(
      companyId,
      driverId
    );

  useProductsListDebounce({
    searchInput,
    setSearch,
    familyFilterSearchInput,
    setFamilyFilterSearch,
    canViewPricing,
    priceFilter,
    setPriceFilter,
    setCursor,
    setHistory,
  });

  useCreateFamilyOptionSearchDebounce({
    createOpen,
    family: draft.family,
    setFamilyOptionSearch,
  });

  useCreateProductDraftPersistence({
    draftStorageKey,
    draft,
    setDraft,
    restoredDraftKey,
    t,
  });

  useImportSessionResume({
    importSessionKey,
    importJobId,
    setImportJobId,
    t,
  });

  const {
    params,
    familyFilterParams,
  } = useProductsListParams({
    search,
    cursor,
    familyFilterId,
    lifecycleFilter,
    trackingTypeFilter,
    compatibilityFilter,
    barcodeFilter,
    canViewPricing,
    priceFilter,
    lotFilter,
    expiryFilter,
    sortBy,
    sortDir,
    familyFilterSearch,
  });

  const familyOptionParams =
    useCreateFamilyOptionParams(
      familyOptionSearch
    );

  const {
    productsQuery,
    familyFilterOptionsQuery,
  } = useProductsListQueries({
    companyId,
    params,
    filtersOpen,
    familyFilterSearch,
    familyFilterParams,
    authFetch,
  });

  const familyOptionsQuery =
    useCreateFamilyOptionsQuery({
      companyId,
      createOpen,
      familyOptionSearch,
      familyOptionParams,
      authFetch,
    });

  const packageUomsQuery =
    usePackageUomsQuery({
      authFetch,
    });

  const trackingDefaultsQuery =
    useTrackingDefaultsQuery({
      companyId,
      authFetch,
    });

  useEffect(() => {
    const nextDisplayPreferences =
      companyId !== null &&
      driverId !== null
        ? readProductDisplayPreferences(
            companyId,
            driverId
          )
        : readProductDisplayPreferences(
            Number.NaN,
            Number.NaN
          );

    setDisplayPreferences(
      nextDisplayPreferences
    );
    setCursor(null);
    setHistory([]);
    setFiltersOpen(false);
    setFamilyFilterSearchInput("");
    setFamilyFilterSearch("");
    setFamilyFilterId("");
    setFamilyFilterName("");
    setLifecycleFilter("");
    setTrackingTypeFilter("");
    setCompatibilityFilter("");
    setBarcodeFilter("");
    setPriceFilter("");
    setLotFilter("");
    setExpiryFilter("");
    setSortBy(
      nextDisplayPreferences.defaultSort
        .field
    );
    setSortDir(
      nextDisplayPreferences.defaultSort
        .direction
    );
    setDetailProduct(null);
    setRenameProduct(null);
    setBarcodeProduct(null);
    setPriceEdit(null);
    setEditPackagePrice("");
    setEditUnitPrice("");
    setImportLotControlMode(null);
    setImportExpiryControlMode(null);
    setImportTrackingExpanded(false);
    setCreateTrackingExpanded(false);
    setCreateAdvancedExpanded(false);
    setTrackingDefaultsOpen(false);
    setTrackingDefaultsLot(null);
    setTrackingDefaultsExpiry(null);
    setTrackingEdit(null);
    setTrackingEditLot(null);
    setTrackingEditExpiry(null);
    setFamilyOptionSearch("");
  }, [
    companyId,
    driverId,
    setBarcodeFilter,
    setCompatibilityFilter,
    setBarcodeProduct,
    setCreateAdvancedExpanded,
    setCreateTrackingExpanded,
    setCursor,
    setDetailProduct,
    setDisplayPreferences,
    setEditPackagePrice,
    setEditUnitPrice,
    setExpiryFilter,
    setFamilyFilterId,
    setFamilyFilterName,
    setFamilyFilterSearch,
    setFamilyFilterSearchInput,
    setFamilyOptionSearch,
    setFiltersOpen,
    setHistory,
    setImportExpiryControlMode,
    setImportLotControlMode,
    setImportTrackingExpanded,
    setLifecycleFilter,
    setLotFilter,
    setPriceEdit,
    setPriceFilter,
    setRenameProduct,
    setSortBy,
    setSortDir,
    setTrackingDefaultsExpiry,
    setTrackingDefaultsLot,
    setTrackingDefaultsOpen,
    setTrackingEdit,
    setTrackingEditExpiry,
    setTrackingEditLot,
    setTrackingTypeFilter,
  ]);

  useImportTrackingDefaultsSync({
    importOpen,
    importJobId,
    defaults:
      trackingDefaultsQuery.data,
    setImportLotControlMode,
    setImportExpiryControlMode,
  });

  useCreateTrackingDefaultsSync({
    createOpen,
    defaults:
      trackingDefaultsQuery.data,
    setDraft,
  });

  const page =
    productsQuery.data;
  const familyFilterOptions =
    familyFilterOptionsQuery.data
      ?.items ?? [];
  const familyOptions =
    familyOptionsQuery.data
      ?.items ?? [];
  const packageUoms =
    packageUomsQuery.data
      ?.items ?? [];
  const {
    pricingVisible,
    visibleColumns,
    productTableColumnCount,
    tableHeaderSpacing,
    hasProductListControls,
  } = deriveProductsListViewState({
    page,
    canViewPricing,
    displayPreferences,
    familyFilterId,
    lifecycleFilter,
    trackingTypeFilter,
    compatibilityFilter,
    barcodeFilter,
    priceFilter,
    lotFilter,
    expiryFilter,
    sortBy,
    sortDir,
  });

  const {
    toggleFilters,
    clearControls,
    selectFamily,
    updateLifecycleFilter,
    updateTrackingTypeFilter,
    updateCompatibilityFilter,
    updateBarcodeFilter,
    updatePriceFilter,
    updateLotFilter,
    updateExpiryFilter,
    updateSortBy,
    updateSortDir,
    goPrevious,
    goNext,
  } = createProductsListActions({
    familyFilterOptions,
    displayPreferences,
    cursor,
    history,
    setFiltersOpen,
    setFamilyFilterId,
    setFamilyFilterName,
    setFamilyFilterSearchInput,
    setLifecycleFilter,
    setTrackingTypeFilter,
    setCompatibilityFilter,
    setBarcodeFilter,
    setPriceFilter,
    setLotFilter,
    setExpiryFilter,
    setSortBy,
    setSortDir,
    setCursor,
    setHistory,
    resetProductPagination,
  });

  const {
    draftDerived,
    trackingUsesCompanyDefaults:
      createTrackingUsesCompanyDefaults,
  } = deriveCreateProductViewState({
    draft,
    defaults:
      trackingDefaultsQuery.data,
  });

  const {
    progress: importProgress,
    trackingUsesCompanyDefaults:
      importTrackingUsesCompanyDefaults,
  } = deriveImportProductViewState(
    importStatus,
    trackingDefaultsQuery.data,
    importLotControlMode,
    importExpiryControlMode
  );

  const {
    updateName:
      updateCreateName,
    updateFamily:
      updateCreateFamily,
    updateHasPackage:
      updateCreateHasPackage,
    updatePackageUom:
      updateCreatePackageUom,
    updateUnitsPerPackage:
      updateCreateUnitsPerPackage,
    updatePackagePrice:
      updateCreatePackagePrice,
    updateUnitPrice:
      updateCreateUnitPrice,
    toggleAdvanced:
      toggleCreateAdvanced,
    expandTracking:
      expandCreateTracking,
    updateLotControlMode:
      updateCreateLotControlMode,
    updateExpiryControlMode:
      updateCreateExpiryControlMode,
    resetTracking:
      resetCreateTracking,
    updateUnitBarcode:
      updateCreateUnitBarcode,
    copyBarcode:
      copyCreateBarcode,
    updatePackageBarcode:
      updateCreatePackageBarcode,
  } = createProductDraftActions({
    createFieldError,
    trackingDefaults:
      trackingDefaultsQuery.data,
    setDraft,
    setCreateFieldError,
    setCreateAdvancedExpanded,
    setCreateTrackingExpanded,
    t,
  });

  const {
    openTrackingDefaults,
    openTrackingEditor,
  } = createProductTrackingActions({
    defaults:
      trackingDefaultsQuery.data,
    setTrackingDefaultsOpen,
    setTrackingDefaultsLot,
    setTrackingDefaultsExpiry,
    setTrackingEdit,
    setTrackingEditLot,
    setTrackingEditExpiry,
    t,
  });

  const {
    renameProductFromDetails,
    editPriceFromDetails,
    editTrackingFromDetails,
    manageLifecycleFromDetails,
    manageBarcodesFromDetails,
    manageAdvancedUomFromDetails,
  } = createProductDetailActions({
    closeProductDetails,
    openRenameProduct,
    openPriceEditor,
    openTrackingEditor,
    openLifecycleManager,
    openBarcodeManager,
    navigate,
  });

  const {
    saveDisplayPreferences,
  } = createProductDisplayPreferenceActions({
    companyId,
    driverId,
    setDisplayPreferences,
    setSortBy,
    setSortDir,
    resetProductPagination,
    setDisplayPreferencesOpen,
    t,
  });

  const {
    trackingDefaultsMutation,
    trackingMutation,
  } = useProductTrackingMutations({
    trackingDefaultsLot,
    trackingDefaultsExpiry,
    trackingEdit,
    trackingEditLot,
    trackingEditExpiry,
    companyId,
    driverId,
    authFetch,
    setTrackingDefaultsOpen,
    setTrackingDefaultsLot,
    setTrackingDefaultsExpiry,
    importJobId,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setTrackingEdit,
    setTrackingEditLot,
    setTrackingEditExpiry,
    queryClient,
    t,
  });

  const {
    createMutation,
    submitCreate,
    cancelCreate,
  } = useCreateProductMutation({
    draft,
    familyOptions,
    packageUoms,
    companyId,
    driverId,
    authFetch,
    draftStorageKey,
    setDraft,
    setCreateFieldError,
    setCreateTrackingExpanded,
    setCreateAdvancedExpanded,
    setCreateOpen,
    setCursor,
    setHistory,
    queryClient,
    t,
    createNameRef,
    createUnitsRef,
    createPackagePriceRef,
    createUnitPriceRef,
  });

  const {
    priceMutation,
    submitPriceEdit,
    closePriceEdit,
  } = usePriceEditMutation({
    priceEdit,
    editPackagePrice,
    editUnitPrice,
    companyId,
    driverId,
    authFetch,
    setPriceEdit,
    setPriceFieldError,
    queryClient,
    t,
    editPackagePriceRef,
    editUnitPriceRef,
  });

  const {
    importMutation,
    startImport,
  } = useImportProductUpload({
    importFile,
    importLotControlMode,
    importExpiryControlMode,
    companyId,
    driverId,
    authFetch,
    setImportJobId,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setImportStatus,
    setImportPollError,
    importSessionKey,
    t,
  });

  const {
    mappingMutation,
    retryImportMutation,
    updateMapping,
    submitMapping,
    retryImport,
  } = useImportProductCommands({
    importJobId,
    mapping,
    setMapping,
    authFetch,
    setImportPollError,
    setImportStatus,
    setImportPollKey,
    t,
  });

  const {
    retryPoll,
  } = useImportProductPolling({
    importJobId,
    importPollKey,
    setImportPollKey,
    authFetch,
    queryClient,
    t,
    isOnline,
    setImportPollError,
    setImportStatus,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setMapping,
  });

  const {
    chooseFile,
    resetImport,
    openImport,
    closeImport,
    expandImportTracking,
    resetImportTracking,
    completeImport,
  } = createImportFileActions({
    importSessionKey,
    importing:
      importMutation.isPending,
    trackingDefaultsQuery,
    fileRef,
    setImportOpen,
    setImportFile,
    setImportJobId,
    setImportStatus,
    setImportPollError,
    setMapping,
    setImportLotControlMode,
    setImportExpiryControlMode,
    setImportTrackingExpanded,
    t,
  });

  const {
    downloadErrorReport,
    downloadTemplate,
  } = createImportDownloads({
    importJobId,
    authFetch,
    t,
    i18n,
  });

  return (
    <div
      className="products-a11y-scope flex min-h-0 flex-1 flex-col overflow-hidden"
      dir={i18n.dir()}
    >
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
              onClick={() =>
                void productsQuery.refetch()
              }
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-600"
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  productsQuery.isFetching
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
                openDisplayPreferences
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
                  trackingDefaultsQuery.isLoading
                }
                onClick={
                  openTrackingDefaults
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
                onClick={
                  openImport
                }
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
                  onClick={() =>
                    navigate(
                      "/products/advanced-uom"
                    )
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
                onClick={
                  openFamilies
                }
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
                  openCreateProduct
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

      <section className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-[22px] border border-white/70 bg-white/85 shadow-sm backdrop-blur-xl sm:rounded-[26px]">
        <div className="shrink-0 border-b border-slate-100 p-4">
          <ProductsListToolbar
            searchInput={searchInput}
            filtersOpen={filtersOpen}
            hasActiveControls={
              hasProductListControls
            }
            onSearchInputChange={
              setSearchInput
            }
            onToggleFilters={
              toggleFilters
            }
            onClearControls={
              clearControls
            }
          />

          {filtersOpen ? (
            <ProductsFiltersPanel
              familyFilterSearchInput={
                familyFilterSearchInput
              }
              familyFilterId={
                familyFilterId
              }
              familyFilterName={
                familyFilterName
              }
              familyFilterOptions={
                familyFilterOptions
              }
              familyOptionsError={
                familyFilterOptionsQuery.isError
              }
              lifecycleFilter={
                lifecycleFilter
              }
              trackingTypeFilter={
                trackingTypeFilter
              }
              compatibilityFilter={
                compatibilityFilter
              }
              barcodeFilter={
                barcodeFilter
              }
              canViewPricing={
                canViewPricing
              }
              priceFilter={
                priceFilter
              }
              lotFilter={lotFilter}
              expiryFilter={
                expiryFilter
              }
              sortBy={sortBy}
              sortDir={sortDir}
              onFamilySearchInputChange={
                setFamilyFilterSearchInput
              }
              onFamilyFilterChange={
                selectFamily
              }
              onRetryFamilyOptions={() =>
                void familyFilterOptionsQuery.refetch()
              }
              onLifecycleFilterChange={
                updateLifecycleFilter
              }
              onTrackingTypeFilterChange={
                updateTrackingTypeFilter
              }
              onCompatibilityFilterChange={
                updateCompatibilityFilter
              }
              onBarcodeFilterChange={
                updateBarcodeFilter
              }
              onPriceFilterChange={
                updatePriceFilter
              }
              onLotFilterChange={
                updateLotFilter
              }
              onExpiryFilterChange={
                updateExpiryFilter
              }
              onSortByChange={
                updateSortBy
              }
              onSortDirChange={
                updateSortDir
              }
            />
          ) : null}
        </div>

        <ProductsListResults
          items={
            page?.items ?? []
          }
          isLoading={
            productsQuery.isLoading
          }
          isError={
            productsQuery.isError
          }
          isFetching={
            productsQuery.isFetching
          }
          isNarrowViewport={
            isNarrowViewport
          }
          pricingVisible={
            pricingVisible
          }
          canEditPrice={
            canEditSimplePrice
          }
          canEditTracking={
            canManageCatalog
          }
          columns={
            visibleColumns
          }
          density={
            displayPreferences
              .density
          }
          tableHeaderSpacing={
            tableHeaderSpacing
          }
          tableColumnCount={
            productTableColumnCount
          }
          hasPrevious={
            history.length > 0
          }
          hasNext={Boolean(
            page?.next_cursor
          )}
          onRetry={() =>
            void productsQuery.refetch()
          }
          onOpenDetails={
            openProductDetails
          }
          onEditPrice={
            openPriceEditor
          }
          onEditTracking={
            openTrackingEditor
          }
          onPrevious={
            goPrevious
          }
          onNext={() =>
            goNext(
              page?.next_cursor ??
                null
            )
          }
        />
      </section>

      <ProductDisplayPreferencesModal
        open={displayPreferencesOpen}
        preferences={
          displayPreferences
        }
        pricingAvailable={
          canViewPricing
        }
        onClose={
          closeDisplayPreferences
        }
        onSave={
          saveDisplayPreferences
        }
      />

      <ProductDetailDrawer
        product={detailProduct}
        pricingVisible={pricingVisible}
        canEditPrice={
          canEditSimplePrice
        }
        canRenameProduct={
          canManageCatalog
        }
        canEditTracking={
          canManageCatalog
        }
        canManageBarcodes={
          canManageCatalog
        }
        canManageLifecycle={
          canManageLifecycle
        }
        canManageAdvancedUom={
          canManageCatalog
        }
        detailSections={
          displayPreferences
            .detailSections
        }
        onClose={
          closeProductDetails
        }
        onRenameProduct={
          renameProductFromDetails
        }
        onEditPrice={
          editPriceFromDetails
        }
        onEditTracking={
          editTrackingFromDetails
        }
        onManageLifecycle={
          manageLifecycleFromDetails
        }
        onManageBarcodes={
          manageBarcodesFromDetails
        }
        onManageAdvancedUom={
          manageAdvancedUomFromDetails
        }
      />

      <ProductRenameDialog
        product={renameProduct}
        companyId={companyId}
        driverId={driverId}
        onClose={
          closeRenameProduct
        }
        onRenamed={
          closeRenameProduct
        }
      />

      <ProductLifecycleManager
        product={lifecycleProduct}
        onClose={
          closeLifecycleManager
        }
        onChanged={async () => {
          await queryClient.invalidateQueries(
            {
              queryKey: [
                "simple-products",
              ],
            }
          );
        }}
      />

      <ProductBarcodeManager
        product={barcodeProduct}
        companyId={companyId}
        driverId={driverId}
        onClose={
          closeBarcodeManager
        }
        onChanged={async () => {
          await queryClient.invalidateQueries(
            {
              queryKey: [
                "simple-products",
              ],
            }
          );
        }}
      />

      {trackingDefaultsOpen &&
      trackingDefaultsLot &&
      trackingDefaultsExpiry &&
      trackingDefaultsQuery.data ? (
        <ProductTrackingSettings
          open={trackingDefaultsOpen}
          lotControlMode={
            trackingDefaultsLot
          }
          expiryControlMode={
            trackingDefaultsExpiry
          }
          lotControlSource={
            trackingDefaultsQuery.data
              .lot_control_source
          }
          expiryControlSource={
            trackingDefaultsQuery.data
              .expiry_control_source
          }
          saving={
            trackingDefaultsMutation.isPending
          }
          online={isOnline}
          onLotControlModeChange={
            setTrackingDefaultsLot
          }
          onExpiryControlModeChange={
            setTrackingDefaultsExpiry
          }
          onClose={
            closeTrackingDefaults
          }
          onSave={() =>
            trackingDefaultsMutation.mutate()
          }
        />
      ) : null}

      {trackingEdit &&
      trackingEditLot &&
      trackingEditExpiry ? (
        <ProductTrackingEditor
          product={trackingEdit}
          lotControlMode={
            trackingEditLot
          }
          expiryControlMode={
            trackingEditExpiry
          }
          saving={
            trackingMutation.isPending
          }
          online={isOnline}
          onLotControlModeChange={
            setTrackingEditLot
          }
          onExpiryControlModeChange={
            setTrackingEditExpiry
          }
          onClose={
            closeTrackingEditor
          }
          onSave={() =>
            trackingMutation.mutate()
          }
        />
      ) : null}

      <CreateProductModal
        open={createOpen}
        saving={
          createMutation.isPending
        }
        online={isOnline}
        draft={draft}
        createFieldError={
          createFieldError
        }
        familyOptions={
          familyOptions
        }
        familyOptionsError={
          familyOptionsQuery.isError
        }
        packageUoms={packageUoms}
        packageUomsLoading={
          packageUomsQuery.isLoading
        }
        packageUomsError={
          packageUomsQuery.isError
        }
        trackingDefaultsError={
          trackingDefaultsQuery.isError
        }
        trackingUsesCompanyDefaults={
          createTrackingUsesCompanyDefaults
        }
        draftDerived={
          draftDerived
        }
        createAdvancedExpanded={
          createAdvancedExpanded
        }
        createTrackingExpanded={
          createTrackingExpanded
        }
        createNameRef={
          createNameRef
        }
        createUnitsRef={
          createUnitsRef
        }
        createPackagePriceRef={
          createPackagePriceRef
        }
        createUnitPriceRef={
          createUnitPriceRef
        }
        onCancel={cancelCreate}
        onSubmit={submitCreate}
        onNameChange={
          updateCreateName
        }
        onFamilyChange={
          updateCreateFamily
        }
        onRetryFamilyOptions={() =>
          void familyOptionsQuery.refetch()
        }
        onRetryTrackingDefaults={() =>
          void trackingDefaultsQuery.refetch()
        }
        onHasPackageChange={
          updateCreateHasPackage
        }
        onRetryPackageUoms={() =>
          void packageUomsQuery.refetch()
        }
        onPackageUomChange={
          updateCreatePackageUom
        }
        onUnitsPerPackageChange={
          updateCreateUnitsPerPackage
        }
        onPackagePriceChange={
          updateCreatePackagePrice
        }
        onUnitPriceChange={
          updateCreateUnitPrice
        }
        onToggleAdvanced={
          toggleCreateAdvanced
        }
        onExpandTracking={
          expandCreateTracking
        }
        onLotControlModeChange={
          updateCreateLotControlMode
        }
        onExpiryControlModeChange={
          updateCreateExpiryControlMode
        }
        onResetTracking={
          resetCreateTracking
        }
        onUnitBarcodeChange={
          updateCreateUnitBarcode
        }
        onCopyBarcode={
          copyCreateBarcode
        }
        onPackageBarcodeChange={
          updateCreatePackageBarcode
        }
      />

      <PriceEditModal
        product={priceEdit}
        saving={
          priceMutation.isPending
        }
        online={isOnline}
        packagePrice={
          editPackagePrice
        }
        unitPrice={
          editUnitPrice
        }
        fieldError={
          priceFieldError
        }
        independentPrices={Boolean(
          editDerived?.independent
        )}
        packagePriceRef={
          editPackagePriceRef
        }
        unitPriceRef={
          editUnitPriceRef
        }
        onClose={
          closePriceEdit
        }
        onCancel={
          cancelPriceEdit
        }
        onSubmit={submitPriceEdit}
        onPackagePriceChange={
          updatePackagePrice
        }
        onUnitPriceChange={
          updateUnitPrice
        }
      />

      <ProductFamiliesManager
        isOpen={familiesOpen}
        companyId={companyId}
        driverId={driverId}
        onClose={
          closeFamilies
        }
      />

      <ImportProductModal
        open={importOpen}
        importing={
          importMutation.isPending
        }
        online={isOnline}
        jobId={importJobId}
        status={importStatus}
        pollError={
          importPollError
        }
        mapping={mapping}
        progress={importProgress}
        file={importFile}
        dragging={dragging}
        lotControlMode={
          importLotControlMode
        }
        expiryControlMode={
          importExpiryControlMode
        }
        trackingDefaultsLoading={
          trackingDefaultsQuery.isLoading
        }
        trackingDefaultsError={
          trackingDefaultsQuery.isError
        }
        trackingUsesCompanyDefaults={
          importTrackingUsesCompanyDefaults
        }
        trackingExpanded={
          importTrackingExpanded
        }
        mappingPending={
          mappingMutation.isPending
        }
        retryPending={
          retryImportMutation.isPending
        }
        fileRef={fileRef}
        onClose={closeImport}
        onDownloadTemplate={
          downloadTemplate
        }
        onRetryTrackingDefaults={() =>
          void trackingDefaultsQuery.refetch()
        }
        onExpandTracking={
          expandImportTracking
        }
        onLotControlModeChange={
          setImportLotControlMode
        }
        onExpiryControlModeChange={
          setImportExpiryControlMode
        }
        onResetTracking={
          resetImportTracking
        }
        onChooseFile={chooseFile}
        onDraggingChange={
          setDragging
        }
        onStartImport={
          startImport
        }
        onRetryPoll={retryPoll}
        onMappingChange={
          updateMapping
        }
        onSubmitMapping={
          submitMapping
        }
        onDownloadErrorReport={
          downloadErrorReport
        }
        onResetImport={resetImport}
        onRetryImport={
          retryImport
        }
        onCompletedClose={
          completeImport
        }
      />
    </div>
  );
}
