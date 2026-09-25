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
  SimpleProduct,
} from "@/pages/products/contracts";
import {
  isProductPriceCommandPayload,
  usePriceEditMutation,
} from "@/pages/products/pricing/usePriceEditMutation";
import { usePriceEditState } from "@/pages/products/pricing/usePriceEditState";
import {
  productDurableScope,
} from "@/pages/products/productDurableScope";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  queryClient: QueryClient;
  t: TFunction;
  online: boolean;
};

export function usePriceEditWorkflow({
  companyId,
  driverId,
  authFetch,
  queryClient,
  t,
  online,
}: Params) {
  const {
    priceEdit,
    setPriceEdit,
    editPackagePrice,
    setEditPackagePrice,
    editUnitPrice,
    setEditUnitPrice,
    priceFieldError,
    setPriceFieldError,
    editPackagePriceRef,
    editUnitPriceRef,
    openPriceEditor:
      openPriceEditorState,
    cancelPriceEdit,
    updatePackagePrice,
    updateUnitPrice,
    editDerived,
  } = usePriceEditState();

  const openPriceEditor = async (
    product: SimpleProduct
  ) => {
    try {
      const scope =
        productDurableScope(
          companyId,
          driverId,
          "product-price",
          product.id
        );
      const pending =
        await readDurableCommand<unknown>(
          scope
        );
      if (pending) {
        if (
          !isProductPriceCommandPayload(
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
        setPriceFieldError(null);
        setPriceEdit(product);
        setEditPackagePrice(
          pending.payload
            .package_price ?? ""
        );
        setEditUnitPrice(
          pending.payload
            .unit_price ?? ""
        );
        return;
      }
    } catch (error) {
      toast.error(
        apiErrorMessage(
          error,
          t(
            "products.errors.priceFailed"
          )
        )
      );
      return;
    }

    openPriceEditorState(
      product
    );
  };

  const {
    priceMutation,
    submitPriceEdit,
    closePriceEdit,
  } = usePriceEditMutation({
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
  });

  return {
    openPriceEditor,
    identityScope: {
      setPriceEdit,
      setEditPackagePrice,
      setEditUnitPrice,
    },
    modalProps: {
      product: priceEdit,
      saving:
        priceMutation.isPending,
      online,
      packagePrice:
        editPackagePrice,
      unitPrice:
        editUnitPrice,
      fieldError:
        priceFieldError,
      independentPrices:
        Boolean(
          editDerived?.independent
        ),
      packagePriceRef:
        editPackagePriceRef,
      unitPriceRef:
        editUnitPriceRef,
      onClose:
        closePriceEdit,
      onCancel:
        cancelPriceEdit,
      onSubmit:
        submitPriceEdit,
      onPackagePriceChange:
        updatePackagePrice,
      onUnitPriceChange:
        updateUnitPrice,
    },
  };
}
