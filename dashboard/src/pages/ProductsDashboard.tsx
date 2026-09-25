import {
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ProductBarcodeManager } from "@/pages/products/ProductBarcodeManager";
import { ProductsPageHeader } from "@/pages/products/ProductsPageHeader";
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
import { useCreateProductWorkflow } from "@/pages/products/create/useCreateProductWorkflow";
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
import { ProductsListSection } from "@/pages/products/list/ProductsListSection";
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
import { useProductsIdentityScopeReset } from "@/pages/products/useProductsIdentityScopeReset";
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

  const trackingDefaultsQuery =
    useTrackingDefaultsQuery({
      companyId,
      authFetch,
    });

  const createWorkflow =
    useCreateProductWorkflow({
      companyId,
      driverId,
      authFetch,
      queryClient,
      t,
      online: isOnline,
      trackingDefaults:
        trackingDefaultsQuery.data,
      trackingDefaultsError:
        trackingDefaultsQuery.isError,
      retryTrackingDefaults: () =>
        void trackingDefaultsQuery.refetch(),
      setCursor,
      setHistory,
    });

  useProductsIdentityScopeReset({
    companyId,
    driverId,
    list: {
      setCursor,
      setHistory,
      setFiltersOpen,
      setFamilyFilterSearchInput,
      setFamilyFilterSearch,
      setFamilyFilterId,
      setFamilyFilterName,
      setLifecycleFilter,
      setTrackingTypeFilter,
      setCompatibilityFilter,
      setBarcodeFilter,
      setPriceFilter,
      setLotFilter,
      setExpiryFilter,
      setSortBy,
      setSortDir,
    },
    display: {
      setDisplayPreferences,
    },
    targets: {
      setDetailProduct,
      setRenameProduct,
      setBarcodeProduct,
    },
    pricing: {
      setPriceEdit,
      setEditPackagePrice,
      setEditUnitPrice,
    },
    importScope: {
      setImportLotControlMode,
      setImportExpiryControlMode,
      setImportTrackingExpanded,
    },
    create:
      createWorkflow.identityScope,
    tracking: {
      setTrackingDefaultsOpen,
      setTrackingDefaultsLot,
      setTrackingDefaultsExpiry,
      setTrackingEdit,
      setTrackingEditLot,
      setTrackingEditExpiry,
    },
  });

  useImportTrackingDefaultsSync({
    importOpen,
    importJobId,
    defaults:
      trackingDefaultsQuery.data,
    setImportLotControlMode,
    setImportExpiryControlMode,
  });

  const page =
    productsQuery.data;
  const familyFilterOptions =
    familyFilterOptionsQuery.data
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
      <ProductsPageHeader
        isFetching={
          productsQuery.isFetching
        }
        trackingDefaultsLoading={
          trackingDefaultsQuery.isLoading
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
        canCreateSimpleProduct={
          canCreateSimpleProduct
        }
        onRefresh={() =>
          void productsQuery.refetch()
        }
        onOpenDisplayPreferences={
          openDisplayPreferences
        }
        onOpenTrackingDefaults={
          openTrackingDefaults
        }
        onOpenImport={openImport}
        onOpenAdvancedUom={() =>
          navigate(
            "/products/advanced-uom"
          )
        }
        onOpenFamilies={
          openFamilies
        }
        onOpenCreateProduct={
          createWorkflow.openCreateProduct
        }
      />

      <ProductsListSection
        filtersOpen={filtersOpen}
        toolbar={{
          searchInput,
          filtersOpen,
          hasActiveControls:
            hasProductListControls,
          onSearchInputChange:
            setSearchInput,
          onToggleFilters:
            toggleFilters,
          onClearControls:
            clearControls,
        }}
        filters={{
          familyFilterSearchInput,
          familyFilterId,
          familyFilterName,
          familyFilterOptions,
          familyOptionsError:
            familyFilterOptionsQuery.isError,
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
          onFamilySearchInputChange:
            setFamilyFilterSearchInput,
          onFamilyFilterChange:
            selectFamily,
          onRetryFamilyOptions: () =>
            void familyFilterOptionsQuery.refetch(),
          onLifecycleFilterChange:
            updateLifecycleFilter,
          onTrackingTypeFilterChange:
            updateTrackingTypeFilter,
          onCompatibilityFilterChange:
            updateCompatibilityFilter,
          onBarcodeFilterChange:
            updateBarcodeFilter,
          onPriceFilterChange:
            updatePriceFilter,
          onLotFilterChange:
            updateLotFilter,
          onExpiryFilterChange:
            updateExpiryFilter,
          onSortByChange:
            updateSortBy,
          onSortDirChange:
            updateSortDir,
        }}
        results={{
          items:
            page?.items ?? [],
          isLoading:
            productsQuery.isLoading,
          isError:
            productsQuery.isError,
          isFetching:
            productsQuery.isFetching,
          isNarrowViewport,
          pricingVisible,
          canEditPrice:
            canEditSimplePrice,
          canEditTracking:
            canManageCatalog,
          columns: visibleColumns,
          density:
            displayPreferences.density,
          tableHeaderSpacing,
          tableColumnCount:
            productTableColumnCount,
          hasPrevious:
            history.length > 0,
          hasNext: Boolean(
            page?.next_cursor
          ),
          onRetry: () =>
            void productsQuery.refetch(),
          onOpenDetails:
            openProductDetails,
          onEditPrice:
            openPriceEditor,
          onEditTracking:
            openTrackingEditor,
          onPrevious:
            goPrevious,
          onNext: () =>
            goNext(
              page?.next_cursor ??
                null
            ),
        }}
      />

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
        {...createWorkflow.modalProps}
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
