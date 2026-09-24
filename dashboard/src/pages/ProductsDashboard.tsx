import {
  useEffect,
  useMemo,
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
  ChevronLeft,
  ChevronRight,
  Copy,
  FileSpreadsheet,
  FolderTree,
  PackagePlus,
  RefreshCw,
  Search,
  Settings2,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
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
  parseProductFamilies,
  parseProductImportAccepted,
  parseProductImportErrorPage,
  parseProductImportState,
  parseProductTrackingDefaults,
  parseProductTrackingMutation,
  parseSimpleProductPage,
  type PackageUom,
  type ProductImportState,
  type ProductFamily,
  type ProductTrackingMode,
  type SimpleProduct,
} from "@/pages/products/contracts";
import { ProductBarcodeManager } from "@/pages/products/ProductBarcodeManager";
import { ProductDetailDrawer } from "@/pages/products/ProductDetailDrawer";
import { ProductFamiliesManager } from "@/pages/products/ProductFamiliesManager";
import { ProductTableRow } from "@/pages/products/ProductTableRow";
import { ProductTrackingEditor } from "@/pages/products/ProductTrackingEditor";
import { ProductTrackingFields } from "@/pages/products/ProductTrackingFields";
import { ProductTrackingSettings } from "@/pages/products/ProductTrackingSettings";

type MutationResult = {
  result: unknown;
  requestId: string;
  scope: string;
};

const terminalImportStatuses =
  new Set([
    "COMPLETED",
    "VALIDATION_FAILED",
    "FAILED",
    "NEEDS_MAPPING",
  ]);

type ProductLifecycleFilter =
  | ""
  | "ACTIVE"
  | "RETIRING";
type ProductTrackingTypeFilter =
  | ""
  | "NONE"
  | "LOT"
  | "EXPIRY"
  | "LOT_EXPIRY";
type ProductBooleanFilter =
  | ""
  | "true"
  | "false";
type ProductSortField =
  | "id"
  | "name"
  | "family"
  | "sku"
  | "lifecycle";
type ProductSortDirection =
  | "asc"
  | "desc";

type CreateFieldError = {
  field:
    | "name"
    | "units"
    | "packagePrice"
    | "unitPrice";
  message: string;
};

type PriceFieldError = {
  field: "packagePrice" | "unitPrice";
  message: string;
};

type ProductDraft = {
  name: string;
  family: string;
  has_package: boolean;
  package_uom_code: string;
  units_per_package: string;
  package_price: string;
  unit_price: string;
  unit_barcode: string;
  package_barcode: string;
  lot_control_mode: ProductTrackingMode | null;
  expiry_control_mode: ProductTrackingMode | null;
};

const emptyDraft: ProductDraft = {
  name: "",
  family: "",
  has_package: true,
  package_uom_code: "CARTON",
  units_per_package: "50",
  package_price: "",
  unit_price: "",
  unit_barcode: "",
  package_barcode: "",
  lot_control_mode: null,
  expiry_control_mode: null,
};

const importMappingFields = [
  "name",
  "family",
  "package_uom",
  "units_per_package",
  "package_price",
  "unit_price",
  "unit_barcode",
  "package_barcode",
  "lot_control_mode",
  "expiry_control_mode",
] as const;

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

  const [
    searchInput,
    setSearchInput,
  ] = useState("");
  const [
    search,
    setSearch,
  ] = useState("");
  const [
    cursor,
    setCursor,
  ] = useState<string | null>(
    null
  );
  const [
    history,
    setHistory,
  ] = useState<
    Array<string | null>
  >([]);
  const [
    filtersOpen,
    setFiltersOpen,
  ] = useState(false);
  const [
    familyFilterSearchInput,
    setFamilyFilterSearchInput,
  ] = useState("");
  const [
    familyFilterSearch,
    setFamilyFilterSearch,
  ] = useState("");
  const [
    familyFilterId,
    setFamilyFilterId,
  ] = useState("");
  const [
    familyFilterName,
    setFamilyFilterName,
  ] = useState("");
  const [
    lifecycleFilter,
    setLifecycleFilter,
  ] =
    useState<ProductLifecycleFilter>(
      ""
    );
  const [
    trackingTypeFilter,
    setTrackingTypeFilter,
  ] =
    useState<ProductTrackingTypeFilter>(
      ""
    );
  const [
    compatibilityFilter,
    setCompatibilityFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    barcodeFilter,
    setBarcodeFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    priceFilter,
    setPriceFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    lotFilter,
    setLotFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    expiryFilter,
    setExpiryFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    sortBy,
    setSortBy,
  ] =
    useState<ProductSortField>(
      "id"
    );
  const [
    sortDir,
    setSortDir,
  ] =
    useState<ProductSortDirection>(
      "asc"
    );

  const resetProductPagination = () => {
    setCursor(null);
    setHistory([]);
  };

  const [
    createOpen,
    setCreateOpen,
  ] = useState(false);
  const [
    createTrackingExpanded,
    setCreateTrackingExpanded,
  ] = useState(false);
  const [
    createAdvancedExpanded,
    setCreateAdvancedExpanded,
  ] = useState(false);
  const [
    draft,
    setDraft,
  ] =
    useState<ProductDraft>(
      emptyDraft
    );
  const restoredDraftKey =
    useRef<string | null>(
      null
    );
  const [
    createFieldError,
    setCreateFieldError,
  ] = useState<CreateFieldError | null>(
    null
  );
  const createNameRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createUnitsRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createPackagePriceRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createUnitPriceRef =
    useRef<HTMLInputElement | null>(
      null
    );

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
    barcodeProduct,
    setBarcodeProduct,
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
  ] = useState("");

  const [
    importOpen,
    setImportOpen,
  ] = useState(false);
  const [
    importFile,
    setImportFile,
  ] = useState<File | null>(
    null
  );
  const [
    importJobId,
    setImportJobId,
  ] = useState<string | null>(
    null
  );
  const [
    importStatus,
    setImportStatus,
  ] =
    useState<ProductImportState | null>(
      null
    );
  const [
    mapping,
    setMapping,
  ] = useState<
    Record<string, string>
  >({});
  const [
    importPollKey,
    setImportPollKey,
  ] = useState(0);
  const [
    importLotControlMode,
    setImportLotControlMode,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    importExpiryControlMode,
    setImportExpiryControlMode,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    importTrackingExpanded,
    setImportTrackingExpanded,
  ] = useState(false);
  const [
    dragging,
    setDragging,
  ] = useState(false);
  const fileRef =
    useRef<HTMLInputElement | null>(
      null
    );

  const draftStorageKey =
    companyId && driverId
      ? `wanasah:product-draft:v2:${companyId}:${driverId}`
      : null;
  const importSessionKey =
    companyId && driverId
      ? `wanasah:product-import:v1:${companyId}:${driverId}`
      : null;

  useEffect(() => {
    const timer =
      window.setTimeout(() => {
        const clean =
          searchInput.trim();
        setSearch(
          clean.length >= 2
            ? clean
            : ""
        );
        setCursor(null);
        setHistory([]);
      }, 250);
    return () =>
      window.clearTimeout(
        timer
      );
  }, [searchInput]);

  useEffect(() => {
    const timer =
      window.setTimeout(() => {
        setFamilyFilterSearch(
          familyFilterSearchInput
            .trim()
            .slice(0, 100)
        );
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [familyFilterSearchInput]);

  useEffect(() => {
    if (
      canViewPricing ||
      !priceFilter
    ) {
      return;
    }
    setPriceFilter("");
    setCursor(null);
    setHistory([]);
  }, [
    canViewPricing,
    priceFilter,
  ]);

  useEffect(() => {
    if (!createOpen) {
      setFamilyOptionSearch("");
      return;
    }
    const timer =
      window.setTimeout(() => {
        setFamilyOptionSearch(
          draft.family
            .trim()
            .slice(0, 100)
        );
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [
    createOpen,
    draft.family,
  ]);

  useEffect(() => {
    if (!draftStorageKey) {
      return;
    }
    if (
      restoredDraftKey.current ===
      draftStorageKey
    ) {
      return;
    }

    restoredDraftKey.current =
      draftStorageKey;
    try {
      const raw =
        sessionStorage.getItem(
          draftStorageKey
        );
      if (raw) {
        const parsed =
          JSON.parse(
            raw
          ) as Partial<ProductDraft>;
        const restored = {
          ...emptyDraft,
          ...parsed,
        };
        setDraft(restored);
        if (
          restored.name ||
          restored.family ||
          restored.package_price ||
          restored.unit_price ||
          restored.unit_barcode ||
          restored.package_barcode
        ) {
          toast.message(
            t(
              "products.draftRestored"
            )
          );
        }
      }
    } catch {
      sessionStorage.removeItem(
        draftStorageKey
      );
    }
  }, [
    draftStorageKey,
    t,
  ]);

  useEffect(() => {
    if (
      !draftStorageKey ||
      restoredDraftKey.current !==
        draftStorageKey
    ) {
      return;
    }
    sessionStorage.setItem(
      draftStorageKey,
      JSON.stringify(draft)
    );
  }, [
    draft,
    draftStorageKey,
  ]);

  useEffect(() => {
    if (!importSessionKey) {
      return;
    }
    const stored =
      sessionStorage.getItem(
        importSessionKey
      );
    if (
      stored &&
      !importJobId
    ) {
      setImportJobId(stored);
      toast.message(
        t(
          "products.importResumed"
        )
      );
    }
  }, [
    importJobId,
    importSessionKey,
    t,
  ]);

  const params = useMemo(
    () => {
      const value =
        new URLSearchParams({
          limit: "100",
          sort_by: sortBy,
          sort_dir: sortDir,
        });
      if (search) {
        value.set(
          "search",
          search
        );
      }
      if (cursor) {
        value.set(
          "cursor",
          cursor
        );
      }
      if (familyFilterId) {
        value.set(
          "family_id",
          familyFilterId
        );
      }
      if (lifecycleFilter) {
        value.set(
          "lifecycle",
          lifecycleFilter
        );
      }
      if (trackingTypeFilter) {
        value.set(
          "tracking_type",
          trackingTypeFilter
        );
      }
      if (compatibilityFilter) {
        value.set(
          "simple_compatible",
          compatibilityFilter
        );
      }
      if (barcodeFilter) {
        value.set(
          "has_barcode",
          barcodeFilter
        );
      }
      if (
        canViewPricing &&
        priceFilter
      ) {
        value.set(
          "has_price",
          priceFilter
        );
      }
      if (lotFilter) {
        value.set(
          "lot_tracked",
          lotFilter
        );
      }
      if (expiryFilter) {
        value.set(
          "expiry_tracked",
          expiryFilter
        );
      }
      return value.toString();
    },
    [
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
    ]
  );

  const familyFilterParams =
    useMemo(
      () => {
        const value =
          new URLSearchParams({
            limit: "50",
          });
        if (familyFilterSearch) {
          value.set(
            "search",
            familyFilterSearch
          );
        }
        return value.toString();
      },
      [familyFilterSearch]
    );

  const familyOptionParams =
    useMemo(
      () => {
        const value =
          new URLSearchParams({
            limit: "20",
          });
        if (familyOptionSearch) {
          value.set(
            "search",
            familyOptionSearch
          );
        }
        return value.toString();
      },
      [familyOptionSearch]
    );

  const productsQuery =
    useQuery({
      queryKey: [
        "simple-products",
        companyId,
        params,
      ],
      enabled: Boolean(
        companyId
      ),
      queryFn: async ({
        signal,
      }) =>
        parseSimpleProductPage(
          await authFetch(
            `/simple-products?${params}`,
            { signal }
          )
        ),
    });

  const familyFilterOptionsQuery =
    useQuery({
      queryKey: [
        "simple-product-families",
        companyId,
        "filter-options",
        familyFilterSearch,
      ],
      enabled: Boolean(
        companyId &&
        filtersOpen
      ),
      queryFn: async ({
        signal,
      }) =>
        parseProductFamilies(
          await authFetch(
            `/simple-products/families?${familyFilterParams}`,
            { signal }
          )
        ),
    });

  const familyOptionsQuery =
    useQuery({
      queryKey: [
        "simple-product-families",
        companyId,
        "options",
        familyOptionSearch,
      ],
      enabled: Boolean(
        companyId &&
        createOpen
      ),
      queryFn: async ({
        signal,
      }) =>
        parseProductFamilies(
          await authFetch(
            `/simple-products/families?${familyOptionParams}`,
            { signal }
          )
        ),
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
    setSortBy("id");
    setSortDir("asc");
    setDetailProduct(null);
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
  }, [companyId]);

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
  const productTableColumnCount =
    pricingVisible ? 7 : 5;
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
        sortBy !== "id" ||
        sortDir !== "asc"
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

  const openPriceEditor = (
    product: SimpleProduct
  ) => {
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

  const createMutation =
    useMutation({
      mutationFn:
        async (): Promise<MutationResult> => {
          if (
            !draft.name.trim()
          ) {
            throw new Error(
              t(
                "products.errors.nameRequired"
              )
            );
          }

          const units =
            draft.has_package
              ? Number(
                  draft.units_per_package
                )
              : 1;

          if (
            draft.has_package &&
            (!Number.isInteger(
              units
            ) ||
              units < 2)
          ) {
            throw new Error(
              t(
                "products.errors.packageUnitsInvalid"
              )
            );
          }

          if (
            !draft.package_price.trim() &&
            !draft.unit_price.trim()
          ) {
            throw new Error(
              draft.has_package
                ? t(
                    "products.errors.priceRequired"
                  )
                : t(
                    "products.errors.unitPriceRequired"
                  )
            );
          }
          if (
            !draft.lot_control_mode ||
            !draft.expiry_control_mode
          ) {
            throw new Error(
              t(
                "products.errors.trackingDefaultsRequired"
              )
            );
          }

          const selectedFamily =
            familyOptions.find(
              (item) =>
                item.name
                  .trim()
                  .toLocaleLowerCase() ===
                draft.family
                  .trim()
                  .toLocaleLowerCase()
            );

          const body = {
            name:
              draft.name.trim(),
            family_id:
              selectedFamily?.id ??
              null,
            family_name:
              !selectedFamily &&
              draft.family.trim()
                ? draft.family.trim()
                : null,
            package_uom_code:
              draft.has_package
                ? draft.package_uom_code
                : null,
            units_per_package:
              units,
            package_price:
              draft.has_package &&
              draft.package_price.trim()
                ? draft.package_price.trim()
                : null,
            unit_price:
              draft.unit_price.trim() ||
              null,
            unit_barcode:
              draft.unit_barcode.trim() ||
              null,
            package_barcode:
              draft.has_package &&
              draft.package_barcode.trim()
                ? draft.package_barcode.trim()
                : null,
            lot_control_mode:
              draft.lot_control_mode,
            expiry_control_mode:
              draft.expiry_control_mode,
          };

          const scope =
            operationScope(
              "product-create"
            );
          const requestId =
            await getOrCreateDurableRequestId(
              scope,
              body
            );
          const result =
            await authFetch(
              "/simple-products",
              {
                method: "POST",
                body: JSON.stringify(
                  {
                    request_id:
                      requestId,
                    ...body,
                  }
                ),
              }
            );

          return {
            result,
            requestId,
            scope,
          };
        },
      onSuccess:
        async ({
          requestId,
          scope,
        }) => {
          completeDurableOperation(
            scope,
            requestId
          );
          if (
            draftStorageKey
          ) {
            sessionStorage.removeItem(
              draftStorageKey
            );
          }
          setDraft(
            emptyDraft
          );
          setCreateFieldError(null);
          setCreateTrackingExpanded(
            false
          );
          setCreateAdvancedExpanded(
            false
          );
          setCreateOpen(false);
          setCursor(null);
          setHistory([]);
          toast.success(
            t(
              "products.created"
            )
          );
          await Promise.all([
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-products",
                ],
              }
            ),
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-product-families",
                ],
              }
            ),
          ]);
        },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.createFailed"
            )
          )
        ),
    });

  const submitCreate = () => {
    if (!draft.name.trim()) {
      setCreateFieldError({
        field: "name",
        message: t(
          "products.errors.nameRequired"
        ),
      });
      window.requestAnimationFrame(
        () => createNameRef.current?.focus()
      );
      return;
    }

    const units =
      draft.has_package
        ? Number(
            draft.units_per_package
          )
        : 1;
    if (
      draft.has_package &&
      (!Number.isInteger(units) ||
        units < 2)
    ) {
      setCreateFieldError({
        field: "units",
        message: t(
          "products.errors.packageUnitsInvalid"
        ),
      });
      window.requestAnimationFrame(
        () => createUnitsRef.current?.focus()
      );
      return;
    }

    if (
      !draft.package_price.trim() &&
      !draft.unit_price.trim()
    ) {
      const packageField =
        draft.has_package;
      setCreateFieldError({
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
              ? createPackagePriceRef
              : createUnitPriceRef
          ).current?.focus()
      );
      return;
    }

    setCreateFieldError(null);
    createMutation.mutate();
  };

  const priceMutation =
    useMutation({
      mutationFn:
        async (): Promise<
          MutationResult | undefined
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
            );
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

  const mappingMutation =
    useMutation({
      mutationFn: async () => {
        if (!importJobId) {
          return;
        }
        return authFetch(
          `/simple-products/imports/${importJobId}/mapping`,
          {
            method: "PUT",
            body: JSON.stringify({
              mapping,
            }),
          }
        );
      },
      onSuccess: () => {
        setImportStatus(
          (current) =>
            current
              ? {
                  ...current,
                  status:
                    "VALIDATING",
                }
              : current
        );
        setImportPollKey(
          (current) =>
            current + 1
        );
        toast.success(
          t(
            "products.mappingAccepted"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.mappingFailed"
            )
          )
        ),
    });

  const retryImportMutation =
    useMutation({
      mutationFn: async () => {
        if (!importJobId) {
          return;
        }
        return authFetch(
          `/simple-products/imports/${importJobId}/retry`,
          {
            method: "POST",
          }
        );
      },
      onSuccess: () => {
        setImportStatus(
          (current) =>
            current
              ? {
                  ...current,
                  status: "QUEUED",
                }
              : current
        );
        setImportPollKey(
          (current) =>
            current + 1
        );
        toast.success(
          t(
            "products.retryQueued"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.retryFailed"
            )
          )
        ),
    });

  useEffect(() => {
    if (!importJobId) {
      return;
    }

    let disposed = false;
    let timer:
      | number
      | undefined;

    const poll = async () => {
      if (!navigator.onLine) {
        timer =
          window.setTimeout(
            poll,
            3000
          );
        return;
      }

      try {
        const status =
          parseProductImportState(
            await authFetch(
              `/simple-products/imports/${importJobId}`
            )
          );

        if (disposed) {
          return;
        }

        setImportStatus(
          status
        );
        setImportLotControlMode(
          status.default_lot_control_mode
        );
        setImportExpiryControlMode(
          status.default_expiry_control_mode
        );

        if (
          status.status ===
          "NEEDS_MAPPING"
        ) {
          setMapping(
            Object.keys(
              status.column_mapping ||
                {}
            ).length
              ? status.column_mapping
              : status.suggested_mapping
          );
        }

        if (
          status.status ===
          "COMPLETED"
        ) {
          toast.success(
            t(
              "products.importCompleted",
              {
                count:
                  status.processed_rows,
              }
            )
          );
          await Promise.all([
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-products",
                ],
              }
            ),
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-product-families",
                ],
              }
            ),
          ]);
          return;
        }

        if (
          !terminalImportStatuses.has(
            status.status
          )
        ) {
          timer =
            window.setTimeout(
              poll,
              1500
            );
        }
      } catch {
        if (!disposed) {
          timer =
            window.setTimeout(
              poll,
              3000
            );
        }
      }
    };

    void poll();

    return () => {
      disposed = true;
      if (
        timer !== undefined
      ) {
        window.clearTimeout(
          timer
        );
      }
    };
  }, [
    authFetch,
    importJobId,
    importPollKey,
    queryClient,
    t,
    isOnline,
  ]);

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

  const cancelCreate =
    () => {
      setCreateOpen(false);
      setCreateFieldError(null);
      setCreateTrackingExpanded(
        false
      );
      setCreateAdvancedExpanded(
        false
      );
      setDraft(emptyDraft);
      if (
        draftStorageKey
      ) {
        sessionStorage.removeItem(
          draftStorageKey
        );
      }
      if (
        companyId &&
        driverId
      ) {
        abandonDurableOperation(
          durableScope(
            companyId,
            driverId,
            "product-create"
          )
        );
      }
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

  const mappingLabelKey = (
    field:
      (typeof importMappingFields)[number]
  ) => {
    const keys = {
      name:
        "products.fields.name",
      family:
        "products.fields.family",
      package_uom:
        "products.fields.packageUom",
      units_per_package:
        "products.fields.unitsPerPackage",
      package_price:
        "products.fields.packagePrice",
      unit_price:
        "products.fields.unitPrice",
      unit_barcode:
        "products.fields.unitBarcode",
      package_barcode:
        "products.fields.packageBarcode",
      lot_control_mode:
        "products.fields.lotControlMode",
      expiry_control_mode:
        "products.fields.expiryControlMode",
    } as const;
    return keys[field];
  };

  return (
    <div
      className="products-a11y-scope flex min-h-0 flex-1 flex-col overflow-hidden"
      dir={i18n.dir()}
    >
      <header className="shrink-0 rounded-[26px] border border-white/70 bg-white/85 px-5 py-4 shadow-sm backdrop-blur-xl">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-slate-950 text-white">
              <Boxes className="h-5 w-5" />
            </span>
            <div>
              <h1 className="text-xl font-black text-slate-950">
                {t(
                  "products.title"
                )}
              </h1>
              <p className="mt-0.5 text-xs font-semibold text-slate-500">
                {t(
                  "products.subtitle"
                )}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
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

      <section className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-[26px] border border-white/70 bg-white/85 shadow-sm backdrop-blur-xl">
        <div className="shrink-0 border-b border-slate-100 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[260px] max-w-md flex-1">
              <Search className="absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchInput}
                maxLength={100}
                onChange={(
                  event
                ) =>
                  setSearchInput(
                    event.target.value
                  )
                }
                placeholder={t(
                  "products.searchPlaceholder"
                )}
                aria-label={t(
                  "products.searchPlaceholder"
                )}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pe-9 ps-3 text-sm font-bold outline-none focus:border-slate-400 focus:bg-white"
              />
            </div>
            <button
              type="button"
              onClick={() =>
                setFiltersOpen(
                  (current) =>
                    !current
                )
              }
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs font-black text-slate-700"
            >
              <Settings2 className="h-4 w-4" />
              {t(
                filtersOpen
                  ? "products.filters.hide"
                  : "products.filters.show"
              )}
            </button>
            {hasProductListControls ? (
              <button
                type="button"
                onClick={() => {
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
                  setSortBy("id");
                  setSortDir("asc");
                  resetProductPagination();
                }}
                className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-black text-slate-600"
              >
                {t(
                  "products.filters.clear"
                )}
              </button>
            ) : null}
          </div>

          {filtersOpen ? (
            <div className="mt-3 grid gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-3 sm:grid-cols-2 xl:grid-cols-4">
              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.family"
                  )}
                </span>
                <input
                  type="search"
                  value={
                    familyFilterSearchInput
                  }
                  maxLength={100}
                  onChange={(event) =>
                    setFamilyFilterSearchInput(
                      event.target.value
                    )
                  }
                  placeholder={t(
                    "products.filters.familySearch"
                  )}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold outline-none focus:border-slate-400"
                />
                <select
                  value={familyFilterId}
                  onChange={(event) => {
                    const nextId =
                      event.target.value;
                    const selected =
                      familyFilterOptions.find(
                        (item) =>
                          String(
                            item.id
                          ) ===
                          nextId
                      );
                    setFamilyFilterId(
                      nextId
                    );
                    setFamilyFilterName(
                      selected?.name ??
                        ""
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold outline-none focus:border-slate-400"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  {familyFilterId &&
                  !familyFilterOptions.some(
                    (item) =>
                      String(item.id) ===
                      familyFilterId
                  ) ? (
                    <option
                      value={
                        familyFilterId
                      }
                    >
                      {familyFilterName ||
                        familyFilterId}
                    </option>
                  ) : null}
                  {familyFilterOptions.map(
                    (
                      family: ProductFamily
                    ) => (
                      <option
                        key={family.id}
                        value={String(
                          family.id
                        )}
                      >
                        {family.name}
                      </option>
                    )
                  )}
                </select>
                {familyFilterOptionsQuery.isError ? (
                  <button
                    type="button"
                    onClick={() =>
                      void familyFilterOptionsQuery.refetch()
                    }
                    className="text-[11px] font-black text-rose-700"
                  >
                    {t(
                      "products.filters.familyLoadFailed"
                    )}
                  </button>
                ) : null}
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.lifecycle"
                  )}
                </span>
                <select
                  value={lifecycleFilter}
                  onChange={(event) => {
                    setLifecycleFilter(
                      event.target
                        .value as ProductLifecycleFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  <option value="ACTIVE">
                    {t(
                      "products.details.lifecycleModes.ACTIVE"
                    )}
                  </option>
                  <option value="RETIRING">
                    {t(
                      "products.details.lifecycleModes.RETIRING"
                    )}
                  </option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.trackingType"
                  )}
                </span>
                <select
                  value={trackingTypeFilter}
                  onChange={(event) => {
                    setTrackingTypeFilter(
                      event.target
                        .value as ProductTrackingTypeFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  {(
                    [
                      "NONE",
                      "LOT",
                      "EXPIRY",
                      "LOT_EXPIRY",
                    ] as const
                  ).map((value) => (
                    <option
                      key={value}
                      value={value}
                    >
                      {t(
                        `products.filters.trackingTypes.${value}`
                      )}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.compatibility"
                  )}
                </span>
                <select
                  value={
                    compatibilityFilter
                  }
                  onChange={(event) => {
                    setCompatibilityFilter(
                      event.target
                        .value as ProductBooleanFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  <option value="true">
                    {t(
                      "products.filters.simple"
                    )}
                  </option>
                  <option value="false">
                    {t(
                      "products.filters.advanced"
                    )}
                  </option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.barcode"
                  )}
                </span>
                <select
                  value={barcodeFilter}
                  onChange={(event) => {
                    setBarcodeFilter(
                      event.target
                        .value as ProductBooleanFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  <option value="true">
                    {t(
                      "products.filters.present"
                    )}
                  </option>
                  <option value="false">
                    {t(
                      "products.filters.missing"
                    )}
                  </option>
                </select>
              </label>

              {canViewPricing ? (
                <label className="space-y-1">
                  <span className="text-[11px] font-black text-slate-500">
                    {t(
                      "products.filters.price"
                    )}
                  </span>
                  <select
                    value={priceFilter}
                    onChange={(event) => {
                      setPriceFilter(
                        event.target
                          .value as ProductBooleanFilter
                      );
                      resetProductPagination();
                    }}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                  >
                    <option value="">
                      {t(
                        "products.filters.all"
                      )}
                    </option>
                    <option value="true">
                      {t(
                        "products.filters.present"
                      )}
                    </option>
                    <option value="false">
                      {t(
                        "products.filters.missing"
                      )}
                    </option>
                  </select>
                </label>
              ) : null}

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.lot"
                  )}
                </span>
                <select
                  value={lotFilter}
                  onChange={(event) => {
                    setLotFilter(
                      event.target
                        .value as ProductBooleanFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  <option value="true">
                    {t(
                      "products.filters.tracked"
                    )}
                  </option>
                  <option value="false">
                    {t(
                      "products.filters.notTracked"
                    )}
                  </option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.expiry"
                  )}
                </span>
                <select
                  value={expiryFilter}
                  onChange={(event) => {
                    setExpiryFilter(
                      event.target
                        .value as ProductBooleanFilter
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="">
                    {t(
                      "products.filters.all"
                    )}
                  </option>
                  <option value="true">
                    {t(
                      "products.filters.tracked"
                    )}
                  </option>
                  <option value="false">
                    {t(
                      "products.filters.notTracked"
                    )}
                  </option>
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.sortBy"
                  )}
                </span>
                <select
                  value={sortBy}
                  onChange={(event) => {
                    setSortBy(
                      event.target
                        .value as ProductSortField
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  {(
                    [
                      "id",
                      "name",
                      "family",
                      "sku",
                      "lifecycle",
                    ] as const
                  ).map((value) => (
                    <option
                      key={value}
                      value={value}
                    >
                      {t(
                        `products.filters.sortFields.${value}`
                      )}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-1">
                <span className="text-[11px] font-black text-slate-500">
                  {t(
                    "products.filters.sortDirection"
                  )}
                </span>
                <select
                  value={sortDir}
                  onChange={(event) => {
                    setSortDir(
                      event.target
                        .value as ProductSortDirection
                    );
                    resetProductPagination();
                  }}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
                >
                  <option value="asc">
                    {t(
                      "products.filters.ascending"
                    )}
                  </option>
                  <option value="desc">
                    {t(
                      "products.filters.descending"
                    )}
                  </option>
                </select>
              </label>
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full min-w-[1050px] text-start text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50 text-xs font-black text-slate-500">
              <tr>
                <th className="px-5 py-3">
                  {t(
                    "products.columns.product"
                  )}
                </th>
                <th className="px-5 py-3">
                  {t(
                    "products.columns.package"
                  )}
                </th>
                <th className="px-5 py-3">
                  {t(
                    "products.columns.unitsPerPackage"
                  )}
                </th>
                <th className="px-5 py-3">
                  {t(
                    "products.columns.tracking"
                  )}
                </th>
                {pricingVisible ? (
                  <>
                    <th className="px-5 py-3">
                      {t(
                        "products.columns.packagePrice"
                      )}
                    </th>
                    <th className="px-5 py-3">
                      {t(
                        "products.columns.unitPrice"
                      )}
                    </th>
                  </>
                ) : null}
                <th className="px-5 py-3">
                  {t(
                    "products.columns.action"
                  )}
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {productsQuery.isLoading ? (
                <tr>
                  <td
                    colSpan={
                      productTableColumnCount
                    }
                    className="py-16 text-center font-bold text-slate-400"
                  >
                    {t(
                      "common.loading"
                    )}
                  </td>
                </tr>
              ) : null}

              {productsQuery.isError ? (
                <tr>
                  <td
                    colSpan={
                      productTableColumnCount
                    }
                    className="py-14 text-center"
                  >
                    <div className="mx-auto max-w-md rounded-2xl bg-rose-50 p-5">
                      <p className="font-black text-rose-900">
                        {t(
                          "products.errors.listLoadTitle"
                        )}
                      </p>
                      <p className="mt-1 text-xs font-semibold leading-6 text-rose-700">
                        {t(
                          "products.errors.listLoadDescription"
                        )}
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          void productsQuery.refetch()
                        }
                        className="mt-3 rounded-xl border border-rose-200 bg-white px-4 py-2 text-xs font-black text-rose-800"
                      >
                        {t(
                          "common.retry"
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ) : null}

              {!productsQuery.isLoading &&
              !productsQuery.isError &&
              !page?.items.length ? (
                <tr>
                  <td
                    colSpan={
                      productTableColumnCount
                    }
                    className="py-16 text-center"
                  >
                    <Boxes className="mx-auto mb-3 h-8 w-8 text-slate-300" />
                    <p className="font-black text-slate-700">
                      {t(
                        "products.emptyTitle"
                      )}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {t(
                        "products.emptyDescription"
                      )}
                    </p>
                  </td>
                </tr>
              ) : null}

              {page?.items.map(
                (item) => (
                  <ProductTableRow
                    key={item.id}
                    item={item}
                    pricingVisible={
                      pricingVisible
                    }
                    canEditPrice={
                      canEditSimplePrice
                    }
                    canEditTracking={
                      canManageCatalog
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
                  />
                )
              )}
            </tbody>
          </table>
        </div>

        {history.length > 0 ||
        page?.next_cursor ? (
          <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
            <button
              type="button"
              disabled={
                !history.length ||
                productsQuery.isFetching
              }
              onClick={() => {
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
              aria-label={t(
                "products.familyPrevious"
              )}
              className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
            </button>
            <button
              type="button"
              disabled={
                !page?.next_cursor ||
                productsQuery.isFetching
              }
              onClick={() => {
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
              aria-label={t(
                "products.familyNext"
              )}
              className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4 rtl:rotate-180" />
            </button>
          </div>
        ) : null}
      </section>

      <ProductDetailDrawer
        product={detailProduct}
        pricingVisible={pricingVisible}
        canEditPrice={
          canEditSimplePrice
        }
        canEditTracking={
          canManageCatalog
        }
        canManageBarcodes={
          canManageCatalog
        }
        canManageAdvancedUom={
          canManageCatalog
        }
        onClose={() =>
          setDetailProduct(null)
        }
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

      <Modal
        isOpen={createOpen}
        onClose={() => {
          if (
            !createMutation.isPending
          ) {
            cancelCreate();
          }
        }}
        title={t(
          "products.addTitle"
        )}
        maxWidth="max-w-2xl"
        footer={
          <>
            <button
              type="button"
              disabled={
                createMutation.isPending
              }
              onClick={
                cancelCreate
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
                createMutation.isPending ||
                !isOnline ||
                !draft.lot_control_mode ||
                !draft.expiry_control_mode
              }
              onClick={submitCreate}
              className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-50"
            >
              {t(
                "products.saveProduct"
              )}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          {!isOnline ? (
            <div className="rounded-2xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
              {t(
                "products.offlineSaveHint"
              )}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-black text-slate-600">
              {t(
                "products.productName"
              )}
              <input
                value={draft.name}
                onChange={(
                  event
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      name:
                        event.target
                          .value,
                    })
                  )
                }
                placeholder={t(
                  "products.productNamePlaceholder"
                )}
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
              />
            </label>

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.family"
              )}{" "}
              <span className="font-bold text-slate-400">
                {t(
                  "common.optional"
                )}
              </span>
              <input
                list="product-family-options"
                value={
                  draft.family
                }
                onChange={(
                  event
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      family:
                        event.target
                          .value,
                    })
                  )
                }
                placeholder={t(
                  "products.familyPlaceholder"
                )}
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none"
              />
              <datalist id="product-family-options">
                {familyOptions.map(
                  (family) => (
                    <option
                      key={
                        family.id
                      }
                      value={
                        family.name
                      }
                    />
                  )
                )}
              </datalist>
            </label>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3">
              <h3 className="text-sm font-black text-slate-900">
                {t(
                  "products.tracking.createTitle"
                )}
              </h3>
              <p className="mt-1 text-xs font-semibold leading-6 text-slate-500">
                {t(
                  "products.tracking.createHint"
                )}
              </p>
            </div>

            {!draft.lot_control_mode ||
            !draft.expiry_control_mode ? (
              trackingDefaultsQuery.isError ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
                  <span className="text-xs font-bold text-rose-800">
                    {t(
                      "products.errors.trackingDefaultsLoad"
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      void trackingDefaultsQuery.refetch()
                    }
                    className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                  >
                    {t(
                      "common.retry"
                    )}
                  </button>
                </div>
              ) : (
                <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                  {t(
                    "products.trackingDefaultsLoading"
                  )}
                </div>
              )
            ) : (
              <div className="space-y-3">
                <div className="rounded-xl bg-slate-50 p-3">
                  <p className="text-xs font-black leading-6 text-slate-800">
                    {t(
                      "products.tracking.createSummary",
                      {
                        lot: t(
                          `products.tracking.lotModes.${draft.lot_control_mode}`
                        ),
                        expiry: t(
                          `products.tracking.expiryModes.${draft.expiry_control_mode}`
                        ),
                      }
                    )}
                  </p>
                  <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                    {t(
                      createTrackingUsesCompanyDefaults
                        ? "products.tracking.createCompanyScope"
                        : "products.tracking.createCustomScope"
                    )}
                  </p>
                </div>

                <p className="text-[11px] font-semibold leading-5 text-slate-500">
                  {t(
                    "products.quickCreate.trackingAdvancedHint"
                  )}
                </p>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
            <label className="flex cursor-pointer items-center justify-between gap-4">
              <span className="text-xs font-black text-slate-700">
                {draft.has_package
                  ? t(
                      "products.hasOuterPackage"
                    )
                  : t(
                      "products.noOuterPackage"
                    )}
              </span>
              <input
                type="checkbox"
                checked={
                  draft.has_package
                }
                onChange={(
                  event
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      has_package:
                        event.target
                          .checked,
                      units_per_package:
                        event.target
                          .checked
                          ? current.units_per_package ===
                            "1"
                            ? "50"
                            : current.units_per_package
                          : "1",
                      package_price:
                        event.target
                          .checked
                          ? current.package_price
                          : "",
                      package_barcode:
                        event.target
                          .checked
                          ? current.package_barcode
                          : "",
                    })
                  )
                }
                className="h-4 w-4"
              />
            </label>
          </div>

          {draft.has_package ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.packageType"
                )}
                <select
                  value={
                    draft.package_uom_code
                  }
                  onChange={(
                    event
                  ) =>
                    setDraft(
                      (current) => ({
                        ...current,
                        package_uom_code:
                          event.target
                            .value,
                      })
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold"
                >
                  {packageUoms.map(
                    (uom) => (
                      <option
                        key={
                          uom.code
                        }
                        value={
                          uom.code
                        }
                      >
                        {t(
                          `uom.${uom.code}`
                        )}
                      </option>
                    )
                  )}
                </select>
              </label>

              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.unitsPerPackage"
                )}
                <input
                  inputMode="numeric"
                  value={
                    draft.units_per_package
                  }
                  onChange={(
                    event
                  ) =>
                    setDraft(
                      (current) => ({
                        ...current,
                        units_per_package:
                          event.target
                            .value,
                      })
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold"
                />
              </label>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            {draft.has_package ? (
              <label className="text-xs font-black text-slate-600">
                {t(
                  "products.packagePrice"
                )}{" "}
                <span className="font-bold text-slate-400">
                  {t(
                    "common.optional"
                  )}
                </span>
                <input
                  inputMode="decimal"
                  value={
                    draft.package_price
                  }
                  onChange={(
                    event
                  ) =>
                    setDraft(
                      (current) => ({
                        ...current,
                        package_price:
                          event.target
                            .value,
                      })
                    )
                  }
                  placeholder={t(
                    "products.packagePricePlaceholder"
                  )}
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black"
                />
              </label>
            ) : null}

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.unitPrice"
              )}{" "}
              {draft.has_package ? (
                <span className="font-bold text-slate-400">
                  {t(
                    "common.optional"
                  )}
                </span>
              ) : null}
              <input
                inputMode="decimal"
                value={
                  draft.unit_price
                }
                onChange={(
                  event
                ) =>
                  setDraft(
                    (current) => ({
                      ...current,
                      unit_price:
                        event.target
                          .value,
                    })
                  )
                }
                placeholder={t(
                  "products.unitPricePlaceholder"
                )}
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-black"
              />
            </label>
          </div>

          {draftDerived ? (
            <div className="rounded-2xl bg-emerald-50 p-3 text-xs font-bold leading-6 text-emerald-900">
              {draft.has_package &&
              draftDerived.independent
                ? t(
                    "products.independentPrices"
                  )
                : draft.has_package
                  ? t(
                      "products.derivedPrice"
                    )
                  : t(
                      "products.unitPrice"
                    )}
            </div>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white">
            <button
              type="button"
              onClick={() =>
                setCreateAdvancedExpanded(
                  (current) => !current
                )
              }
              aria-expanded={
                createAdvancedExpanded
              }
              className="flex w-full items-center justify-between gap-4 p-4 text-start"
            >
              <span>
                <span className="block text-sm font-black text-slate-900">
                  {t(
                    "products.quickCreate.advancedTitle"
                  )}
                </span>
                <span className="mt-1 block text-[11px] font-semibold leading-5 text-slate-500">
                  {t(
                    "products.quickCreate.advancedHint"
                  )}
                </span>
              </span>
              <span className="shrink-0 text-xs font-black text-slate-600">
                {t(
                  createAdvancedExpanded
                    ? "products.quickCreate.hideAdvanced"
                    : "products.quickCreate.showAdvanced"
                )}
              </span>
            </button>

            {createAdvancedExpanded ? (
              <div className="space-y-4 border-t border-slate-100 p-4">
                <div className="rounded-xl bg-slate-50 p-3 text-[11px] font-semibold leading-5 text-slate-600">
                  {t(
                    "products.quickCreate.systemManagedHint"
                  )}
                </div>

                <div className="space-y-3">
                  <div>
                    <h4 className="text-xs font-black text-slate-800">
                      {t(
                        "products.tracking.createTitle"
                      )}
                    </h4>
                    <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                      {t(
                        "products.tracking.createOnlyThisProduct"
                      )}
                    </p>
                  </div>

                  {!createTrackingExpanded ? (
                    <button
                      type="button"
                      onClick={() =>
                        setCreateTrackingExpanded(
                          true
                        )
                      }
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                    >
                      {t(
                        "products.tracking.createChange"
                      )}
                    </button>
                  ) : (
                    <div className="space-y-3">
                      <ProductTrackingFields
                        lotControlMode={
                          draft.lot_control_mode
                        }
                        expiryControlMode={
                          draft.expiry_control_mode
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
                      />

                      {!createTrackingUsesCompanyDefaults ? (
                        <button
                          type="button"
                          onClick={() => {
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
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                        >
                          {t(
                            "products.tracking.createReset"
                          )}
                        </button>
                      ) : null}
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-100 pt-4">
                  <h4 className="text-xs font-black text-slate-800">
                    {t(
                      "products.barcodeSection"
                    )}
                  </h4>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-500">
                {t(
                  "products.unitBarcode"
                )}
                <input
                  value={
                    draft.unit_barcode
                  }
                  onChange={(
                    event
                  ) =>
                    setDraft(
                      (current) => ({
                        ...current,
                        unit_barcode:
                          event.target
                            .value,
                      })
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                />
              </label>

              {draft.has_package ? (
                <label className="text-xs font-bold text-slate-500">
                  <span className="flex items-center justify-between gap-2">
                    <span>
                      {t(
                        "products.packageBarcode"
                      )}
                    </span>
                    <button
                      type="button"
                      disabled={
                        !draft.unit_barcode.trim()
                      }
                      onClick={() => {
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
                      title={t(
                        "products.copyBarcode"
                      )}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-black text-slate-600 disabled:opacity-30"
                    >
                      <Copy className="h-3 w-3" />
                      {t(
                        "products.copyBarcode"
                      )}
                    </button>
                  </span>
                  <input
                    value={
                      draft.package_barcode
                    }
                    onChange={(
                      event
                    ) =>
                      setDraft(
                        (current) => ({
                          ...current,
                          package_barcode:
                            event.target
                              .value,
                        })
                      )
                    }
                    className="mt-1.5 w-full rounded-xl border border-slate-200 p-2.5 font-mono"
                  />
                </label>
              ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </Modal>

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
                  inputMode="decimal"
                  value={
                    editPackagePrice
                  }
                  onChange={(
                    event
                  ) =>
                    setEditPackagePrice(
                      event.target.value
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
                />
              </label>
            ) : null}

            <label className="text-xs font-black text-slate-600">
              {t(
                "products.unitPrice"
              )}
              <input
                inputMode="decimal"
                value={
                  editUnitPrice
                }
                onChange={(
                  event
                ) =>
                  setEditUnitPrice(
                    event.target.value
                  )
                }
                className="mt-1.5 w-full rounded-xl border p-2.5 font-black"
              />
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

      <Modal
        isOpen={importOpen}
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
        title={t(
          "products.importTitle"
        )}
        maxWidth="max-w-2xl"
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-sky-50 p-3">
            <p className="text-xs font-bold leading-6 text-sky-900">
              {t(
                "products.importIntro"
              )}
            </p>
            <button
              type="button"
              onClick={
                downloadTemplate
              }
              className="rounded-xl bg-white px-3 py-2 text-xs font-black text-sky-900 shadow-sm"
            >
              {t(
                "products.downloadTemplate"
              )}
            </button>
          </div>

          {!importJobId ? (
            <>
              <div className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="mb-3">
                  <h3 className="text-sm font-black text-slate-900">
                    {t(
                      "products.importTrackingTitle"
                    )}
                  </h3>
                  <p className="mt-1 text-xs leading-6 text-slate-500">
                    {t(
                      "products.importTrackingHint"
                    )}
                  </p>
                </div>

                {trackingDefaultsQuery.isLoading ? (
                  <div className="rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                    {t(
                      "products.trackingDefaultsLoading"
                    )}
                  </div>
                ) : trackingDefaultsQuery.isError ? (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
                    <span className="text-xs font-bold text-rose-800">
                      {t(
                        "products.errors.trackingDefaultsLoad"
                      )}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        void trackingDefaultsQuery.refetch()
                      }
                      className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                    >
                      {t(
                        "common.retry"
                      )}
                    </button>
                  </div>
                ) : importLotControlMode &&
                  importExpiryControlMode ? (
                  <div className="space-y-3">
                    <div className="rounded-xl bg-slate-50 p-3">
                      <p className="text-xs font-black leading-6 text-slate-800">
                        {t(
                          "products.importTrackingSummary",
                          {
                            lot: t(
                              `products.tracking.lotModes.${importLotControlMode}`
                            ),
                            expiry: t(
                              `products.tracking.expiryModes.${importExpiryControlMode}`
                            ),
                          }
                        )}
                      </p>
                      <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
                        {t(
                          importTrackingUsesCompanyDefaults
                            ? "products.importTrackingCompanyScope"
                            : "products.importTrackingCustomScope"
                        )}
                      </p>
                    </div>

                    {!importTrackingExpanded ? (
                      <button
                        type="button"
                        onClick={() =>
                          setImportTrackingExpanded(
                            true
                          )
                        }
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                      >
                        {t(
                          "products.importTrackingChange"
                        )}
                      </button>
                    ) : (
                      <div className="space-y-3">
                        <ProductTrackingFields
                          lotControlMode={
                            importLotControlMode
                          }
                          expiryControlMode={
                            importExpiryControlMode
                          }
                          onLotControlModeChange={
                            setImportLotControlMode
                          }
                          onExpiryControlModeChange={
                            setImportExpiryControlMode
                          }
                        />

                        <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
                          {t(
                            "products.importTrackingOnlyThisImport"
                          )}
                        </p>

                        {!importTrackingUsesCompanyDefaults ? (
                          <button
                            type="button"
                            onClick={() => {
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
                            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                          >
                            {t(
                              "products.importTrackingReset"
                            )}
                          </button>
                        ) : null}

                        <p className="text-[11px] leading-5 text-slate-500">
                          {t(
                            "products.importTrackingOverrideHint"
                          )}
                        </p>
                        <p className="text-[11px] leading-5 text-slate-500">
                          {t(
                            "products.importTrackingValueHint",
                            {
                              none: t(
                                "products.tracking.importValues.NONE"
                              ),
                              optional: t(
                                "products.tracking.importValues.OPTIONAL"
                              ),
                              required: t(
                                "products.tracking.importValues.REQUIRED"
                              ),
                            }
                          )}
                        </p>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>

              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="hidden"
                onChange={(
                  event
                ) =>
                  chooseFile(
                    event.target.files?.[0] ??
                      null
                  )
                }
              />

              <button
                type="button"
                onClick={() =>
                  fileRef.current?.click()
                }
                onDragEnter={(
                  event
                ) => {
                  event.preventDefault();
                  setDragging(
                    true
                  );
                }}
                onDragOver={(
                  event
                ) => {
                  event.preventDefault();
                  setDragging(
                    true
                  );
                }}
                onDragLeave={() =>
                  setDragging(
                    false
                  )
                }
                onDrop={(
                  event
                ) => {
                  event.preventDefault();
                  setDragging(
                    false
                  );
                  chooseFile(
                    event.dataTransfer
                      .files?.[0] ??
                      null
                  );
                }}
                className={`flex min-h-48 w-full flex-col items-center justify-center rounded-[24px] border border-dashed text-center transition ${
                  dragging
                    ? "border-slate-950 bg-slate-100"
                    : "border-slate-300 bg-slate-50 hover:bg-white"
                }`}
              >
                <Upload className="mb-3 h-8 w-8 text-slate-400" />
                <strong className="text-sm text-slate-700">
                  {importFile?.name ??
                    t(
                      "products.dropFile"
                    )}
                </strong>
                <span className="mt-1 text-xs text-slate-400">
                  {t(
                    "products.importLimit"
                  )}
                </span>
              </button>

              <button
                type="button"
                disabled={
                  !importFile ||
                  !importLotControlMode ||
                  !importExpiryControlMode ||
                  trackingDefaultsQuery.isLoading ||
                  trackingDefaultsQuery.isError ||
                  importMutation.isPending ||
                  !isOnline
                }
                onClick={() =>
                  importMutation.mutate()
                }
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
              >
                {t(
                  "products.uploadAndStart"
                )}
              </button>
            </>
          ) : null}

          {importJobId &&
          !importStatus ? (
            <div className="rounded-2xl bg-slate-50 p-5 text-center text-sm font-black text-slate-600">
              {t(
                "products.queued"
              )}
            </div>
          ) : null}

          {importStatus?.status ===
          "NEEDS_MAPPING" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
                {t(
                  "products.mappingIntro"
                )}
              </div>

              {importMappingFields.map(
                (field) => (
                  <label
                    key={field}
                    className="grid gap-2 text-xs font-black text-slate-600 sm:grid-cols-[180px_1fr] sm:items-center"
                  >
                    <span>
                      {t(
                        mappingLabelKey(
                          field
                        )
                      )}
                    </span>
                    <select
                      value={
                        mapping[
                          field
                        ] ?? ""
                      }
                      onChange={(
                        event
                      ) =>
                        setMapping(
                          (
                            current
                          ) => ({
                            ...current,
                            [field]:
                              event
                                .target
                                .value,
                          })
                        )
                      }
                      className="rounded-xl border border-slate-200 bg-white p-2.5"
                    >
                      <option value="">
                        {t(
                          "products.unmapped"
                        )}
                      </option>
                      {importStatus.detected_headers.map(
                        (
                          header
                        ) => (
                          <option
                            key={
                              header
                            }
                            value={
                              header
                            }
                          >
                            {
                              header
                            }
                          </option>
                        )
                      )}
                    </select>
                  </label>
                )
              )}

              <button
                type="button"
                disabled={
                  mappingMutation.isPending ||
                  !isOnline
                }
                onClick={() =>
                  mappingMutation.mutate()
                }
                className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
              >
                {t(
                  "products.continueImport"
                )}
              </button>
            </div>
          ) : null}

          {importStatus &&
          ![
            "NEEDS_MAPPING",
            "VALIDATION_FAILED",
            "FAILED",
            "COMPLETED",
          ].includes(
            importStatus.status
          ) ? (
            <div className="rounded-[22px] border border-slate-200 p-4">
              <div className="flex items-center justify-between text-xs font-black">
                <span>
                  {importStatus.status ===
                  "IMPORTING"
                    ? t(
                        "products.importingProducts"
                      )
                    : t(
                        "products.preparingImport"
                      )}
                </span>
                <span>
                  {
                    importStatus.processed_rows
                  }{" "}
                  /{" "}
                  {importStatus.valid_rows ||
                    importStatus.total_rows}
                </span>
              </div>

              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-slate-950 transition-all"
                  style={{
                    width: `${importProgress}%`,
                  }}
                />
              </div>
              <p className="mt-3 text-[11px] text-slate-500">
                {t(
                  "products.backgroundHint"
                )}
              </p>
            </div>
          ) : null}

          {importStatus?.status ===
          "VALIDATION_FAILED" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-900">
                {t(
                  "products.validationFailed",
                  {
                    count:
                      importStatus.failed_rows,
                  }
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!isOnline}
                  onClick={() =>
                    void downloadErrorReport()
                  }
                  className="rounded-xl border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800 disabled:opacity-40"
                >
                  {t(
                    "products.downloadErrors"
                  )}
                </button>
                <button
                  type="button"
                  onClick={resetImport}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700"
                >
                  {t(
                    "products.newImport"
                  )}
                </button>
              </div>

              <div className="max-h-64 overflow-auto rounded-xl border">
                {importStatus.errors.map(
                  (error) => {
                    const key =
                      error.code
                        ? `errors.codes.${error.code}`
                        : "";
                    const message =
                      key &&
                      i18n.exists(
                        key
                      )
                        ? t(key)
                        : t(
                            "network.serverError"
                          );
                    return (
                      <div
                        key={`${error.row_number}-${error.code}`}
                        className="border-b p-3 text-xs last:border-b-0"
                      >
                        <strong>
                          {t(
                            "products.rowNumber",
                            {
                              row:
                                error.row_number,
                            }
                          )}
                        </strong>
                        <span className="ms-2 text-rose-700">
                          {
                            message
                          }
                        </span>
                      </div>
                    );
                  }
                )}
              </div>
            </div>
          ) : null}

          {importStatus?.status ===
          "FAILED" ? (
            <div className="space-y-3">
              <div className="rounded-2xl bg-rose-50 p-4 text-xs font-bold leading-6 text-rose-900">
                {t(
                  "products.importFailed"
                )}
              </div>
              <div className="flex flex-wrap gap-2">
              {importStatus.error_summary
                ?.retryable ===
              true ? (
                <button
                  type="button"
                  disabled={
                    retryImportMutation.isPending ||
                    !isOnline
                  }
                  onClick={() =>
                    retryImportMutation.mutate()
                  }
                  className="w-full rounded-xl bg-slate-950 px-4 py-3 text-sm font-black text-white disabled:opacity-40"
                >
                  {t(
                    "common.retry"
                  )}
                </button>
              ) : null}
                <button
                  type="button"
                  onClick={resetImport}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-black text-slate-700"
                >
                  {t(
                    "products.newImport"
                  )}
                </button>
              </div>
            </div>
          ) : null}

          {importStatus?.status ===
          "COMPLETED" ? (
            <div className="rounded-2xl bg-emerald-50 p-5 text-center">
              <strong className="text-sm text-emerald-900">
                {t(
                  "products.importCompleted",
                  {
                    count:
                      importStatus.processed_rows,
                  }
                )}
              </strong>
              <button
                type="button"
                onClick={() => {
                  setImportOpen(
                    false
                  );
                  setImportFile(
                    null
                  );
                  setImportJobId(
                    null
                  );
                  setImportStatus(
                    null
                  );
                  setMapping({});
                  setImportTrackingExpanded(
                    false
                  );
                  if (
                    importSessionKey
                  ) {
                    sessionStorage.removeItem(
                      importSessionKey
                    );
                  }
                }}
                className="mt-4 block w-full rounded-xl bg-emerald-900 px-4 py-2.5 text-xs font-black text-white"
              >
                {t(
                  "common.close"
                )}
              </button>
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}
