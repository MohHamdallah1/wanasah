import type {
  Dispatch,
  SetStateAction,
} from "react";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import type {
  ProductTrackingDefaults,
  ProductTrackingMode,
  SimpleProduct,
} from "@/pages/products/contracts";

type Params = {
  defaults: ProductTrackingDefaults | undefined;
  setTrackingDefaultsOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setTrackingDefaultsLot: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setTrackingDefaultsExpiry: Dispatch<
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
  t: TFunction;
};

export function createProductTrackingActions({
  defaults,
  setTrackingDefaultsOpen,
  setTrackingDefaultsLot,
  setTrackingDefaultsExpiry,
  setTrackingEdit,
  setTrackingEditLot,
  setTrackingEditExpiry,
  t,
}: Params) {
  const openTrackingDefaults =
    () => {
      if (!defaults) {
        toast.error(
          t(
            "products.errors.trackingDefaultsLoad"
          )
        );
        return;
      }
      setTrackingDefaultsLot(
        defaults.lot_control_mode
      );
      setTrackingDefaultsExpiry(
        defaults.expiry_control_mode
      );
      setTrackingDefaultsOpen(true);
    };

  const openTrackingEditor = (
    product: SimpleProduct
  ) => {
    setTrackingEdit(product);
    setTrackingEditLot(
      product.lot_control_mode
    );
    setTrackingEditExpiry(
      product.expiry_control_mode
    );
  };

  return {
    openTrackingDefaults,
    openTrackingEditor,
  };
}
