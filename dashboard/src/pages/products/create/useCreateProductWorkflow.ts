import type {
  Dispatch,
  SetStateAction,
} from "react";
import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";

import type {
  ProductTrackingDefaults,
} from "@/pages/products/contracts";
import { createProductDraftActions } from "@/pages/products/create/createProductDraftActions";
import { deriveCreateProductViewState } from "@/pages/products/create/deriveCreateProductViewState";
import { productDraftStorageKey } from "@/pages/products/create/productDraftStorageKey";
import { useCreateFamilyOptionParams } from "@/pages/products/create/useCreateFamilyOptionParams";
import { useCreateFamilyOptionsQuery } from "@/pages/products/create/useCreateFamilyOptionsQuery";
import { useCreateFamilyOptionSearchDebounce } from "@/pages/products/create/useCreateFamilyOptionSearchDebounce";
import { useCreateFamilyOptionSearchState } from "@/pages/products/create/useCreateFamilyOptionSearchState";
import { useCreateProductDraftPersistence } from "@/pages/products/create/useCreateProductDraftPersistence";
import { useCreateProductMutation } from "@/pages/products/create/useCreateProductMutation";
import { useCreateProductState } from "@/pages/products/create/useCreateProductState";
import { useCreateTrackingDefaultsSync } from "@/pages/products/create/useCreateTrackingDefaultsSync";
import { usePackageUomsQuery } from "@/pages/products/create/usePackageUomsQuery";

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
  trackingDefaults:
    | ProductTrackingDefaults
    | undefined;
  trackingDefaultsError: boolean;
  retryTrackingDefaults: () => void;
  setCursor: Dispatch<
    SetStateAction<string | null>
  >;
  setHistory: Dispatch<
    SetStateAction<
      Array<string | null>
    >
  >;
};

export function useCreateProductWorkflow({
  companyId,
  driverId,
  authFetch,
  queryClient,
  t,
  online,
  trackingDefaults,
  trackingDefaultsError,
  retryTrackingDefaults,
  setCursor,
  setHistory,
}: Params) {
  const {
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
  } = useCreateProductState();

  const [
    familyOptionSearch,
    setFamilyOptionSearch,
  ] =
    useCreateFamilyOptionSearchState();

  const draftStorageKey =
    productDraftStorageKey(
      companyId,
      driverId
    );

  useCreateFamilyOptionSearchDebounce({
    createOpen,
    family: draft.family,
    setFamilyOptionSearch,
  });

  useCreateProductDraftPersistence({
    draftStorageKey,
    draft,
    setDraft,
    restoredDraftKey,
    t,
  });

  const familyOptionParams =
    useCreateFamilyOptionParams(
      familyOptionSearch
    );

  const familyOptionsQuery =
    useCreateFamilyOptionsQuery({
      companyId,
      createOpen,
      familyOptionSearch,
      familyOptionParams,
      authFetch,
    });

  const packageUomsQuery =
    usePackageUomsQuery({
      authFetch,
    });

  useCreateTrackingDefaultsSync({
    createOpen,
    defaults:
      trackingDefaults,
    setDraft,
  });

  const familyOptions =
    familyOptionsQuery.data
      ?.items ?? [];
  const packageUoms =
    packageUomsQuery.data
      ?.items ?? [];

  const {
    draftDerived,
    trackingUsesCompanyDefaults,
  } = deriveCreateProductViewState({
    draft,
    defaults:
      trackingDefaults,
  });

  const {
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
  } = createProductDraftActions({
    createFieldError,
    trackingDefaults,
    setDraft,
    setCreateFieldError,
    setCreateAdvancedExpanded,
    setCreateTrackingExpanded,
    t,
  });

  const {
    createMutation,
    submitCreate,
    cancelCreate,
  } = useCreateProductMutation({
    draft,
    familyOptions,
    packageUoms,
    companyId,
    driverId,
    authFetch,
    draftStorageKey,
    setDraft,
    setCreateFieldError,
    setCreateTrackingExpanded,
    setCreateAdvancedExpanded,
    setCreateOpen,
    setCursor,
    setHistory,
    queryClient,
    t,
    createNameRef,
    createUnitsRef,
    createPackagePriceRef,
    createUnitPriceRef,
  });

  return {
    openCreateProduct,
    identityScope: {
      setCreateTrackingExpanded,
      setCreateAdvancedExpanded,
      setFamilyOptionSearch,
    },
    modalProps: {
      open: createOpen,
      saving:
        createMutation.isPending,
      online,
      draft,
      createFieldError,
      familyOptions,
      familyOptionsError:
        familyOptionsQuery.isError,
      packageUoms,
      packageUomsLoading:
        packageUomsQuery.isLoading,
      packageUomsError:
        packageUomsQuery.isError,
      trackingDefaultsError,
      trackingUsesCompanyDefaults,
      draftDerived,
      createAdvancedExpanded,
      createTrackingExpanded,
      createNameRef,
      createUnitsRef,
      createPackagePriceRef,
      createUnitPriceRef,
      onCancel:
        cancelCreate,
      onSubmit:
        submitCreate,
      onNameChange:
        updateName,
      onFamilyChange:
        updateFamily,
      onRetryFamilyOptions: () =>
        void familyOptionsQuery.refetch(),
      onRetryTrackingDefaults:
        retryTrackingDefaults,
      onHasPackageChange:
        updateHasPackage,
      onRetryPackageUoms: () =>
        void packageUomsQuery.refetch(),
      onPackageUomChange:
        updatePackageUom,
      onUnitsPerPackageChange:
        updateUnitsPerPackage,
      onPackagePriceChange:
        updatePackagePrice,
      onUnitPriceChange:
        updateUnitPrice,
      onToggleAdvanced:
        toggleAdvanced,
      onExpandTracking:
        expandTracking,
      onLotControlModeChange:
        updateLotControlMode,
      onExpiryControlModeChange:
        updateExpiryControlMode,
      onResetTracking:
        resetTracking,
      onUnitBarcodeChange:
        updateUnitBarcode,
      onCopyBarcode:
        copyBarcode,
      onPackageBarcodeChange:
        updatePackageBarcode,
    },
  };
}
