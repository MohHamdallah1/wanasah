import {
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductLifecycleState() {
  const [
    lifecycleProduct,
    setLifecycleProduct,
  ] = useState<SimpleProduct | null>(
    null
  );

  const openLifecycleManager = (
    product: SimpleProduct
  ) => setLifecycleProduct(product);

  const closeLifecycleManager = () =>
    setLifecycleProduct(null);

  return {
    lifecycleProduct,
    setLifecycleProduct,
    openLifecycleManager,
    closeLifecycleManager,
  };
}
