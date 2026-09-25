import type {
  Dispatch,
  RefObject,
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
  parseSimpleProductPriceMutationResponse,
  type SimpleProduct,
} from "@/pages/products/contracts";
import type {
  PriceFieldError,
} from "@/pages/products/pricing/types";
import {
  productDurableScope,
} from "@/pages/products/productDurableScope";

type MutationResult<T> = {
  result: T;
  requestId: string;
  scope: string;
};

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

export type ProductPriceCommandPayload = {
  package_price: string | null;
  unit_price: string | null;
};

export const isProductPriceCommandPayload = (
  value: unknown,
): value is ProductPriceCommandPayload => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<string, unknown>;
  const validPrice = (price: unknown) =>
    price === null ||
    (typeof price === "string" &&
      price.trim().length > 0);
  return (
    validPrice(row.package_price) &&
    validPrice(row.unit_price) &&
    (row.package_price !== null ||
      row.unit_price !== null)
  );
};

type Params = {
  priceEdit: SimpleProduct | null;
  editPackagePrice: string;
  editUnitPrice: string;
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  setPriceEdit: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setPriceFieldError: Dispatch<
    SetStateAction<PriceFieldError | null>
  >;
  queryClient: QueryClient;
  t: TFunction;
  editPackagePriceRef: RefObject<HTMLInputElement | null>;
  editUnitPriceRef: RefObject<HTMLInputElement | null>;
};

export function usePriceEditMutation({
  priceEdit,
  editPackagePrice,
  editUnitPrice,
  companyId,
  driverId,
  authFetch,
  setPriceEdit,
  setPriceFieldError,
  queryClient,
  t,
  editPackagePriceRef,
  editUnitPriceRef,
}: Params) {
  const priceMutation =
    useMutation({
      mutationFn:
        async (): Promise<
          | MutationResult<
              ReturnType<
                typeof parseSimpleProductPriceMutationResponse
              >
            >
          | undefined
        > => {
          if (!priceEdit) {
            return undefined;
          }
          if (
            !editPackagePrice.trim() &&
            !editUnitPrice.trim()
          ) {
            throw new Error(
              priceEdit.package_uom_code
                ? t(
                    "products.errors.priceRequired"
                  )
                : t(
                    "products.errors.unitPriceRequired"
                  )
            );
          }

          const body:
            ProductPriceCommandPayload = {
              package_price:
                priceEdit.package_uom_code &&
                editPackagePrice.trim()
                  ? editPackagePrice.trim()
                  : null,
              unit_price:
                editUnitPrice.trim() ||
                null,
            };
          const scope =
            productDurableScope(
              companyId,
              driverId,
              "product-price",
              priceEdit.id
            );
          const command =
            await getOrCreateDurableCommand(
              scope,
              body
            );
          const result =
            parseSimpleProductPriceMutationResponse(
              await authFetch(
                `/simple-products/${priceEdit.id}/price`,
                {
                  method: "PATCH",
                  body: JSON.stringify(
                    {
                      request_id:
                        command.requestId,
                      ...command.payload,
                    }
                  ),
                }
              )
            );
          if (
            result.product_variant_id !==
            priceEdit.id
          ) {
            throw new Error(
              "SIMPLE_PRODUCT_PRICE_SCOPE_MISMATCH"
            );
          }
          return {
            result,
            requestId:
              command.requestId,
            scope,
          };
        },
      onSuccess: async (
        completed
      ) => {
        if (completed) {
          completeDurableOperation(
            completed.scope,
            completed.requestId
          );
        }
        setPriceEdit(null);
        setPriceFieldError(null);
        toast.success(
          t(
            "products.priceUpdated"
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
        const code =
          apiErrorCode(error);
        const uncertainResponse =
          code ===
            "SIMPLE_PRODUCT_PRICE_RESPONSE_INVALID" ||
          code ===
            "SIMPLE_PRODUCT_PRICE_SCOPE_MISMATCH";
        if (
          priceEdit &&
          companyId !== null &&
          driverId !== null &&
          code !==
            "DURABLE_OPERATION_PENDING" &&
          code !==
            "DURABLE_OPERATION_CORRUPT" &&
          !uncertainResponse &&
          !isAmbiguousRequestError(
            error
          )
        ) {
          abandonDurableOperation(
            productDurableScope(
              companyId,
              driverId,
              "product-price",
              priceEdit.id
            )
          );
        }
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.priceFailed"
            )
          )
        );
      },
    });

  const submitPriceEdit = () => {
    if (!priceEdit) {
      return;
    }
    if (
      !editPackagePrice.trim() &&
      !editUnitPrice.trim()
    ) {
      const packageField =
        Boolean(
          priceEdit.package_uom_code
        );
      setPriceFieldError({
        field: packageField
          ? "packagePrice"
          : "unitPrice",
        message: packageField
          ? t(
              "products.errors.priceRequired"
            )
          : t(
              "products.errors.unitPriceRequired"
            ),
      });
      window.requestAnimationFrame(
        () =>
          (
            packageField
              ? editPackagePriceRef
              : editUnitPriceRef
          ).current?.focus()
      );
      return;
    }
    setPriceFieldError(null);
    priceMutation.mutate();
  };

  const closePriceEdit =
    () => {
      if (
        !priceMutation.isPending
      ) {
        setPriceEdit(
          null
        );
        setPriceFieldError(null);
      }
    };

  return {
    priceMutation,
    submitPriceEdit,
    closePriceEdit,
  };
}
