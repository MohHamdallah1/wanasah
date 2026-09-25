import {
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";

import type {
  ProductTrackingDefaults,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
} from "@/pages/products/create/types";

type Params = {
  createOpen: boolean;
  defaults:
    | ProductTrackingDefaults
    | undefined;
  setDraft: Dispatch<
    SetStateAction<ProductDraft>
  >;
};

export function useCreateTrackingDefaultsSync({
  createOpen,
  defaults,
  setDraft,
}: Params) {
  useEffect(() => {
    if (
      !createOpen ||
      !defaults
    ) {
      return;
    }
    setDraft((current) => ({
      ...current,
      lot_control_mode:
        current.lot_control_mode ??
        defaults.lot_control_mode,
      expiry_control_mode:
        current.expiry_control_mode ??
        defaults.expiry_control_mode,
    }));
  }, [
    createOpen,
    defaults,
    setDraft,
  ]);
}
