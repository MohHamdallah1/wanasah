import {
  useQueryClient,
} from "@tanstack/react-query";
import {
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { ProductBarcodeManager } from "@/pages/products/barcode/ProductBarcodeManager";
import { ProductsPageHeader } from "@/pages/products/ProductsPageHeader";
import { ProductDetailDrawer } from "@/pages/products/detail/ProductDetailDrawer";
import { useProductBarcodeWorkflow } from "@/pages/products/barcode/useProductBarcodeWorkflow";
import { useProductDetailWorkflow } from "@/pages/products/detail/useProductDetailWorkflow";
import { ProductDisplayPreferencesModal } from "@/pages/products/display-preferences/ProductDisplayPreferencesModal";
import { createProductDisplayPreferenceActions } from "@/pages/products/display-preferences/createProductDisplayPreferenceActions";
import { useProductDisplayPreferencesState } from "@/pages/products/display-preferences/useProductDisplayPreferencesState";
import { ProductFamiliesManager } from "@/pages/products/family/ProductFamiliesManager";
import { ProductFamilyReassignDialog } from "@/pages/products/family/ProductFamilyReassignDialog";
import { useProductFamiliesWorkflow } from "@/pages/products/family/useProductFamiliesWorkflow";
import { useProductFamilyReassignWorkflow } from "@/pages/products/family/useProductFamilyReassignWorkflow";
import { ProductLifecycleManager } from "@/pages/products/lifecycle/ProductLifecycleManager";
import { useProductLifecycleWorkflow } from "@/pages/products/lifecycle/useProductLifecycleWorkflow";
import { CreateProductModal } from "@/pages/products/create/CreateProductModal";
import { useCreateProductWorkflow } from "@/pages/products/create/useCreateProductWorkflow";
import { ImportProductModal } from "@/pages/products/import/ImportProductModal";
import { ProductImportReceiptBanner } from "@/pages/products/import/ProductImportReceiptBanner";
import type { ProductImportState } from "@/pages/products/contracts";
import { useImportProductWorkflow } from "@/pages/products/import/useImportProductWorkflow";
import { ProductsListSection } from "@/pages/products/list/ProductsListSection";
import { useProductsListWorkflow } from "@/pages/products/list/useProductsListWorkflow";
import { PriceEditModal } from "@/pages/products/pricing/PriceEditModal";
import { usePriceEditWorkflow } from "@/pages/products/pricing/usePriceEditWorkflow";
import { ProductRenameDialog } from "@/pages/products/rename/ProductRenameDialog";
import { deriveProductsCapabilities } from "@/pages/products/deriveProductsCapabilities";
import { useProductsIdentityScopeReset } from "@/pages/products/useProductsIdentityScopeReset";
import { useProductRenameWorkflow } from "@/pages/products/rename/useProductRenameWorkflow";
import { ProductTrackingOverlays } from "@/pages/products/tracking/ProductTrackingOverlays";
import { useProductTrackingWorkflow } from "@/pages/products/tracking/useProductTrackingWorkflow";
import { useTrackingDefaultsQuery } from "@/pages/products/tracking/useTrackingDefaultsQuery";

export default function ProductsPage() {
  const { t, i18n } =
    useTranslation();
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
  const [
    lastImportReceipt,
    setLastImportReceipt,
  ] = useState<{
    companyId: number;
    jobId: string;
    imported: number;
    needsReview: number;
  } | null>(null);

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
      driverId,
      authFetch,
      canViewPricing,
      displayPreferences,
      online: isOnline,
    });

  const onProductChanged =
    async () => {
      await queryClient.invalidateQueries(
        {
          queryKey: [
            "simple-products",
          ],
        }
      );
    };

  const renameWorkflow =
    useProductRenameWorkflow({
      companyId,
      driverId,
    });

  const barcodeWorkflow =
    useProductBarcodeWorkflow({
      companyId,
      driverId,
      onChanged:
        onProductChanged,
    });

  const lifecycleWorkflow =
    useProductLifecycleWorkflow({
      onChanged:
        onProductChanged,
    });

  const familiesWorkflow =
    useProductFamiliesWorkflow({
      companyId,
      driverId,
    });

  const familyReassignWorkflow =
    useProductFamilyReassignWorkflow({
      companyId,
      driverId,
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

  const rememberCompletedImport = (
    status: ProductImportState | null,
  ) => {
    if (
      companyId === null ||
      !status ||
      (
        status.status !== "COMPLETED" &&
        status.status !== "COMPLETED_WITH_ERRORS"
      )
    ) {
      return;
    }

    setLastImportReceipt({
      companyId,
      jobId: status.job_id,
      imported: status.imported_rows,
      needsReview:
        status.invalid_rows +
        status.import_failed_rows,
    });
  };

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

  const detailWorkflow =
    useProductDetailWorkflow({
      detailSections:
        displayPreferences
          .detailSections,
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
      ...detailWorkflow.identityScope,
      ...renameWorkflow.identityScope,
      ...barcodeWorkflow.identityScope,
      ...familyReassignWorkflow.identityScope,
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
      className="products-a11y-scope flex min-h-0 flex-1 flex-col gap-2 overflow-visible"
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
        onOpenFamilies={
          familiesWorkflow.openFamilies
        }
        onOpenCreateProduct={
          createWorkflow.openCreateProduct
        }
      />

      {lastImportReceipt?.companyId === companyId ? (
        <ProductImportReceiptBanner
          imported={lastImportReceipt.imported}
          needsReview={lastImportReceipt.needsReview}
          hasFilters={listWorkflow.section.results.hasResultCriteria}
          onClearFilters={listWorkflow.section.results.onClearCriteria}
          onDismiss={() => setLastImportReceipt(null)}
        />
      ) : null}

      <ProductsListSection
        summary={listWorkflow.section.summary}
        toolbar={
          listWorkflow.section.toolbar
        }
        activeFilters={
          listWorkflow.section
            .activeFilters
        }
        filters={
          listWorkflow.section.filters
        }
        results={{
          ...listWorkflow.section.results,
          isNarrowViewport,
          canEditPrice:
            canEditSimplePrice,
          canRenameProduct:
            canManageCatalog,
          canReassignFamily:
            canManageCatalog,
          canEditTracking:
            canManageCatalog,
          canManageBarcodes:
            canManageCatalog,
          canManageLifecycle,
          onOpenDetails:
            detailWorkflow.openProductDetails,
          onRenameProduct:
            renameWorkflow.openRenameProduct,
          onEditPrice:
            priceWorkflow.openPriceEditor,
          onReassignFamily:
            familyReassignWorkflow.openFamilyReassign,
          onEditTracking:
            trackingWorkflow.openTrackingEditor,
          onManageBarcodes:
            barcodeWorkflow.openBarcodeManager,
          onManageLifecycle:
            lifecycleWorkflow.openLifecycleManager,
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
        {...detailWorkflow.drawerProps}
      />

      <ProductRenameDialog
        {...renameWorkflow.dialogProps}
      />

      <ProductFamilyReassignDialog
        {...familyReassignWorkflow.dialogProps}
      />

      <ProductLifecycleManager
        {...lifecycleWorkflow.managerProps}
      />

      <ProductBarcodeManager
        {...barcodeWorkflow.managerProps}
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
        {...familiesWorkflow.managerProps}
      />

      <ImportProductModal
        {...importWorkflow.modalProps}
        onClose={() => {
          rememberCompletedImport(importWorkflow.modalProps.status);
          importWorkflow.modalProps.onClose();
        }}
        onCompletedClose={() => {
          rememberCompletedImport(importWorkflow.modalProps.status);
          importWorkflow.modalProps.onCompletedClose();
        }}
      />
    </div>
  );
}
