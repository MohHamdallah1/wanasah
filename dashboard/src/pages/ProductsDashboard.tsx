import {
  useEffect,
  useRef,
  useState,
} from "react";
import {
  useMutation,
  useQuery,
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
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  readProductDisplayPreferences,
  writeProductDisplayPreferences,
  type ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  deriveExactMoneyPair,
} from "@/lib/exactMoney";
import {
  parsePackageUoms,
  parseProductTrackingDefaults,
  parseProductTrackingMutation,
  type ProductTrackingMode,
  type SimpleProduct,
} from "@/pages/products/contracts";
import { ProductBarcodeManager } from "@/pages/products/ProductBarcodeManager";
import { ProductDetailDrawer } from "@/pages/products/ProductDetailDrawer";
import { ProductDisplayPreferencesModal } from "@/pages/products/ProductDisplayPreferences";
import { ProductFamiliesManager } from "@/pages/products/ProductFamiliesManager";
import { ProductLifecycleManager } from "@/pages/products/ProductLifecycleManager";
import { CreateProductModal } from "@/pages/products/create/CreateProductModal";
import { useCreateFamilyOptionParams } from "@/pages/products/create/useCreateFamilyOptionParams";
import { useCreateFamilyOptionsQuery } from "@/pages/products/create/useCreateFamilyOptionsQuery";
import { useCreateFamilyOptionSearchDebounce } from "@/pages/products/create/useCreateFamilyOptionSearchDebounce";
import { useCreateFamilyOptionSearchState } from "@/pages/products/create/useCreateFamilyOptionSearchState";
import { useCreateProductDraftPersistence } from "@/pages/products/create/useCreateProductDraftPersistence";
import { useCreateProductMutation } from "@/pages/products/create/useCreateProductMutation";
import {
  useCreateProductState,
} from "@/pages/products/create/useCreateProductState";
import { ImportProductModal } from "@/pages/products/import/ImportProductModal";
import { createImportDownloads } from "@/pages/products/import/createImportDownloads";
import { createImportFileActions } from "@/pages/products/import/createImportFileActions";
import {
  calculateImportProgress,
  usesCompanyImportTrackingDefaults,
} from "@/pages/products/import/helpers";
import { useImportProductCommands } from "@/pages/products/import/useImportProductCommands";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";
import { useImportProductState } from "@/pages/products/import/useImportProductState";
import { useImportProductUpload } from "@/pages/products/import/useImportProductUpload";
import { useImportSessionResume } from "@/pages/products/import/useImportSessionResume";
import { ProductsFiltersPanel } from "@/pages/products/list/ProductsFiltersPanel";
import { ProductsListResults } from "@/pages/products/list/ProductsListResults";
import { ProductsListToolbar } from "@/pages/products/list/ProductsListToolbar";
import { PriceEditModal } from "@/pages/products/pricing/PriceEditModal";
import { usePriceEditMutation } from "@/pages/products/pricing/usePriceEditMutation";
import { usePriceEditState } from "@/pages/products/pricing/usePriceEditState";
import { useProductsListDebounce } from "@/pages/products/list/useProductsListDebounce";
import { useProductsListParams } from "@/pages/products/list/useProductsListParams";
import { useProductsListQueries } from "@/pages/products/list/useProductsListQueries";
import { useProductsListState } from "@/pages/products/list/useProductsListState";
import { ProductRenameDialog } from "@/pages/products/ProductRenameDialog";
import { ProductTrackingEditor } from "@/pages/products/ProductTrackingEditor";
import { ProductTrackingSettings } from "@/pages/products/ProductTrackingSettings";
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

  const canManageCatalog =
    access.isCompanyAdmin ||
    access.canAny(
      "catalog.manage"
    );
  const canViewPricing =
    access.isCompanyAdmin ||
    access.canAny(
      "pricing.view"
    );

  const canPublishCatalog =
    access.isCompanyAdmin ||
    access.canAny(
      "catalog.publish"
    );
  const canManagePricing =
    access.isCompanyAdmin ||
    access.canAny(
      "pricing.manage"
    );
  const canCreateSimpleProduct =
    access.isCompanyAdmin ||
    (canManageCatalog &&
      canPublishCatalog &&
      canManagePricing);
  const canImportProducts =
    canCreateSimpleProduct;
  const canManageFamilies =
    canManageCatalog;
  const canEditSimplePrice =
    canManagePricing;
  const canManageLifecycle =
    access.isCompanyAdmin ||
    access.can(
      "catalog.retire"
    ) ||
    access.can(
      "catalog.restore"
    ) ||
    access.can(
      "catalog.archive"
    ) ||
    access.can(
      "catalog.hold"
    );

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

  const [
    displayPreferences,
    setDisplayPreferences,
  ] =
    useState<ProductDisplayPreferences>(
      () =>
        readProductDisplayPreferences(
          Number(
            localStorage.getItem(
              "company_id"
            )
          ),
          Number(
            localStorage.getItem(
              "driver_id"
            )
          )
        )
    );
  const [
    displayPreferencesOpen,
    setDisplayPreferencesOpen,
  ] = useState(false);

  const {
    createOpen,
    setCreateOpen,
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
  } = useTrackingDefaultsState();

  const [
    detailProduct,
    setDetailProduct,
  ] = useState<SimpleProduct | null>(
    null
  );
  const [
    renameProduct,
    setRenameProduct,
  ] = useState<SimpleProduct | null>(
    null
  );
  const [
    barcodeProduct,
    setBarcodeProduct,
  ] = useState<SimpleProduct | null>(
    null
  );
  const [
    lifecycleProduct,
    setLifecycleProduct,
  ] = useState<SimpleProduct | null>(
    null
  );
  const {
    trackingEdit,
    setTrackingEdit,
    trackingEditLot,
    setTrackingEditLot,
    trackingEditExpiry,
    setTrackingEditExpiry,
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

  const [
    familiesOpen,
    setFamiliesOpen,
  ] = useState(false);
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
    companyId && driverId
      ? `wanasah:product-draft:v2:${companyId}:${driverId}`
      : null;
  const importSessionKey =
    companyId && driverId
      ? `wanasah:product-import:v1:${companyId}:${driverId}`
      : null;

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
    useQuery({
      queryKey: [
        "simple-product-package-uoms",
      ],
      queryFn: async ({
        signal,
      }) =>
        parsePackageUoms(
          await authFetch(
            "/simple-products/package-uoms",
            { signal }
          )
        ),
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
  }, [companyId, driverId]);

  useEffect(() => {
    const defaults =
      trackingDefaultsQuery.data;
    if (
      !importOpen ||
      importJobId ||
      !defaults
    ) {
      return;
    }
    setImportLotControlMode(
      (current) =>
        current ??
        defaults.lot_control_mode
    );
    setImportExpiryControlMode(
      (current) =>
        current ??
        defaults.expiry_control_mode
    );
  }, [
    importOpen,
    importJobId,
    trackingDefaultsQuery.data,
  ]);

  useEffect(() => {
    const defaults =
      trackingDefaultsQuery.data;
    if (
      !createOpen ||
      !defaults
    ) {
      return;
    }
    setDraft((current) => ({
      ...current,
      lot_control_mode:
        current.lot_control_mode ??
        defaults.lot_control_mode,
      expiry_control_mode:
        current.expiry_control_mode ??
        defaults.expiry_control_mode,
    }));
  }, [
    createOpen,
    trackingDefaultsQuery.data,
  ]);

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
  const pricingVisible =
    Boolean(
      page?.pricing_visible &&
        canViewPricing
    );
  const visibleColumns =
    displayPreferences.columns;
  const productTableColumnCount =
    2 +
    Number(
      visibleColumns.package
    ) +
    Number(
      visibleColumns.unitsPerPackage
    ) +
    Number(
      visibleColumns.tracking
    ) +
    Number(
      visibleColumns.lifecycle
    ) +
    Number(
      visibleColumns.unitBarcode
    ) +
    Number(
      visibleColumns.packageBarcode
    ) +
    Number(
      pricingVisible &&
        visibleColumns.packagePrice
    ) +
    Number(
      pricingVisible &&
        visibleColumns.unitPrice
    );
  const tableHeaderSpacing =
    displayPreferences.density ===
    "compact"
      ? "px-4 py-2"
      : "px-5 py-3";
  const hasProductListControls =
    Boolean(
      familyFilterId ||
        lifecycleFilter ||
        trackingTypeFilter ||
        compatibilityFilter ||
        barcodeFilter ||
        (canViewPricing &&
          priceFilter) ||
        lotFilter ||
        expiryFilter ||
        sortBy !==
          displayPreferences.defaultSort
            .field ||
        sortDir !==
          displayPreferences.defaultSort
            .direction
    );

  const importTrackingUsesCompanyDefaults =
    usesCompanyImportTrackingDefaults(
      trackingDefaultsQuery.data,
      importLotControlMode,
      importExpiryControlMode
    );

  const createTrackingUsesCompanyDefaults =
    Boolean(
      trackingDefaultsQuery.data &&
        draft.lot_control_mode &&
        draft.expiry_control_mode &&
        draft.lot_control_mode ===
          trackingDefaultsQuery.data
            .lot_control_mode &&
        draft.expiry_control_mode ===
          trackingDefaultsQuery.data
            .expiry_control_mode
    );

  const operationScope = (
    operation: string,
    target:
      | string
      | number = "default"
  ) => {
    if (
      !companyId ||
      !driverId
    ) {
      throw new Error(
        "IDENTITY_NOT_READY"
      );
    }
    return durableScope(
      companyId,
      driverId,
      operation,
      target
    );
  };

  const openTrackingDefaults =
    () => {
      const defaults =
        trackingDefaultsQuery.data;
      if (!defaults) {
        toast.error(
          t(
            "products.errors.trackingDefaultsLoad"
          )
        );
        return;
      }
      setTrackingDefaultsLot(
        defaults.lot_control_mode
      );
      setTrackingDefaultsExpiry(
        defaults.expiry_control_mode
      );
      setTrackingDefaultsOpen(true);
    };

  const saveDisplayPreferences = (
    next: ProductDisplayPreferences
  ) => {
    if (
      companyId === null ||
      driverId === null ||
      !writeProductDisplayPreferences(
        companyId,
        driverId,
        next
      )
    ) {
      toast.error(
        t(
          "products.displayPreferences.saveFailed"
        )
      );
      return;
    }

    setDisplayPreferences(next);
    setSortBy(
      next.defaultSort.field
    );
    setSortDir(
      next.defaultSort.direction
    );
    resetProductPagination();
    setDisplayPreferencesOpen(false);
    toast.success(
      t(
        "products.displayPreferences.saved"
      )
    );
  };

  const openTrackingEditor = (
    product: SimpleProduct
  ) => {
    setTrackingEdit(product);
    setTrackingEditLot(
      product.lot_control_mode
    );
    setTrackingEditExpiry(
      product.expiry_control_mode
    );
  };

  const {
    trackingDefaultsMutation,
    trackingMutation,
  } = useProductTrackingMutations({
    trackingDefaultsLot,
    trackingDefaultsExpiry,
    trackingEdit,
    trackingEditLot,
    trackingEditExpiry,
    operationScope,
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
    operationScope,
    authFetch,
    draftStorageKey,
    companyId,
    driverId,
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
    operationScope,
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
    operationScope,
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

  const draftDerived =
    deriveExactMoneyPair(
      draft.has_package,
      draft.units_per_package,
      draft.package_price,
      draft.unit_price
    );

  const importProgress =
    calculateImportProgress(
      importStatus
    );


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
              onClick={() =>
                setDisplayPreferencesOpen(
                  true
                )
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
                onClick={() =>
                  setFamiliesOpen(
                    true
                  )
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
                onClick={() => {
                  setCreateTrackingExpanded(
                    false
                  );
                  setCreateAdvancedExpanded(
                    false
                  );
                  setCreateOpen(
                    true
                  );
                }}
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
            onToggleFilters={() =>
              setFiltersOpen(
                (current) =>
                  !current
              )
            }
            onClearControls={() => {
              setFamilyFilterId("");
              setFamilyFilterName("");
              setFamilyFilterSearchInput("");
              setLifecycleFilter("");
              setTrackingTypeFilter("");
              setCompatibilityFilter("");
              setBarcodeFilter("");
              setPriceFilter("");
              setLotFilter("");
              setExpiryFilter("");
              setSortBy(
                displayPreferences
                  .defaultSort.field
              );
              setSortDir(
                displayPreferences
                  .defaultSort.direction
              );
              resetProductPagination();
            }}
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
              onFamilyFilterChange={(
                nextId
              ) => {
                const selected =
                  familyFilterOptions.find(
                    (item) =>
                      String(item.id) ===
                      nextId
                  );
                setFamilyFilterId(
                  nextId
                );
                setFamilyFilterName(
                  selected?.name ?? ""
                );
                resetProductPagination();
              }}
              onRetryFamilyOptions={() =>
                void familyFilterOptionsQuery.refetch()
              }
              onLifecycleFilterChange={(
                value
              ) => {
                setLifecycleFilter(
                  value
                );
                resetProductPagination();
              }}
              onTrackingTypeFilterChange={(
                value
              ) => {
                setTrackingTypeFilter(
                  value
                );
                resetProductPagination();
              }}
              onCompatibilityFilterChange={(
                value
              ) => {
                setCompatibilityFilter(
                  value
                );
                resetProductPagination();
              }}
              onBarcodeFilterChange={(
                value
              ) => {
                setBarcodeFilter(
                  value
                );
                resetProductPagination();
              }}
              onPriceFilterChange={(
                value
              ) => {
                setPriceFilter(value);
                resetProductPagination();
              }}
              onLotFilterChange={(
                value
              ) => {
                setLotFilter(value);
                resetProductPagination();
              }}
              onExpiryFilterChange={(
                value
              ) => {
                setExpiryFilter(value);
                resetProductPagination();
              }}
              onSortByChange={(
                value
              ) => {
                setSortBy(value);
                resetProductPagination();
              }}
              onSortDirChange={(
                value
              ) => {
                setSortDir(value);
                resetProductPagination();
              }}
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
            setDetailProduct
          }
          onEditPrice={
            openPriceEditor
          }
          onEditTracking={
            openTrackingEditor
          }
          onPrevious={() => {
            const previous =
              history.at(-1) ??
              null;
            setHistory(
              (current) =>
                current.slice(
                  0,
                  -1
                )
            );
            setCursor(
              previous
            );
          }}
          onNext={() => {
            if (
              !page?.next_cursor
            ) {
              return;
            }
            setHistory(
              (current) => [
                ...current,
                cursor,
              ]
            );
            setCursor(
              page.next_cursor
            );
          }}
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
        onClose={() =>
          setDisplayPreferencesOpen(
            false
          )
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
        onClose={() =>
          setDetailProduct(null)
        }
        onRenameProduct={(product) => {
          setDetailProduct(null);
          setRenameProduct(product);
        }}
        onEditPrice={(product) => {
          setDetailProduct(null);
          openPriceEditor(product);
        }}
        onEditTracking={(product) => {
          setDetailProduct(null);
          openTrackingEditor(
            product
          );
        }}
        onManageLifecycle={(product) => {
          setDetailProduct(null);
          setLifecycleProduct(
            product
          );
        }}
        onManageBarcodes={(product) => {
          setDetailProduct(null);
          setBarcodeProduct(
            product
          );
        }}
        onManageAdvancedUom={(product) => {
          setDetailProduct(null);
          navigate(
            `/products/advanced-uom?variant=${product.id}`
          );
        }}
      />

      <ProductRenameDialog
        product={renameProduct}
        companyId={companyId}
        driverId={driverId}
        onClose={() =>
          setRenameProduct(null)
        }
        onRenamed={() => {
          setRenameProduct(null);
        }}
      />

      <ProductLifecycleManager
        product={lifecycleProduct}
        onClose={() =>
          setLifecycleProduct(null)
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
        onClose={() =>
          setBarcodeProduct(null)
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
          onClose={() =>
            setTrackingDefaultsOpen(
              false
            )
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
          onClose={() => {
            setTrackingEdit(null);
            setTrackingEditLot(null);
            setTrackingEditExpiry(null);
          }}
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
        onNameChange={(value) => {
          setDraft(
            (current) => ({
              ...current,
              name: value,
            })
          );
          if (
            createFieldError?.field ===
            "name"
          ) {
            setCreateFieldError(null);
          }
        }}
        onFamilyChange={(value) =>
          setDraft(
            (current) => ({
              ...current,
              family: value,
            })
          )
        }
        onRetryFamilyOptions={() =>
          void familyOptionsQuery.refetch()
        }
        onRetryTrackingDefaults={() =>
          void trackingDefaultsQuery.refetch()
        }
        onHasPackageChange={(
          checked
        ) =>
          setDraft(
            (current) => ({
              ...current,
              has_package:
                checked,
              units_per_package:
                checked
                  ? current.units_per_package ===
                    "1"
                    ? "50"
                    : current.units_per_package
                  : "1",
              package_price:
                checked
                  ? current.package_price
                  : "",
              package_barcode:
                checked
                  ? current.package_barcode
                  : "",
            })
          )
        }
        onRetryPackageUoms={() =>
          void packageUomsQuery.refetch()
        }
        onPackageUomChange={(
          value
        ) =>
          setDraft(
            (current) => ({
              ...current,
              package_uom_code:
                value,
            })
          )
        }
        onUnitsPerPackageChange={(
          value
        ) => {
          setDraft(
            (current) => ({
              ...current,
              units_per_package:
                value,
            })
          );
          if (
            createFieldError?.field ===
            "units"
          ) {
            setCreateFieldError(null);
          }
        }}
        onPackagePriceChange={(
          value
        ) => {
          setDraft(
            (current) => ({
              ...current,
              package_price:
                value,
            })
          );
          if (
            createFieldError?.field ===
            "packagePrice"
          ) {
            setCreateFieldError(null);
          }
        }}
        onUnitPriceChange={(
          value
        ) => {
          setDraft(
            (current) => ({
              ...current,
              unit_price: value,
            })
          );
          if (
            createFieldError?.field ===
            "unitPrice"
          ) {
            setCreateFieldError(null);
          }
        }}
        onToggleAdvanced={() =>
          setCreateAdvancedExpanded(
            (current) => !current
          )
        }
        onExpandTracking={() =>
          setCreateTrackingExpanded(
            true
          )
        }
        onLotControlModeChange={(
          value
        ) =>
          setDraft(
            (current) => ({
              ...current,
              lot_control_mode:
                value,
            })
          )
        }
        onExpiryControlModeChange={(
          value
        ) =>
          setDraft(
            (current) => ({
              ...current,
              expiry_control_mode:
                value,
            })
          )
        }
        onResetTracking={() => {
          const defaults =
            trackingDefaultsQuery.data;
          if (!defaults) {
            return;
          }
          setDraft(
            (current) => ({
              ...current,
              lot_control_mode:
                defaults.lot_control_mode,
              expiry_control_mode:
                defaults.expiry_control_mode,
            })
          );
          setCreateTrackingExpanded(
            false
          );
        }}
        onUnitBarcodeChange={(
          value
        ) =>
          setDraft(
            (current) => ({
              ...current,
              unit_barcode:
                value,
            })
          )
        }
        onCopyBarcode={() => {
          setDraft(
            (current) => ({
              ...current,
              package_barcode:
                current.unit_barcode,
            })
          );
          toast.success(
            t(
              "products.copiedBarcode"
            )
          );
        }}
        onPackageBarcodeChange={(
          value
        ) =>
          setDraft(
            (current) => ({
              ...current,
              package_barcode:
                value,
            })
          )
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
        onClose={() =>
          setFamiliesOpen(false)
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
