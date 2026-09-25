import {
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductDetailState() {
  const [
    detailProduct,
    setDetailProduct,
  ] = useState<SimpleProduct | null>(
    null
  );

  const openProductDetails = (
    product: SimpleProduct
  ) => setDetailProduct(product);

  const closeProductDetails = () =>
    setDetailProduct(null);

  return {
    detailProduct,
    setDetailProduct,
    openProductDetails,
    closeProductDetails,
  };
}
