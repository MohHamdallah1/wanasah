import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";

import { usePriceEditMutation } from "@/pages/products/pricing/usePriceEditMutation";
import { usePriceEditState } from "@/pages/products/pricing/usePriceEditState";

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
    openPriceEditor,
    cancelPriceEdit,
    updatePackagePrice,
    updateUnitPrice,
    editDerived,
  } = usePriceEditState();

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
