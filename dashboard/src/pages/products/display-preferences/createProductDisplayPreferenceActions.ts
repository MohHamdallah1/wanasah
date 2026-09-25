import type {
  Dispatch,
  SetStateAction,
} from "react";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import {
  writeProductDisplayPreferences,
  type ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import type {
  ProductSortDirection,
  ProductSortField,
} from "@/pages/products/list/types";

type Params = {
  companyId: number | null;
  driverId: number | null;
  setDisplayPreferences: Dispatch<
    SetStateAction<ProductDisplayPreferences>
  >;
  setSortBy: Dispatch<
    SetStateAction<ProductSortField>
  >;
  setSortDir: Dispatch<
    SetStateAction<ProductSortDirection>
  >;
  resetProductPagination: () => void;
  setDisplayPreferencesOpen: Dispatch<
    SetStateAction<boolean>
  >;
  t: TFunction;
};

export function createProductDisplayPreferenceActions({
  companyId,
  driverId,
  setDisplayPreferences,
  setSortBy,
  setSortDir,
  resetProductPagination,
  setDisplayPreferencesOpen,
  t,
}: Params) {
  const saveDisplayPreferences = (
    next: ProductDisplayPreferences
  ) => {
    if (
      companyId === null ||
      driverId === null ||
      !writeProductDisplayPreferences(
        companyId,
        driverId,
        next
      )
    ) {
      toast.error(
        t(
          "products.displayPreferences.saveFailed"
        )
      );
      return;
    }

    setDisplayPreferences(next);
    setSortBy(
      next.defaultSort.field
    );
    setSortDir(
      next.defaultSort.direction
    );
    resetProductPagination();
    setDisplayPreferencesOpen(false);
    toast.success(
      t(
        "products.displayPreferences.saved"
      )
    );
  };


  return {
    saveDisplayPreferences,
  };
}
