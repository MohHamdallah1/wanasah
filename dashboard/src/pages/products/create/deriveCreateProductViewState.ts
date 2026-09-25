import {
  deriveExactMoneyPair,
} from "@/lib/exactMoney";
import type {
  ProductTrackingDefaults,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
} from "@/pages/products/create/types";

type Params = {
  draft: ProductDraft;
  defaults:
    | ProductTrackingDefaults
    | undefined;
};

export function deriveCreateProductViewState({
  draft,
  defaults,
}: Params) {
  const draftDerived =
    deriveExactMoneyPair(
      draft.has_package,
      draft.units_per_package,
      draft.package_price,
      draft.unit_price
    );

  const trackingUsesCompanyDefaults =
    Boolean(
      defaults &&
        draft.lot_control_mode &&
        draft.expiry_control_mode &&
        draft.lot_control_mode ===
          defaults.lot_control_mode &&
        draft.expiry_control_mode ===
          defaults.expiry_control_mode
    );

  return {
    draftDerived,
    trackingUsesCompanyDefaults,
  };
}
