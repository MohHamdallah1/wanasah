import {
  useState,
} from "react";

import type {
  ProductTrackingMode,
} from "@/pages/products/contracts";

export function useTrackingDefaultsState() {
  const [
    trackingDefaultsOpen,
    setTrackingDefaultsOpen,
  ] = useState(false);
  const [
    trackingDefaultsLot,
    setTrackingDefaultsLot,
  ] = useState<ProductTrackingMode | null>(
    null
  );
  const [
    trackingDefaultsExpiry,
    setTrackingDefaultsExpiry,
    closeTrackingDefaults,
  ] = useState<ProductTrackingMode | null>(
    null
  );

  const closeTrackingDefaults = () =>
    setTrackingDefaultsOpen(false);

  return {
    trackingDefaultsOpen,
    setTrackingDefaultsOpen,
    trackingDefaultsLot,
    setTrackingDefaultsLot,
    trackingDefaultsExpiry,
    setTrackingDefaultsExpiry,
  };
}
