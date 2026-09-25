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
} from "@/pages/products/contracts";
import type {
  CreateFieldError,
  ProductDraft,
} from "@/pages/products/create/types";

type Params = {
  createFieldError: CreateFieldError | null;
  trackingDefaults:
    | ProductTrackingDefaults
    | undefined;
  setDraft: Dispatch<
    SetStateAction<ProductDraft>
  >;
  setCreateFieldError: Dispatch<
    SetStateAction<
      CreateFieldError | null
    >
  >;
  setCreateAdvancedExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  setCreateTrackingExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  t: TFunction;
};

export function createProductDraftActions({
  createFieldError,
  trackingDefaults,
  setDraft,
  setCreateFieldError,
  setCreateAdvancedExpanded,
  setCreateTrackingExpanded,
  t,
}: Params) {
  const updateName = (
    value: string
  ) => {
    setDraft(
      (current) => ({
        ...current,
        name: value,
      })
    );
    if (
      createFieldError?.field ===
      "name"
    ) {
      setCreateFieldError(null);
    }
  };

  const updateFamily = (
    value: string
  ) =>
    setDraft(
      (current) => ({
        ...current,
        family: value,
      })
    );

  const updateHasPackage = (
    checked: boolean
  ) =>
    setDraft(
      (current) => ({
        ...current,
        has_package: checked,
        units_per_package:
          checked
            ? current.units_per_package ===
              "1"
              ? "50"
              : current.units_per_package
            : "1",
        package_price:
          checked
            ? current.package_price
            : "",
        package_barcode:
          checked
            ? current.package_barcode
            : "",
      })
    );

  const updatePackageUom = (
    value: string
  ) =>
    setDraft(
      (current) => ({
        ...current,
        package_uom_code: value,
      })
    );

  const updateUnitsPerPackage = (
    value: string
  ) => {
    setDraft(
      (current) => ({
        ...current,
        units_per_package: value,
      })
    );
    if (
      createFieldError?.field ===
      "units"
    ) {
      setCreateFieldError(null);
    }
  };

  const updatePackagePrice = (
    value: string
  ) => {
    setDraft(
      (current) => ({
        ...current,
        package_price: value,
      })
    );
    if (
      createFieldError?.field ===
      "packagePrice"
    ) {
      setCreateFieldError(null);
    }
  };

  const updateUnitPrice = (
    value: string
  ) => {
    setDraft(
      (current) => ({
        ...current,
        unit_price: value,
      })
    );
    if (
      createFieldError?.field ===
      "unitPrice"
    ) {
      setCreateFieldError(null);
    }
  };

  const toggleAdvanced = () =>
    setCreateAdvancedExpanded(
      (current) => !current
    );

  const expandTracking = () =>
    setCreateTrackingExpanded(
      true
    );

  const updateLotControlMode = (
    value: ProductTrackingMode
  ) =>
    setDraft(
      (current) => ({
        ...current,
        lot_control_mode: value,
      })
    );

  const updateExpiryControlMode = (
    value: ProductTrackingMode
  ) =>
    setDraft(
      (current) => ({
        ...current,
        expiry_control_mode: value,
      })
    );

  const resetTracking = () => {
    if (!trackingDefaults) {
      return;
    }
    setDraft(
      (current) => ({
        ...current,
        lot_control_mode:
          trackingDefaults
            .lot_control_mode,
        expiry_control_mode:
          trackingDefaults
            .expiry_control_mode,
      })
    );
    setCreateTrackingExpanded(
      false
    );
  };

  const updateUnitBarcode = (
    value: string
  ) =>
    setDraft(
      (current) => ({
        ...current,
        unit_barcode: value,
      })
    );

  const copyBarcode = () => {
    setDraft(
      (current) => ({
        ...current,
        package_barcode:
          current.unit_barcode,
      })
    );
    toast.success(
      t(
        "products.copiedBarcode"
      )
    );
  };

  const updatePackageBarcode = (
    value: string
  ) =>
    setDraft(
      (current) => ({
        ...current,
        package_barcode: value,
      })
    );

  return {
    updateName,
    updateFamily,
    updateHasPackage,
    updatePackageUom,
    updateUnitsPerPackage,
    updatePackagePrice,
    updateUnitPrice,
    toggleAdvanced,
    expandTracking,
    updateLotControlMode,
    updateExpiryControlMode,
    resetTracking,
    updateUnitBarcode,
    copyBarcode,
    updatePackageBarcode,
  };
}
