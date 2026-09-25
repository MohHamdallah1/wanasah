import {
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductRenameState() {
  const [
    renameProduct,
    setRenameProduct,
  ] = useState<SimpleProduct | null>(
    null
  );

  const openRenameProduct = (
    product: SimpleProduct
  ) => setRenameProduct(product);

  const closeRenameProduct = () =>
    setRenameProduct(null);

  return {
    renameProduct,
    setRenameProduct,
    openRenameProduct,
    closeRenameProduct,
  };
}
