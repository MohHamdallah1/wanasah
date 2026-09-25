import type {
  Dispatch,
  SetStateAction,
} from "react";
import {
  useMutation,
  type QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  completeDurableOperation,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseProductTrackingDefaults,
  parseProductTrackingMutation,
  type ProductTrackingMode,
  type SimpleProduct,
} from "@/pages/products/contracts";
import {
  productDurableScope,
} from "@/pages/products/productDurableScope";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  trackingDefaultsLot: ProductTrackingMode | null;
  trackingDefaultsExpiry: ProductTrackingMode | null;
  trackingEdit: SimpleProduct | null;
  trackingEditLot: ProductTrackingMode | null;
  trackingEditExpiry: ProductTrackingMode | null;
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  setTrackingDefaultsOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setTrackingDefaultsLot: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setTrackingDefaultsExpiry: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  importJobId: string | null;
  setImportLotControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setTrackingEdit: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setTrackingEditLot: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setTrackingEditExpiry: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  queryClient: QueryClient;
  t: TFunction;
};

export function useProductTrackingMutations({
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
  importJobId,
  setImportLotControlMode,
  setImportExpiryControlMode,
  setTrackingEdit,
  setTrackingEditLot,
  setTrackingEditExpiry,
  queryClient,
  t,
}: Params) {
  const trackingDefaultsMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !trackingDefaultsLot ||
          !trackingDefaultsExpiry
        ) {
          throw new Error(
            t(
              "products.errors.trackingDefaultsRequired"
            )
          );
        }

        const body = {
          lot_control_mode:
            trackingDefaultsLot,
          expiry_control_mode:
            trackingDefaultsExpiry,
        };
        const scope =
          productDurableScope(
            companyId,
            driverId,
            "product-tracking-defaults"
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            body
          );
        const data =
          parseProductTrackingDefaults(
            await authFetch(
              "/simple-products/tracking/defaults",
              {
                method: "PUT",
                body: JSON.stringify({
                  request_id:
                    requestId,
                  ...body,
                }),
              }
            )
          );
        return {
          data,
          requestId,
          scope,
        };
      },
      onSuccess: async ({
        data,
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setTrackingDefaultsOpen(
          false
        );
        setTrackingDefaultsLot(
          data.lot_control_mode
        );
        setTrackingDefaultsExpiry(
          data.expiry_control_mode
        );
        if (
          !importJobId
        ) {
          setImportLotControlMode(
            data.lot_control_mode
          );
          setImportExpiryControlMode(
            data.expiry_control_mode
          );
        }
        toast.success(
          t(
            "products.trackingSettings.saved"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-product-tracking-defaults",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingDefaultsSave"
            )
          )
        ),
    });

  const trackingMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !trackingEdit ||
          !trackingEditLot ||
          !trackingEditExpiry
        ) {
          throw new Error(
            t(
              "products.errors.trackingProductRequired"
            )
          );
        }

        const body = {
          expected_version:
            trackingEdit.version,
          lot_control_mode:
            trackingEditLot,
          expiry_control_mode:
            trackingEditExpiry,
        };
        const scope =
          productDurableScope(
            companyId,
            driverId,
            "product-tracking",
            trackingEdit.id
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            body
          );
        const data =
          parseProductTrackingMutation(
            await authFetch(
              `/simple-products/tracking/variants/${trackingEdit.id}`,
              {
                method: "PATCH",
                body: JSON.stringify({
                  request_id:
                    requestId,
                  ...body,
                }),
              }
            )
          );
        return {
          data,
          requestId,
          scope,
        };
      },
      onSuccess: async ({
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setTrackingEdit(null);
        setTrackingEditLot(null);
        setTrackingEditExpiry(null);
        toast.success(
          t(
            "products.trackingEditor.saved"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-products",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingProductSave"
            )
          )
        ),
    });


  return {
    trackingDefaultsMutation,
    trackingMutation,
  };
}
