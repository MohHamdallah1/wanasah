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
  fileFingerprint,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  deriveExactMoneyPair,
} from "@/lib/exactMoney";
import {
  parsePackageUoms,
  parseProductImportAccepted,
  parseProductImportCommandResponse,
  parseProductImportErrorPage,
  parseProductTrackingDefaults,
  parseProductTrackingMutation,
  parseSimpleProductPriceMutationResponse,
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
import { useImportProductCommands } from "@/pages/products/import/useImportProductCommands";
import { useImportProductPolling } from "@/pages/products/import/useImportProductPolling";
import { useImportProductState } from "@/pages/products/import/useImportProductState";
import { useImportSessionResume } from "@/pages/products/import/useImportSessionResume";
import { ProductsFiltersPanel } from "@/pages/products/list/ProductsFiltersPanel";
import { ProductsListResults } from "@/pages/products/list/ProductsListResults";
import { ProductsListToolbar } from "@/pages/products/list/ProductsListToolbar";
import { useProductsListDebounce } from "@/pages/products/list/useProductsListDebounce";
import { useProductsListParams } from "@/pages/products/list/useProductsListParams";
import { useProductsListQueries } from "@/pages/products/list/useProductsListQueries";
import { useProductsListState } from "@/pages/products/list/useProductsListState";
import { ProductRenameDialog } from "@/pages/products/ProductRenameDialog";
import { ProductTrackingEditor } from "@/pages/products/ProductTrackingEditor";
import { ProductTrackingSettings } from "@/pages/products/ProductTrackingSettings";

type MutationResult<T> = {
  result: T;
  requestId: string;
  scope: string;
};

type PriceFieldError = {
  field: "packagePrice" | "unitPrice";
  message: string;
};

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

  const [
    trackingDefaultsOpen,
    setTrackingDefaultsOpen,
  ] = useState(false);
  const [
    trackingDefaultsLot,
    setTrackingDefaultsLot,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    trackingDefaultsExpiry,
    setTrackingDefaultsExpiry,
  ] = useState<ProductTrackingMode | null>(
    null
  );
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
  const [
    trackingEdit,
    setTrackingEdit,
  ] = useState<SimpleProduct | null>(
    null
  );
  const [
    trackingEditLot,
    setTrackingEditLot,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    trackingEditExpiry,
    setTrackingEditExpiry,
  ] = useState<ProductTrackingMode | null>(
    null
  );

  const [
    priceEdit,
    setPriceEdit,
  ] =
    useState<SimpleProduct | null>(
      null
    );
  const [
    editPackagePrice,
    setEditPackagePrice,
  ] = useState("");
  const [
    editUnitPrice,
    setEditUnitPrice,
  ] = useState("");
  const [
    priceFieldError,
    setPriceFieldError,
  ] = useState<PriceFieldError | null>(
    null
  );
  const editPackagePriceRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const editUnitPriceRef =
    useRef<HTMLInputElement | null>(
      null
    );

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
    useQuery({
      queryKey: [
        "simple-product-tracking-defaults",
        companyId,
      ],
      enabled: Boolean(companyId),
      queryFn: async ({
        signal,
      }) =>
        parseProductTrackingDefaults(
          await authFetch(
            "/simple-products/tracking/defaults",
            { signal }
          )
        ),
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
    Boolean(
      trackingDefaultsQuery.data &&
        importLotControlMode &&
        importExpiryControlMode &&
        importLotControlMode ===
          trackingDefaultsQuery.data
            .lot_control_mode &&
        importExpiryControlMode ===
          trackingDefaultsQuery.data
            .expiry_control_mode
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

  const openPriceEditor = (
    product: SimpleProduct
  ) => {
    setPriceFieldError(null);
    setPriceEdit(product);
    setEditPackagePrice(
      product.package_price ?? ""
    );
    setEditUnitPrice(
      product.unit_price ?? ""
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

  const trackingDefaultsMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !trackingDefaultsLot ||
          !trackingDefaultsExpiry
        ) {
          throw new Error(
            t(
              "products.errors.trackingDefaultsRequired"
            )
          );
        }

        const body = {
          lot_control_mode:
            trackingDefaultsLot,
          expiry_control_mode:
            trackingDefaultsExpiry,
        };
        const scope =
          operationScope(
            "product-tracking-defaults"
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            body
          );
        const data =
          parseProductTrackingDefaults(
            await authFetch(
              "/simple-products/tracking/defaults",
              {
                method: "PUT",
                body: JSON.stringify({
                  request_id:
                    requestId,
                  ...body,
                }),
              }
            )
          );
        return {
          data,
          requestId,
          scope,
        };
      },
      onSuccess: async ({
        data,
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setTrackingDefaultsOpen(
          false
        );
        setTrackingDefaultsLot(
          data.lot_control_mode
        );
        setTrackingDefaultsExpiry(
          data.expiry_control_mode
        );
        if (
          !importJobId
        ) {
          setImportLotControlMode(
            data.lot_control_mode
          );
          setImportExpiryControlMode(
            data.expiry_control_mode
          );
        }
        toast.success(
          t(
            "products.trackingSettings.saved"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-product-tracking-defaults",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingDefaultsSave"
            )
          )
        ),
    });

  const trackingMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !trackingEdit ||
          !trackingEditLot ||
          !trackingEditExpiry
        ) {
          throw new Error(
            t(
              "products.errors.trackingProductRequired"
            )
          );
        }

        const body = {
          expected_version:
            trackingEdit.version,
          lot_control_mode:
            trackingEditLot,
          expiry_control_mode:
            trackingEditExpiry,
        };
        const scope =
          operationScope(
            "product-tracking",
            trackingEdit.id
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            body
          );
        const data =
          parseProductTrackingMutation(
            await authFetch(
              `/simple-products/tracking/variants/${trackingEdit.id}`,
              {
                method: "PATCH",
                body: JSON.stringify({
                  request_id:
                    requestId,
                  ...body,
                }),
              }
            )
          );
        return {
          data,
          requestId,
          scope,
        };
      },
      onSuccess: async ({
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setTrackingEdit(null);
        setTrackingEditLot(null);
        setTrackingEditExpiry(null);
        toast.success(
          t(
            "products.trackingEditor.saved"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-products",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingProductSave"
            )
          )
        ),
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

  const priceMutation =
    useMutation({
      mutationFn:
        async (): Promise<
          | MutationResult<
              ReturnType<
                typeof parseSimpleProductPriceMutationResponse
              >
            >
          | undefined
        > => {
          if (!priceEdit) {
            return undefined;
          }
          if (
            !editPackagePrice.trim() &&
            !editUnitPrice.trim()
          ) {
            throw new Error(
              priceEdit.package_uom_code
                ? t(
                    "products.errors.priceRequired"
                  )
                : t(
                    "products.errors.unitPriceRequired"
                  )
            );
          }

          const body = {
            package_price:
              priceEdit.package_uom_code &&
              editPackagePrice.trim()
                ? editPackagePrice.trim()
                : null,
            unit_price:
              editUnitPrice.trim() ||
              null,
          };
          const scope =
            operationScope(
              "product-price",
              priceEdit.id
            );
          const requestId =
            await getOrCreateDurableRequestId(
              scope,
              body
            );
          const result =
            parseSimpleProductPriceMutationResponse(
              await authFetch(
                `/simple-products/${priceEdit.id}/price`,
                {
                  method: "PATCH",
                  body: JSON.stringify(
                    {
                      request_id:
                        requestId,
                      ...body,
                    }
                  ),
                }
              )
            );
          if (
            result.product_variant_id !==
            priceEdit.id
          ) {
            throw new Error(
              "SIMPLE_PRODUCT_PRICE_SCOPE_MISMATCH"
            );
          }
          return {
            result,
            requestId,
            scope,
          };
        },
      onSuccess: async (
        completed
      ) => {
        if (completed) {
          completeDurableOperation(
            completed.scope,
            completed.requestId
          );
        }
        setPriceEdit(null);
        setPriceFieldError(null);
        toast.success(
          t(
            "products.priceUpdated"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-products",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.priceFailed"
            )
          )
        ),
    });

  const submitPriceEdit = () => {
    if (!priceEdit) {
      return;
    }
    if (
      !editPackagePrice.trim() &&
      !editUnitPrice.trim()
    ) {
      const packageField =
        Boolean(
          priceEdit.package_uom_code
        );
      setPriceFieldError({
        field: packageField
          ? "packagePrice"
          : "unitPrice",
        message: packageField
          ? t(
              "products.errors.priceRequired"
            )
          : t(
              "products.errors.unitPriceRequired"
            ),
      });
      window.requestAnimationFrame(
        () =>
          (
            packageField
              ? editPackagePriceRef
              : editUnitPriceRef
          ).current?.focus()
      );
      return;
    }
    setPriceFieldError(null);
    priceMutation.mutate();
  };

  const importMutation =
    useMutation({
      mutationFn: async () => {
        if (!importFile) {
          throw new Error(
            t(
              "products.errors.fileRequired"
            )
          );
        }
        if (
          !importLotControlMode ||
          !importExpiryControlMode
        ) {
          throw new Error(
            t(
              "products.errors.trackingDefaultsRequired"
            )
          );
        }

        const fingerprint =
          await fileFingerprint(
            importFile
          );
        const scope =
          operationScope(
            "product-import",
            `${fingerprint}:${importLotControlMode}:${importExpiryControlMode}`
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            {
              fingerprint,
              name: importFile.name,
              size: importFile.size,
              default_lot_control_mode:
                importLotControlMode,
              default_expiry_control_mode:
                importExpiryControlMode,
            }
          );

        const form =
          new FormData();
        form.append(
          "request_id",
          requestId
        );
        form.append(
          "default_lot_control_mode",
          importLotControlMode
        );
        form.append(
          "default_expiry_control_mode",
          importExpiryControlMode
        );
        form.append(
          "file",
          importFile
        );

        const result =
          parseProductImportAccepted(
            await authFetch(
              "/simple-products/imports",
              {
                method: "POST",
                body: form,
              }
            )
          );

        return {
          result,
          requestId,
          scope,
        };
      },
      onSuccess: ({
        result,
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setImportJobId(
          result.job_id
        );
        setImportLotControlMode(
          result.default_lot_control_mode
        );
        setImportExpiryControlMode(
          result.default_expiry_control_mode
        );
        setImportStatus(null);
        setImportPollError(null);
        if (
          importSessionKey
        ) {
          sessionStorage.setItem(
            importSessionKey,
            result.job_id
          );
        }
        toast.success(
          t(
            "products.importAccepted"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.importFailed"
            )
          )
        ),
    });

  const {
    mappingMutation,
    retryImportMutation,
  } = useImportProductCommands({
    importJobId,
    mapping,
    authFetch,
    setImportPollError,
    setImportStatus,
    setImportPollKey,
    t,
  });

  useImportProductPolling({
    importJobId,
    importPollKey,
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

  const chooseFile = (
    file: File | null
  ) => {
    if (!file) {
      return;
    }
    const lower =
      file.name.toLowerCase();
    if (
      !lower.endsWith(
        ".csv"
      ) &&
      !lower.endsWith(
        ".xlsx"
      )
    ) {
      toast.error(
        t(
          "products.errors.unsupportedFile"
        )
      );
      return;
    }

    setImportFile(file);
    setImportJobId(null);
    setImportStatus(null);
    setImportPollError(null);
    setMapping({});
    if (
      importSessionKey
    ) {
      sessionStorage.removeItem(
        importSessionKey
      );
    }
  };

  const resetImport =
    () => {
      setImportFile(null);
      setImportJobId(null);
      setImportStatus(null);
      setImportPollError(null);
      setMapping({});
      setImportLotControlMode(
        trackingDefaultsQuery.data
          ?.lot_control_mode ?? null
      );
      setImportExpiryControlMode(
        trackingDefaultsQuery.data
          ?.expiry_control_mode ?? null
      );
      setImportTrackingExpanded(false);
      if (importSessionKey) {
        sessionStorage.removeItem(
          importSessionKey
        );
      }
      if (fileRef.current) {
        fileRef.current.value =
          "";
      }
    };

  const csvCell = (
    value: string | number
  ) => {
    const text = String(value);
    return `"${text.replace(
      /"/g,
      '""'
    )}"`;
  };

  const downloadErrorReport =
    async () => {
      if (!importJobId) {
        return;
      }

      const allRows: Array<{
        row_number: number;
        code: string | null;
        message: string | null;
      }> = [];
      let afterRow = 0;

      while (true) {
        const result =
          parseProductImportErrorPage(
            await authFetch(
              `/simple-products/imports/${importJobId}/errors?after_row=${afterRow}&limit=1000`
            )
          );

        allRows.push(
          ...result.items
        );
        if (
          result.next_after_row ===
          null
        ) {
          break;
        }
        afterRow =
          result.next_after_row;
      }

      const lines = [
        [
          t(
            "products.errorReportRow"
          ),
          t(
            "products.errorReportCode"
          ),
          t(
            "products.errorReportMessage"
          ),
        ]
          .map(csvCell)
          .join(","),
        ...allRows.map(
          (row) => {
            const key = row.code
              ? `errors.codes.${row.code}`
              : "";
            const message =
              key &&
              i18n.exists(key)
                ? t(key)
                : t(
                    "network.serverError"
                  );
            return [
              row.row_number,
              row.code || "",
              message,
            ]
              .map(csvCell)
              .join(",");
          }
        ),
      ];

      const blob = new Blob(
        [
          "\ufeff",
          lines.join("\n"),
        ],
        {
          type: "text/csv;charset=utf-8",
        }
      );
      const href =
        URL.createObjectURL(
          blob
        );
      const link =
        document.createElement(
          "a"
        );
      link.href = href;
      link.download =
        "product-import-errors.csv";
      link.click();
      URL.revokeObjectURL(
        href
      );
    };

  const downloadTemplate =
    () => {
      const headers = [
        t(
          "products.fields.name"
        ),
        t(
          "products.fields.family"
        ),
        t(
          "products.fields.packageUom"
        ),
        t(
          "products.fields.unitsPerPackage"
        ),
        t(
          "products.fields.packagePrice"
        ),
        t(
          "products.fields.unitPrice"
        ),
        t(
          "products.fields.unitBarcode"
        ),
        t(
          "products.fields.packageBarcode"
        ),
        t(
          "products.fields.lotControlMode"
        ),
        t(
          "products.fields.expiryControlMode"
        ),
      ];
      const lines = [
        headers.join(","),
        [
          t("products.importTemplateSampleName"),
          t("products.importTemplateSampleFamily"),
          t("uom.CARTON"),
          "50",
          "10.000",
          "",
          "6251234567890",
          "",
          t(
            "products.tracking.importValues.REQUIRED"
          ),
          t(
            "products.tracking.importValues.REQUIRED"
          ),
        ].join(","),
      ];

      const blob = new Blob(
        [
          "\ufeff",
          lines.join("\n"),
        ],
        {
          type: "text/csv;charset=utf-8",
        }
      );
      const href =
        URL.createObjectURL(
          blob
        );
      const anchor =
        document.createElement(
          "a"
        );
      anchor.href = href;
      anchor.download =
        "products-import-template.csv";
      anchor.click();
      URL.revokeObjectURL(
        href
      );
    };

  const draftDerived =
    deriveExactMoneyPair(
      draft.has_package,
      draft.units_per_package,
      draft.package_price,
      draft.unit_price
    );

  const editDerived =
    priceEdit
      ? deriveExactMoneyPair(
          Boolean(
            priceEdit.package_uom_code
          ),
          String(
            priceEdit.units_per_package
          ),
          editPackagePrice,
          editUnitPrice
        )
      : null;

  const importProgress =
    importStatus &&
    importStatus.valid_rows > 0
      ? Math.min(
          100,
          Math.round(
            (importStatus.processed_rows /
              importStatus.valid_rows) *
              100
          )
        )
      : 0;


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
                onClick={() => {
                  setImportTrackingExpanded(
                    false
                  );
                  setImportOpen(
                    true
                  );
                }}
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

      <Modal
        isOpen={
          priceEdit !== null
        }
        onClose={() => {
          if (
            !priceMutation.isPending
          ) {
            setPriceEdit(
              null
            );
            setPriceFieldError(null);
          }
        }}
        title={`${t(
          "products.editPrice"
        )} — ${priceEdit?.name ?? ""}`}
        maxWidth="max-w-xl"
        footer={
          <>
            <button
              type="button"
              disabled={
                priceMutation.isPending
              }
              onClick={() =>
                setPriceEdit(
                  null
                )
              }
              className="px-4 py-2 text-sm font-bold text-slate-600"
            >
              {t(
                "common.cancel"
              )}
            </button>
            <button
              type="button"
              disabled={
                priceMutation.isPending ||
                !isOnline
              }
              onClick={submitPriceEdit}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
            >
              {t(
                "products.savePrice"
              )}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="rounded-2xl bg-sky-50 p-3 text-xs font-bold leading-6 text-sky-900">
            {t(
              "products.priceHelp"
            )}
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            {priceEdit?.package_uom_code ? (
              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.packagePrice"
                )}
                <input
                  ref={editPackagePriceRef}
                  inputMode="decimal"
                  value={
                    editPackagePrice
                  }
                  onChange={(
                    event
                  ) => {
                    setEditPackagePrice(
                      event.target.value
                    );
                    if (
                      priceFieldError?.field ===
                      "packagePrice"
                    ) {
                      setPriceFieldError(null);
                    }
                  }}
                  aria-invalid={
                    priceFieldError?.field ===
                    "packagePrice"
                      ? "true"
                      : undefined
                  }
                  aria-describedby={
                    priceFieldError?.field ===
                    "packagePrice"
                      ? "edit-package-price-error"
                      : undefined
                  }
                  className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
                />
                {priceFieldError?.field ===
                "packagePrice" ? (
                  <span
                    id="edit-package-price-error"
                    role="alert"
                    className="mt-1 block text-[11px] font-bold text-rose-700"
                  >
                    {priceFieldError.message}
                  </span>
                ) : null}
              </label>
            ) : null}

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.unitPrice"
              )}
              <input
                ref={editUnitPriceRef}
                inputMode="decimal"
                value={
                  editUnitPrice
                }
                onChange={(
                  event
                ) => {
                  setEditUnitPrice(
                    event.target.value
                  );
                  if (
                    priceFieldError?.field ===
                    "unitPrice"
                  ) {
                    setPriceFieldError(null);
                  }
                }}
                aria-invalid={
                  priceFieldError?.field ===
                  "unitPrice"
                    ? "true"
                    : undefined
                }
                aria-describedby={
                  priceFieldError?.field ===
                  "unitPrice"
                    ? "edit-unit-price-error"
                    : undefined
                }
                className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
              />
              {priceFieldError?.field ===
              "unitPrice" ? (
                <span
                  id="edit-unit-price-error"
                  role="alert"
                  className="mt-1 block text-[11px] font-bold text-rose-700"
                >
                  {priceFieldError.message}
                </span>
              ) : null}
            </label>
          </div>

          {editDerived?.independent ? (
            <p className="text-xs font-bold text-slate-500">
              {t(
                "products.independentPrices"
              )}
            </p>
          ) : null}
        </div>
      </Modal>

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
        onClose={() => {
          if (
            !importMutation.isPending
          ) {
            setImportTrackingExpanded(
              false
            );
            setImportOpen(
              false
            );
          }
        }}
        onDownloadTemplate={
          downloadTemplate
        }
        onRetryTrackingDefaults={() =>
          void trackingDefaultsQuery.refetch()
        }
        onExpandTracking={() =>
          setImportTrackingExpanded(
            true
          )
        }
        onLotControlModeChange={
          setImportLotControlMode
        }
        onExpiryControlModeChange={
          setImportExpiryControlMode
        }
        onResetTracking={() => {
          const defaults =
            trackingDefaultsQuery.data;
          if (!defaults) {
            return;
          }
          setImportLotControlMode(
            defaults.lot_control_mode
          );
          setImportExpiryControlMode(
            defaults.expiry_control_mode
          );
          setImportTrackingExpanded(
            false
          );
        }}
        onChooseFile={chooseFile}
        onDraggingChange={
          setDragging
        }
        onStartImport={() =>
          importMutation.mutate()
        }
        onRetryPoll={() => {
          setImportPollError(null);
          setImportPollKey(
            (current) =>
              current + 1
          );
        }}
        onMappingChange={(
          field,
          value
        ) =>
          setMapping(
            (current) => ({
              ...current,
              [field]: value,
            })
          )
        }
        onSubmitMapping={() =>
          mappingMutation.mutate()
        }
        onDownloadErrorReport={() =>
          void downloadErrorReport()
        }
        onResetImport={resetImport}
        onRetryImport={() =>
          retryImportMutation.mutate()
        }
        onCompletedClose={() => {
          setImportOpen(false);
          setImportFile(null);
          setImportJobId(null);
          setImportStatus(null);
          setMapping({});
          setImportTrackingExpanded(
            false
          );
          if (importSessionKey) {
            sessionStorage.removeItem(
              importSessionKey
            );
          }
        }}
      />
    </div>
  );
}
