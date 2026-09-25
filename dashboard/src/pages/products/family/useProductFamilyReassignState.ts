import {
  useState,
} from "react";

import type {
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductFamilyReassignState() {
  const [
    familyReassignProduct,
    setFamilyReassignProduct,
  ] = useState<SimpleProduct | null>(
    null
  );

  const openFamilyReassign = (
    product: SimpleProduct
  ) =>
    setFamilyReassignProduct(
      product
    );

  const closeFamilyReassign = () =>
    setFamilyReassignProduct(null);

  return {
    familyReassignProduct,
    setFamilyReassignProduct,
    openFamilyReassign,
    closeFamilyReassign,
  };
}
