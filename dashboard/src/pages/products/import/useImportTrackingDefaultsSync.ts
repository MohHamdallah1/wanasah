import {
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";

import type {
  ProductTrackingDefaults,
  ProductTrackingMode,
} from "@/pages/products/contracts";

type Params = {
  importOpen: boolean;
  importJobId: string | null;
  defaults:
    | ProductTrackingDefaults
    | undefined;
  setImportLotControlMode: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
};

export function useImportTrackingDefaultsSync({
  importOpen,
  importJobId,
  defaults,
  setImportLotControlMode,
  setImportExpiryControlMode,
}: Params) {
  useEffect(() => {
    if (
      !importOpen ||
      importJobId ||
      !defaults
    ) {
      return;
    }
    setImportLotControlMode(
      (current) =>
        current ??
        defaults.lot_control_mode
    );
    setImportExpiryControlMode(
      (current) =>
        current ??
        defaults.expiry_control_mode
    );
  }, [
    importOpen,
    importJobId,
    defaults,
    setImportExpiryControlMode,
    setImportLotControlMode,
  ]);
}
