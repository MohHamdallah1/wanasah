import {
  useRef,
  useState,
} from "react";

import type {
  CreateFieldError,
  ProductDraft,
} from "@/pages/products/create/types";

export const emptyDraft: ProductDraft = {
  name: "",
  family: "",
  has_package: true,
  package_uom_code: "CARTON",
  units_per_package: "50",
  package_price: "",
  unit_price: "",
  unit_barcode: "",
  package_barcode: "",
  lot_control_mode: null,
  expiry_control_mode: null,
};

export function useCreateProductState() {
  const [
    createOpen,
    setCreateOpen,
  ] = useState(false);
  const [
    createTrackingExpanded,
    setCreateTrackingExpanded,
  ] = useState(false);
  const [
    createAdvancedExpanded,
    setCreateAdvancedExpanded,
  ] = useState(false);
  const [
    draft,
    setDraft,
  ] =
    useState<ProductDraft>(
      emptyDraft
    );
  const restoredDraftKey =
    useRef<string | null>(
      null
    );
  const [
    createFieldError,
    setCreateFieldError,
  ] = useState<CreateFieldError | null>(
    null
  );
  const createNameRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createUnitsRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createPackagePriceRef =
    useRef<HTMLInputElement | null>(
      null
    );
  const createUnitPriceRef =
    useRef<HTMLInputElement | null>(
      null
    );

  const openCreateProduct = () => {
    setCreateTrackingExpanded(
      false
    );
    setCreateAdvancedExpanded(
      false
    );
    setCreateOpen(true);
  };

  return {
    createOpen,
    setCreateOpen,
    openCreateProduct,
    createTrackingExpanded,
    setCreateTrackingExpanded,
    createAdvancedExpanded,
    setCreateAdvancedExpanded,
    draft,
    setDraft,
    restoredDraftKey,
    createFieldError,
    setCreateFieldError,
    createNameRef,
    createUnitsRef,
    createPackagePriceRef,
    createUnitPriceRef,
  };
}
