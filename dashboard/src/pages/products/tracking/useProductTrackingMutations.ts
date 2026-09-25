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
  apiErrorCode,
  apiErrorMessage,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  getOrCreateDurableCommand,
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

export type ProductTrackingDefaultsCommandPayload = {
  lot_control_mode: ProductTrackingMode;
  expiry_control_mode: ProductTrackingMode;
};

export type ProductTrackingCommandPayload =
  ProductTrackingDefaultsCommandPayload & {
    expected_version: number;
  };

const isTrackingMode = (
  value: unknown,
): value is ProductTrackingMode =>
  value === "NONE" ||
  value === "OPTIONAL" ||
  value === "REQUIRED";

export const isProductTrackingDefaultsCommandPayload = (
  value: unknown,
): value is ProductTrackingDefaultsCommandPayload => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    isTrackingMode(
      row.lot_control_mode
    ) &&
    isTrackingMode(
      row.expiry_control_mode
    )
  );
};

export const isProductTrackingCommandPayload = (
  value: unknown,
): value is ProductTrackingCommandPayload => {
  if (
    !isProductTrackingDefaultsCommandPayload(
      value
    )
  ) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.expected_version ===
      "number" &&
    Number.isSafeInteger(
      row.expected_version
    ) &&
    row.expected_version > 0
  );
};

const keepDurableCommand = (
  error: unknown,
  uncertainCodes: string[],
) => {
  const code =
    apiErrorCode(error);
  return (
    code ===
      "DURABLE_OPERATION_PENDING" ||
    code ===
      "DURABLE_OPERATION_CORRUPT" ||
    (
      code !== undefined &&
      uncertainCodes.includes(code)
    ) ||
    isAmbiguousRequestError(error)
  );
};

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

        const body:
          ProductTrackingDefaultsCommandPayload = {
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
        const command =
          await getOrCreateDurableCommand(
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
                    command.requestId,
                  ...command.payload,
                }),
              }
            )
          );
        return {
          data,
          requestId:
            command.requestId,
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
      onError: (error) => {
        if (
          companyId !== null &&
          driverId !== null &&
          !keepDurableCommand(
            error,
            [
              "PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID",
            ]
          )
        ) {
          abandonDurableOperation(
            productDurableScope(
              companyId,
              driverId,
              "product-tracking-defaults"
            )
          );
        }
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingDefaultsSave"
            )
          )
        );
      },
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

        const body:
          ProductTrackingCommandPayload = {
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
        const command =
          await getOrCreateDurableCommand(
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
                    command.requestId,
                  ...command.payload,
                }),
              }
            )
          );
        if (
          data.product_variant_id !==
          trackingEdit.id
        ) {
          throw new Error(
            "PRODUCT_TRACKING_SCOPE_MISMATCH"
          );
        }
        return {
          data,
          requestId:
            command.requestId,
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
      onError: (error) => {
        if (
          trackingEdit &&
          companyId !== null &&
          driverId !== null &&
          !keepDurableCommand(
            error,
            [
              "PRODUCT_TRACKING_MUTATION_RESPONSE_INVALID",
              "PRODUCT_TRACKING_SCOPE_MISMATCH",
            ]
          )
        ) {
          abandonDurableOperation(
            productDurableScope(
              companyId,
              driverId,
              "product-tracking",
              trackingEdit.id
            )
          );
        }
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.trackingProductSave"
            )
          )
        );
      },
    });


  return {
    trackingDefaultsMutation,
    trackingMutation,
  };
}
