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
import { toast } from "sonner";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  readDurableCommand,
} from "@/lib/durableOperations";
import type {
  ProductTrackingDefaults,
  ProductTrackingMode,
  SimpleProduct,
} from "@/pages/products/contracts";
import { createProductTrackingActions } from "@/pages/products/tracking/createProductTrackingActions";
import { useProductTrackingEditState } from "@/pages/products/tracking/useProductTrackingEditState";
import {
  isProductTrackingCommandPayload,
  isProductTrackingDefaultsCommandPayload,
  useProductTrackingMutations,
} from "@/pages/products/tracking/useProductTrackingMutations";
import { useTrackingDefaultsState } from "@/pages/products/tracking/useTrackingDefaultsState";
import {
  productDurableScope,
} from "@/pages/products/productDurableScope";

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
    openTrackingDefaults:
      openTrackingDefaultsState,
    openTrackingEditor:
      openTrackingEditorState,
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

  const openTrackingDefaults =
    async () => {
      if (!defaults) {
        openTrackingDefaultsState();
        return;
      }
      try {
        const scope =
          productDurableScope(
            companyId,
            driverId,
            "product-tracking-defaults"
          );
        const pending =
          await readDurableCommand<unknown>(
            scope
          );
        if (pending) {
          if (
            !isProductTrackingDefaultsCommandPayload(
              pending.payload
            )
          ) {
            throw Object.assign(
              new Error(),
              {
                code:
                  "DURABLE_OPERATION_CORRUPT",
              }
            );
          }
          setTrackingDefaultsLot(
            pending.payload
              .lot_control_mode
          );
          setTrackingDefaultsExpiry(
            pending.payload
              .expiry_control_mode
          );
          setTrackingDefaultsOpen(
            true
          );
          return;
        }
      } catch (error) {
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingDefaultsSave"
            )
          )
        );
        return;
      }
      openTrackingDefaultsState();
    };

  const openTrackingEditor =
    async (
      product: SimpleProduct
    ) => {
      try {
        const scope =
          productDurableScope(
            companyId,
            driverId,
            "product-tracking",
            product.id
          );
        const pending =
          await readDurableCommand<unknown>(
            scope
          );
        if (pending) {
          if (
            !isProductTrackingCommandPayload(
              pending.payload
            )
          ) {
            throw Object.assign(
              new Error(),
              {
                code:
                  "DURABLE_OPERATION_CORRUPT",
              }
            );
          }
          setTrackingEdit({
            ...product,
            version:
              pending.payload
                .expected_version,
          });
          setTrackingEditLot(
            pending.payload
              .lot_control_mode
          );
          setTrackingEditExpiry(
            pending.payload
              .expiry_control_mode
          );
          return;
        }
      } catch (error) {
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingProductSave"
            )
          )
        );
        return;
      }
      openTrackingEditorState(
        product
      );
    };

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
