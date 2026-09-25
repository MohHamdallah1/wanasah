import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Params = {
  closeProductDetails: () => void;
  openRenameProduct: (
    product: SimpleProduct
  ) => void;
  openFamilyReassign: (
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

export function createProductDetailActions({
  closeProductDetails,
  openRenameProduct,
  openFamilyReassign,
  openPriceEditor,
  openTrackingEditor,
  openLifecycleManager,
  openBarcodeManager,
  navigate,
}: Params) {
  const renameProductFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openRenameProduct(product);
  };

  const reassignFamilyFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openFamilyReassign(product);
  };

  const editPriceFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openPriceEditor(product);
  };

  const editTrackingFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openTrackingEditor(product);
  };

  const manageLifecycleFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openLifecycleManager(product);
  };

  const manageBarcodesFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    openBarcodeManager(product);
  };

  const manageAdvancedUomFromDetails = (
    product: SimpleProduct
  ) => {
    closeProductDetails();
    navigate(
      `/products/advanced-uom?variant=${product.id}`
    );
  };

  return {
    renameProductFromDetails,
    reassignFamilyFromDetails,
    editPriceFromDetails,
    editTrackingFromDetails,
    manageLifecycleFromDetails,
    manageBarcodesFromDetails,
    manageAdvancedUomFromDetails,
  };
}
