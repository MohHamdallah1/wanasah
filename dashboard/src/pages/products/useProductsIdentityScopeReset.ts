import {
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  readProductDisplayPreferences,
  type ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import type {
  ProductTrackingMode,
  SimpleProduct,
} from "@/pages/products/contracts";
import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type ListScope = {
  setCursor: Dispatch<
    SetStateAction<string | null>
  >;
  setHistory: Dispatch<
    SetStateAction<
      Array<string | null>
    >
  >;
  setFiltersOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setFamilyFilterSearchInput: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterSearch: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterId: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterName: Dispatch<
    SetStateAction<string>
  >;
  setLifecycleFilter: Dispatch<
    SetStateAction<ProductLifecycleFilter>
  >;
  setTrackingTypeFilter: Dispatch<
    SetStateAction<ProductTrackingTypeFilter>
  >;
  setCompatibilityFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setBarcodeFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setPriceFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setLotFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setExpiryFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setSortBy: Dispatch<
    SetStateAction<ProductSortField>
  >;
  setSortDir: Dispatch<
    SetStateAction<ProductSortDirection>
  >;
};

type DisplayScope = {
  setDisplayPreferences: Dispatch<
    SetStateAction<
      ProductDisplayPreferences
    >
  >;
};

type TargetScope = {
  setDetailProduct: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setRenameProduct: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setBarcodeProduct: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setFamilyReassignProduct: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
};

type PricingScope = {
  setPriceEdit: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setEditPackagePrice: Dispatch<
    SetStateAction<string>
  >;
  setEditUnitPrice: Dispatch<
    SetStateAction<string>
  >;
};

type ImportScope = {
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
  setImportTrackingExpanded: Dispatch<
    SetStateAction<boolean>
  >;
};

type CreateScope = {
  setCreateTrackingExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  setCreateAdvancedExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  setFamilyOptionSearch: Dispatch<
    SetStateAction<string>
  >;
};

type TrackingScope = {
  setTrackingDefaultsOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setTrackingDefaultsLot: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
  setTrackingDefaultsExpiry: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
  setTrackingEdit: Dispatch<
    SetStateAction<SimpleProduct | null>
  >;
  setTrackingEditLot: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
  setTrackingEditExpiry: Dispatch<
    SetStateAction<
      ProductTrackingMode | null
    >
  >;
};

type Params = {
  companyId: number | null;
  driverId: number | null;
  list: ListScope;
  display: DisplayScope;
  targets: TargetScope;
  pricing: PricingScope;
  importScope: ImportScope;
  create: CreateScope;
  tracking: TrackingScope;
};

export function useProductsIdentityScopeReset({
  companyId,
  driverId,
  list,
  display,
  targets,
  pricing,
  importScope,
  create,
  tracking,
}: Params) {
  const {
    setCursor,
    setHistory,
    setFiltersOpen,
    setFamilyFilterSearchInput,
    setFamilyFilterSearch,
    setFamilyFilterId,
    setFamilyFilterName,
    setLifecycleFilter,
    setTrackingTypeFilter,
    setCompatibilityFilter,
    setBarcodeFilter,
    setPriceFilter,
    setLotFilter,
    setExpiryFilter,
    setSortBy,
    setSortDir,
  } = list;
  const {
    setDisplayPreferences,
  } = display;
  const {
    setDetailProduct,
    setRenameProduct,
    setBarcodeProduct,
    setFamilyReassignProduct,
  } = targets;
  const {
    setPriceEdit,
    setEditPackagePrice,
    setEditUnitPrice,
  } = pricing;
  const {
    setImportLotControlMode,
    setImportExpiryControlMode,
    setImportTrackingExpanded,
  } = importScope;
  const {
    setCreateTrackingExpanded,
    setCreateAdvancedExpanded,
    setFamilyOptionSearch,
  } = create;
  const {
    setTrackingDefaultsOpen,
    setTrackingDefaultsLot,
    setTrackingDefaultsExpiry,
    setTrackingEdit,
    setTrackingEditLot,
    setTrackingEditExpiry,
  } = tracking;

  useEffect(() => {
    const nextDisplayPreferences =
      companyId !== null &&
      driverId !== null
        ? readProductDisplayPreferences(
            companyId,
            driverId
          )
        : readProductDisplayPreferences(
            Number.NaN,
            Number.NaN
          );

    setDisplayPreferences(
      nextDisplayPreferences
    );
    setCursor(null);
    setHistory([]);
    setFiltersOpen(false);
    setFamilyFilterSearchInput("");
    setFamilyFilterSearch("");
    setFamilyFilterId("");
    setFamilyFilterName("");
    setLifecycleFilter("");
    setTrackingTypeFilter("");
    setCompatibilityFilter("");
    setBarcodeFilter("");
    setPriceFilter("");
    setLotFilter("");
    setExpiryFilter("");
    setSortBy(
      nextDisplayPreferences.defaultSort
        .field
    );
    setSortDir(
      nextDisplayPreferences.defaultSort
        .direction
    );
    setDetailProduct(null);
    setRenameProduct(null);
    setBarcodeProduct(null);
    setFamilyReassignProduct(null);
    setPriceEdit(null);
    setEditPackagePrice("");
    setEditUnitPrice("");
    setImportLotControlMode(null);
    setImportExpiryControlMode(null);
    setImportTrackingExpanded(false);
    setCreateTrackingExpanded(false);
    setCreateAdvancedExpanded(false);
    setTrackingDefaultsOpen(false);
    setTrackingDefaultsLot(null);
    setTrackingDefaultsExpiry(null);
    setTrackingEdit(null);
    setTrackingEditLot(null);
    setTrackingEditExpiry(null);
    setFamilyOptionSearch("");
  }, [
    companyId,
    driverId,
    setBarcodeFilter,
    setBarcodeProduct,
    setCompatibilityFilter,
    setCreateAdvancedExpanded,
    setCreateTrackingExpanded,
    setCursor,
    setDetailProduct,
    setDisplayPreferences,
    setEditPackagePrice,
    setEditUnitPrice,
    setExpiryFilter,
    setFamilyFilterId,
    setFamilyFilterName,
    setFamilyFilterSearch,
    setFamilyFilterSearchInput,
    setFamilyOptionSearch,
    setFamilyReassignProduct,
    setFiltersOpen,
    setHistory,
    setImportExpiryControlMode,
    setImportLotControlMode,
    setImportTrackingExpanded,
    setLifecycleFilter,
    setLotFilter,
    setPriceEdit,
    setPriceFilter,
    setRenameProduct,
    setSortBy,
    setSortDir,
    setTrackingDefaultsExpiry,
    setTrackingDefaultsLot,
    setTrackingDefaultsOpen,
    setTrackingEdit,
    setTrackingEditExpiry,
    setTrackingEditLot,
    setTrackingTypeFilter,
  ]);
}
