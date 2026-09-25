import { useProductBarcodeState } from "@/pages/products/barcode/useProductBarcodeState";

type Params = {
  companyId: number | null;
  driverId: number | null;
  onChanged: () =>
    void | Promise<void>;
};

export function useProductBarcodeWorkflow({
  companyId,
  driverId,
  onChanged,
}: Params) {
  const {
    barcodeProduct,
    setBarcodeProduct,
    openBarcodeManager,
    closeBarcodeManager,
  } = useProductBarcodeState();

  return {
    openBarcodeManager,
    identityScope: {
      setBarcodeProduct,
    },
    managerProps: {
      product:
        barcodeProduct,
      companyId,
      driverId,
      onClose:
        closeBarcodeManager,
      onChanged,
    },
  };
}
