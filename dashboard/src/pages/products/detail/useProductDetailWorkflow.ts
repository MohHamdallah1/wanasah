import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { createProductDetailActions } from "@/pages/products/detail/createProductDetailActions";
import { useProductDetailState } from "@/pages/products/detail/useProductDetailState";

type Params = {
  pricingVisible: boolean;
  canEditPrice: boolean;
  canManageCatalog: boolean;
  canManageLifecycle: boolean;
  detailSections:
    ProductDisplayPreferences["detailSections"];
  openRenameProduct: (
    product: SimpleProduct
  ) => void;
  openPriceEditor: (
    product: SimpleProduct
  ) => void;
  openTrackingEditor: (
    product: SimpleProduct
  ) => void;
  openLifecycleManager: (
    product: SimpleProduct
  ) => void;
  openBarcodeManager: (
    product: SimpleProduct
  ) => void;
  navigate: (to: string) => void;
};

export function useProductDetailWorkflow({
  pricingVisible,
  canEditPrice,
  canManageCatalog,
  canManageLifecycle,
  detailSections,
  openRenameProduct,
  openPriceEditor,
  openTrackingEditor,
  openLifecycleManager,
  openBarcodeManager,
  navigate,
}: Params) {
  const {
    detailProduct,
    setDetailProduct,
    openProductDetails,
    closeProductDetails,
  } = useProductDetailState();

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

  return {
    openProductDetails,
    identityScope: {
      setDetailProduct,
    },
    drawerProps: {
      product:
        detailProduct,
      pricingVisible,
      canEditPrice,
      canRenameProduct:
        canManageCatalog,
      canEditTracking:
        canManageCatalog,
      canManageBarcodes:
        canManageCatalog,
      canManageLifecycle,
      canManageAdvancedUom:
        canManageCatalog,
      detailSections,
      onClose:
        closeProductDetails,
      onRenameProduct:
        renameProductFromDetails,
      onEditPrice:
        editPriceFromDetails,
      onEditTracking:
        editTrackingFromDetails,
      onManageLifecycle:
        manageLifecycleFromDetails,
      onManageBarcodes:
        manageBarcodesFromDetails,
      onManageAdvancedUom:
        manageAdvancedUomFromDetails,
    },
  };
}
