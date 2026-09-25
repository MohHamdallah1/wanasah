import type {
  Dispatch,
  RefObject,
  SetStateAction,
} from "react";
import {
  useMutation,
  type QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseSimpleProductCreateResponse,
  type PackageUom,
  type ProductFamily,
} from "@/pages/products/contracts";
import {
  resolveCreateProductFamilyIntent,
} from "@/pages/products/create/createProductFamilyIntent";
import type {
  CreateFieldError,
  ProductDraft,
} from "@/pages/products/create/types";
import {
  emptyDraft,
} from "@/pages/products/create/useCreateProductState";
import {
  productDurableScope,
} from "@/pages/products/productDurableScope";

type MutationResult<T> = {
  result: T;
  requestId: string;
  scope: string;
};

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  draft: ProductDraft;
  familyOptions: ProductFamily[];
  packageUoms: PackageUom[];
  authFetch: AuthFetch;
  draftStorageKey: string | null;
  companyId: number | null;
  driverId: number | null;
  setDraft: Dispatch<
    SetStateAction<ProductDraft>
  >;
  setCreateFieldError: Dispatch<
    SetStateAction<
      CreateFieldError | null
    >
  >;
  setCreateTrackingExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  setCreateAdvancedExpanded: Dispatch<
    SetStateAction<boolean>
  >;
  setCreateOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setCursor: Dispatch<
    SetStateAction<string | null>
  >;
  setHistory: Dispatch<
    SetStateAction<
      Array<string | null>
    >
  >;
  queryClient: QueryClient;
  t: TFunction;
  createNameRef: RefObject<
    HTMLInputElement | null
  >;
  createFamilyRef: RefObject<
    HTMLInputElement | null
  >;
  createUnitsRef: RefObject<
    HTMLInputElement | null
  >;
  createPackagePriceRef: RefObject<
    HTMLInputElement | null
  >;
  createUnitPriceRef: RefObject<
    HTMLInputElement | null
  >;
};

export function useCreateProductMutation({
  draft,
  familyOptions,
  packageUoms,
  authFetch,
  draftStorageKey,
  companyId,
  driverId,
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
  createFamilyRef,
  createUnitsRef,
  createPackagePriceRef,
  createUnitPriceRef,
}: Params) {
  const createMutation =
    useMutation({
      mutationFn:
        async (): Promise<
          MutationResult<
            ReturnType<
              typeof parseSimpleProductCreateResponse
            >
          >
        > => {
          if (
            !draft.name.trim()
          ) {
            throw new Error(
              t(
                "products.errors.nameRequired"
              )
            );
          }

          const familyIntent =
            resolveCreateProductFamilyIntent(
              draft,
              familyOptions,
            );
          if (!familyIntent.ok) {
            throw new Error(
              t(
                familyIntent.error ===
                "EXISTING_FAMILY_REQUIRED"
                  ? "products.errors.existingFamilyRequired"
                  : "products.errors.newFamilyRequired"
              )
            );
          }

          const units =
            draft.has_package
              ? Number(
                  draft.units_per_package
                )
              : 1;

          if (
            draft.has_package &&
            (!Number.isInteger(
              units
            ) ||
              units < 2)
          ) {
            throw new Error(
              t(
                "products.errors.packageUnitsInvalid"
              )
            );
          }

          if (
            !draft.package_price.trim() &&
            !draft.unit_price.trim()
          ) {
            throw new Error(
              draft.has_package
                ? t(
                    "products.errors.priceRequired"
                  )
                : t(
                    "products.errors.unitPriceRequired"
                  )
            );
          }
          if (
            !draft.lot_control_mode ||
            !draft.expiry_control_mode
          ) {
            throw new Error(
              t(
                "products.errors.trackingDefaultsRequired"
              )
            );
          }

          if (
            draft.has_package &&
            !packageUoms.some(
              (item) =>
                item.code ===
                draft.package_uom_code
            )
          ) {
            throw new Error(
              "PACKAGE_UOMS_RESPONSE_INVALID"
            );
          }

          const body = {
            name:
              draft.name.trim(),
            family_id:
              familyIntent.family_id,
            family_name:
              familyIntent.family_name,
            package_uom_code:
              draft.has_package
                ? draft.package_uom_code
                : null,
            units_per_package:
              units,
            package_price:
              draft.has_package &&
              draft.package_price.trim()
                ? draft.package_price.trim()
                : null,
            unit_price:
              draft.unit_price.trim() ||
              null,
            unit_barcode:
              draft.unit_barcode.trim() ||
              null,
            package_barcode:
              draft.has_package &&
              draft.package_barcode.trim()
                ? draft.package_barcode.trim()
                : null,
            lot_control_mode:
              draft.lot_control_mode,
            expiry_control_mode:
              draft.expiry_control_mode,
          };

          const scope =
            productDurableScope(
              companyId,
              driverId,
              "product-create"
            );
          const requestId =
            await getOrCreateDurableRequestId(
              scope,
              body
            );
          const result =
            parseSimpleProductCreateResponse(
              await authFetch(
                "/simple-products",
                {
                  method: "POST",
                  body: JSON.stringify(
                    {
                      request_id:
                        requestId,
                      ...body,
                    }
                  ),
                }
              )
            );

          return {
            result,
            requestId,
            scope,
          };
        },
      onSuccess:
        async ({
          requestId,
          scope,
        }) => {
          completeDurableOperation(
            scope,
            requestId
          );
          if (
            draftStorageKey
          ) {
            sessionStorage.removeItem(
              draftStorageKey
            );
          }
          setDraft(
            emptyDraft
          );
          setCreateFieldError(null);
          setCreateTrackingExpanded(
            false
          );
          setCreateAdvancedExpanded(
            false
          );
          setCreateOpen(false);
          setCursor(null);
          setHistory([]);
          toast.success(
            t(
              "products.created"
            )
          );
          await Promise.all([
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-products",
                ],
              }
            ),
            queryClient.invalidateQueries(
              {
                queryKey: [
                  "simple-product-families",
                ],
              }
            ),
          ]);
        },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.createFailed"
            )
          )
        ),
    });

  const submitCreate = () => {
    if (!draft.name.trim()) {
      setCreateFieldError({
        field: "name",
        message: t(
          "products.errors.nameRequired"
        ),
      });
      window.requestAnimationFrame(
        () => createNameRef.current?.focus()
      );
      return;
    }

    const familyIntent =
      resolveCreateProductFamilyIntent(
        draft,
        familyOptions,
      );
    if (!familyIntent.ok) {
      setCreateFieldError({
        field: "family",
        message: t(
          familyIntent.error ===
          "EXISTING_FAMILY_REQUIRED"
            ? "products.errors.existingFamilyRequired"
            : "products.errors.newFamilyRequired"
        ),
      });
      window.requestAnimationFrame(
        () => createFamilyRef.current?.focus()
      );
      return;
    }

    const units =
      draft.has_package
        ? Number(
            draft.units_per_package
          )
        : 1;
    if (
      draft.has_package &&
      (!Number.isInteger(units) ||
        units < 2)
    ) {
      setCreateFieldError({
        field: "units",
        message: t(
          "products.errors.packageUnitsInvalid"
        ),
      });
      window.requestAnimationFrame(
        () => createUnitsRef.current?.focus()
      );
      return;
    }

    if (
      !draft.package_price.trim() &&
      !draft.unit_price.trim()
    ) {
      const packageField =
        draft.has_package;
      setCreateFieldError({
        field: packageField
          ? "packagePrice"
          : "unitPrice",
        message: packageField
          ? t(
              "products.errors.priceRequired"
            )
          : t(
              "products.errors.unitPriceRequired"
            ),
      });
      window.requestAnimationFrame(
        () =>
          (
            packageField
              ? createPackagePriceRef
              : createUnitPriceRef
          ).current?.focus()
      );
      return;
    }

    setCreateFieldError(null);
    createMutation.mutate();
  };

  const cancelCreate =
    () => {
      setCreateOpen(false);
      setCreateFieldError(null);
      setCreateTrackingExpanded(
        false
      );
      setCreateAdvancedExpanded(
        false
      );
      setDraft(emptyDraft);
      if (
        draftStorageKey
      ) {
        sessionStorage.removeItem(
          draftStorageKey
        );
      }
      if (
        companyId &&
        driverId
      ) {
        abandonDurableOperation(
          productDurableScope(
            companyId,
            driverId,
            "product-create"
          )
        );
      }
    };


  return {
    createMutation,
    submitCreate,
    cancelCreate,
  };
}
