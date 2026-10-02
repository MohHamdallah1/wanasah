import {
  useCallback,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  apiErrorCode,
  apiErrorMessage,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";
import {
  parseProductBarcodeMutation,
  type SimpleProduct,
} from "@/pages/products/contracts";

type PackageBarcodeBody = {
  package_uom_id: number;
  barcode: string;
  expected_variant_version: number;
};

type Params = {
  product: SimpleProduct | null;
  companyId: number | null;
  driverId: number | null;
  canMutate: boolean;
  refreshBarcodes: () => void;
  onChanged: () => void | Promise<void>;
};

export function useIndependentPackageBarcode({
  product,
  companyId,
  driverId,
  canMutate,
  refreshBarcodes,
  onChanged,
}: Params) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const [
    assigning,
    setAssigning,
  ] = useState(false);

  const productId =
    product?.id ?? null;

  const scope = useCallback(
    () =>
      companyId !== null &&
      driverId !== null &&
      productId !== null
        ? durableScope(
            companyId,
            driverId,
            "catalog-package-barcode-independent-v1",
            productId,
          )
        : null,
    [
      companyId,
      driverId,
      productId,
    ],
  );

  const assignIndependent =
    useCallback(
      async (
        barcode: string,
      ): Promise<boolean> => {
        if (
          !product ||
          !canMutate ||
          !product.package_uses_base_barcode ||
          product.package_uom_id ===
            null
        ) {
          return false;
        }

        const clean =
          barcode.trim();
        if (!clean) {
          return false;
        }

        const durable =
          scope();
        if (!durable) {
          return false;
        }

        const body:
          PackageBarcodeBody = {
            package_uom_id:
              product.package_uom_id,
            barcode: clean,
            expected_variant_version:
              product.version,
          };

        setAssigning(true);
        try {
          const command =
            await getOrCreateDurableCommand(
              durable,
              body,
            );

          parseProductBarcodeMutation(
            await authFetch(
              "/catalog/variants/" +
                product.id +
                "/barcodes/package-independent",
              {
                method: "POST",
                body: JSON.stringify({
                  request_id:
                    command.requestId,
                  ...command.payload,
                }),
              },
            ),
          );

          completeDurableOperation(
            durable,
            command.requestId,
          );
          toast.success(
            t(
              "products.barcodeManager.packageIndependentSuccess",
            ),
          );
          refreshBarcodes();
          await onChanged();
          return true;
        } catch (error) {
          const code =
            apiErrorCode(error);
          if (
            code !==
              "DURABLE_OPERATION_PENDING" &&
            code !==
              "DURABLE_OPERATION_CORRUPT" &&
            !isAmbiguousRequestError(
              error,
            )
          ) {
            abandonDurableOperation(
              durable,
            );
          }

          toast.error(
            apiErrorMessage(
              error,
              t(
                code ===
                  "DURABLE_OPERATION_PENDING"
                  ? "products.barcodeManager.packageIndependentPending"
                  : "products.barcodeManager.saveFailed",
              ),
            ),
          );
          return false;
        } finally {
          setAssigning(false);
        }
      },
      [
        authFetch,
        canMutate,
        onChanged,
        product,
        refreshBarcodes,
        scope,
        t,
      ],
    );

  return {
    assigning,
    assignIndependent,
  };
}
