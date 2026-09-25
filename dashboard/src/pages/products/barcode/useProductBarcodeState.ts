import {
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductBarcodeState() {
  const [
    barcodeProduct,
    setBarcodeProduct,
  ] = useState<SimpleProduct | null>(
    null
  );

  const openBarcodeManager = (
    product: SimpleProduct
  ) => setBarcodeProduct(product);

  const closeBarcodeManager = () =>
    setBarcodeProduct(null);

  return {
    barcodeProduct,
    setBarcodeProduct,
    openBarcodeManager,
    closeBarcodeManager,
  };
}
