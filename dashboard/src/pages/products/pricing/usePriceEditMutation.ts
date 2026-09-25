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
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  completeDurableOperation,
  getOrCreateDurableRequestId,
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

          const body = {
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
          const requestId =
            await getOrCreateDurableRequestId(
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
                        requestId,
                      ...body,
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
            requestId,
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
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.priceFailed"
            )
          )
        ),
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
