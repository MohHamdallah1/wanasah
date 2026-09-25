import type {
  Dispatch,
  SetStateAction,
} from "react";
import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";

import type {
  ProductTrackingDefaults,
  ProductTrackingMode,
} from "@/pages/products/contracts";
import { createProductTrackingActions } from "@/pages/products/tracking/createProductTrackingActions";
import { useProductTrackingEditState } from "@/pages/products/tracking/useProductTrackingEditState";
import { useProductTrackingMutations } from "@/pages/products/tracking/useProductTrackingMutations";
import { useTrackingDefaultsState } from "@/pages/products/tracking/useTrackingDefaultsState";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type ImportTrackingBridge = {
  importJobId: string | null;
  setImportLotControlMode: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
};

type Params = {
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  queryClient: QueryClient;
  t: TFunction;
  online: boolean;
  defaults:
    | ProductTrackingDefaults
    | undefined;
  importTrackingBridge:
    ImportTrackingBridge;
};

export function useProductTrackingWorkflow({
  companyId,
  driverId,
  authFetch,
  queryClient,
  t,
  online,
  defaults,
  importTrackingBridge,
}: Params) {
  const {
    trackingDefaultsOpen,
    setTrackingDefaultsOpen,
    trackingDefaultsLot,
    setTrackingDefaultsLot,
    trackingDefaultsExpiry,
    setTrackingDefaultsExpiry,
    closeTrackingDefaults,
  } = useTrackingDefaultsState();

  const {
    trackingEdit,
    setTrackingEdit,
    trackingEditLot,
    setTrackingEditLot,
    trackingEditExpiry,
    setTrackingEditExpiry,
    closeTrackingEditor,
  } = useProductTrackingEditState();

  const {
    openTrackingDefaults,
    openTrackingEditor,
  } = createProductTrackingActions({
    defaults,
    setTrackingDefaultsOpen,
    setTrackingDefaultsLot,
    setTrackingDefaultsExpiry,
    setTrackingEdit,
    setTrackingEditLot,
    setTrackingEditExpiry,
    t,
  });

  const {
    trackingDefaultsMutation,
    trackingMutation,
  } = useProductTrackingMutations({
    trackingDefaultsLot,
    trackingDefaultsExpiry,
    trackingEdit,
    trackingEditLot,
    trackingEditExpiry,
    companyId,
    driverId,
    authFetch,
    setTrackingDefaultsOpen,
    setTrackingDefaultsLot,
    setTrackingDefaultsExpiry,
    ...importTrackingBridge,
    setTrackingEdit,
    setTrackingEditLot,
    setTrackingEditExpiry,
    queryClient,
    t,
  });

  return {
    openTrackingDefaults,
    openTrackingEditor,
    identityScope: {
      setTrackingDefaultsOpen,
      setTrackingDefaultsLot,
      setTrackingDefaultsExpiry,
      setTrackingEdit,
      setTrackingEditLot,
      setTrackingEditExpiry,
    },
    overlaysProps: {
      settings:
        trackingDefaultsOpen &&
        trackingDefaultsLot &&
        trackingDefaultsExpiry &&
        defaults
          ? {
              open:
                trackingDefaultsOpen,
              lotControlMode:
                trackingDefaultsLot,
              expiryControlMode:
                trackingDefaultsExpiry,
              lotControlSource:
                defaults
                  .lot_control_source,
              expiryControlSource:
                defaults
                  .expiry_control_source,
              saving:
                trackingDefaultsMutation
                  .isPending,
              online,
              onLotControlModeChange:
                setTrackingDefaultsLot,
              onExpiryControlModeChange:
                setTrackingDefaultsExpiry,
              onClose:
                closeTrackingDefaults,
              onSave: () =>
                trackingDefaultsMutation.mutate(),
            }
          : null,
      editor:
        trackingEdit &&
        trackingEditLot &&
        trackingEditExpiry
          ? {
              product:
                trackingEdit,
              lotControlMode:
                trackingEditLot,
              expiryControlMode:
                trackingEditExpiry,
              saving:
                trackingMutation.isPending,
              online,
              onLotControlModeChange:
                setTrackingEditLot,
              onExpiryControlModeChange:
                setTrackingEditExpiry,
              onClose:
                closeTrackingEditor,
              onSave: () =>
                trackingMutation.mutate(),
            }
          : null,
    },
  };
}
