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
import { useImportProductWorkflow } from "@/pages/products/import/useImportProductWorkflow";
import { ProductsListSection } from "@/pages/products/list/ProductsListSection";
import { useProductsListWorkflow } from "@/pages/products/list/useProductsListWorkflow";
import { PriceEditModal } from "@/pages/products/pricing/PriceEditModal";
import { usePriceEditWorkflow } from "@/pages/products/pricing/usePriceEditWorkflow";
import { ProductRenameDialog } from "@/pages/products/ProductRenameDialog";
import { deriveProductsCapabilities } from "@/pages/products/deriveProductsCapabilities";
import { useProductsIdentityScopeReset } from "@/pages/products/useProductsIdentityScopeReset";
import { useProductRenameState } from "@/pages/products/rename/useProductRenameState";
import { ProductTrackingOverlays } from "@/pages/products/tracking/ProductTrackingOverlays";
import { useProductTrackingWorkflow } from "@/pages/products/tracking/useProductTrackingWorkflow";
import { useTrackingDefaultsQuery } from "@/pages/products/tracking/useTrackingDefaultsQuery";

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
    displayPreferences,
    setDisplayPreferences,
    displayPreferencesOpen,
    setDisplayPreferencesOpen,
    openDisplayPreferences,
    closeDisplayPreferences,
  } =
    useProductDisplayPreferencesState();

  const listWorkflow =
    useProductsListWorkflow({
      companyId,
      authFetch,
      canViewPricing,
      displayPreferences,
    });

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
    familiesOpen,
    openFamilies,
    closeFamilies,
  } = useProductFamiliesState();
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
      ...listWorkflow.paginationScope,
    });

  const importWorkflow =
    useImportProductWorkflow({
      companyId,
      driverId,
      authFetch,
      queryClient,
      t,
      i18n,
      online: isOnline,
      trackingDefaults:
        trackingDefaultsQuery.data,
      trackingDefaultsLoading:
        trackingDefaultsQuery.isLoading,
      trackingDefaultsError:
        trackingDefaultsQuery.isError,
      retryTrackingDefaults: () =>
        void trackingDefaultsQuery.refetch(),
    });

  const priceWorkflow =
    usePriceEditWorkflow({
      companyId,
      driverId,
      authFetch,
      queryClient,
      t,
      online: isOnline,
    });

  const trackingWorkflow =
    useProductTrackingWorkflow({
      companyId,
      driverId,
      authFetch,
      queryClient,
      t,
      online: isOnline,
      defaults:
        trackingDefaultsQuery.data,
      importTrackingBridge:
        importWorkflow.trackingMutationScope,
    });

  useProductsIdentityScopeReset({
    companyId,
    driverId,
    list:
      listWorkflow.identityScope,
    display: {
      setDisplayPreferences,
    },
    targets: {
      setDetailProduct,
      setRenameProduct,
      setBarcodeProduct,
    },
    pricing:
      priceWorkflow.identityScope,
    importScope:
      importWorkflow.identityScope,
    create:
      createWorkflow.identityScope,
    tracking:
      trackingWorkflow.identityScope,
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
    openPriceEditor:
      priceWorkflow.openPriceEditor,
    openTrackingEditor:
      trackingWorkflow.openTrackingEditor,
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
    ...listWorkflow.displayPreferenceScope,
    setDisplayPreferencesOpen,
    t,
  });

  return (
    <div
      className="products-a11y-scope flex min-h-0 flex-1 flex-col overflow-hidden"
      dir={i18n.dir()}
    >
      <ProductsPageHeader
        isFetching={
          listWorkflow.isFetching
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
        onRefresh={
          listWorkflow.refresh
        }
        onOpenDisplayPreferences={
          openDisplayPreferences
        }
        onOpenTrackingDefaults={
          trackingWorkflow.openTrackingDefaults
        }
        onOpenImport={
          importWorkflow.openImport
        }
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
        filtersOpen={
          listWorkflow.section
            .filtersOpen
        }
        toolbar={
          listWorkflow.section.toolbar
        }
        filters={
          listWorkflow.section.filters
        }
        results={{
          ...listWorkflow.section.results,
          isNarrowViewport,
          canEditPrice:
            canEditSimplePrice,
          canEditTracking:
            canManageCatalog,
          onOpenDetails:
            openProductDetails,
          onEditPrice:
            priceWorkflow.openPriceEditor,
          onEditTracking:
            trackingWorkflow.openTrackingEditor,
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
        pricingVisible={listWorkflow.pricingVisible}
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

      <ProductTrackingOverlays
        {...trackingWorkflow.overlaysProps}
      />

      <CreateProductModal
        {...createWorkflow.modalProps}
      />

      <PriceEditModal
        {...priceWorkflow.modalProps}
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
        {...importWorkflow.modalProps}
      />
    </div>
  );
}
