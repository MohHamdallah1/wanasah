import {
  useState,
} from "react";

import type {
  ProductTrackingMode,
  SimpleProduct,
} from "@/pages/products/contracts";

export function useProductTrackingEditState() {
  const [
    trackingEdit,
    setTrackingEdit,
  ] = useState<SimpleProduct | null>(
    null
  );
  const [
    trackingEditLot,
    setTrackingEditLot,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    trackingEditExpiry,
    setTrackingEditExpiry,
  ] = useState<ProductTrackingMode | null>(
    null
  );

  const closeTrackingEditor = () => {
    setTrackingEdit(null);
    setTrackingEditLot(null);
    setTrackingEditExpiry(null);
  };

  return {
    trackingEdit,
    setTrackingEdit,
    trackingEditLot,
    setTrackingEditLot,
    trackingEditExpiry,
    setTrackingEditExpiry,
    closeTrackingEditor,
  };
}
