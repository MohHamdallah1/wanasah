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
import type {
  SimpleBarcodeTarget,
} from "@/pages/products/barcode/barcodeUiTypes";
import {
  parseProductBarcodeMutation,
  type ProductBarcodeRecord,
  type SimpleProduct,
} from "@/pages/products/contracts";

type BarcodeReplaceBody = {
  uom_id: number;
  barcode: string;
  expected_current_id: number | null;
  expected_current_version: number | null;
};

type Params = {
  product: SimpleProduct;
  items: ProductBarcodeRecord[];
  companyId: number | null;
  driverId: number | null;
  canMutate: boolean;
  refreshBarcodes: () => void;
  onChanged: () => void | Promise<void>;
};

export function usePrimaryBarcodeReplacement({
  product,
  items,
  companyId,
  driverId,
  canMutate,
  refreshBarcodes,
  onChanged,
}: Params) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const [
    replacing,
    setReplacing,
  ] = useState(false);

  const replaceScope = useCallback(
    (uomId: number) =>
      companyId !== null &&
      driverId !== null
        ? durableScope(
            companyId,
            driverId,
            "catalog-barcode-replace-primary-v1",
            `${product.id}:${uomId}`,
          )
        : null,
    [
      companyId,
      driverId,
      product.id,
    ],
  );

  const replacePrimaryBarcode =
    useCallback(
      async (
        replacementTarget:
          SimpleBarcodeTarget,
        nextBarcode: string,
      ): Promise<boolean> => {
        const uomId =
          replacementTarget ===
          "package"
            ? product.package_uom_id
            : product.base_uom_id;

        if (
          !canMutate ||
          uomId === null ||
          (
            replacementTarget ===
              "package" &&
            product.package_uses_base_barcode
          )
        ) {
          return false;
        }

        const current =
          items.find(
            (item) =>
              item.uom.id ===
                uomId &&
              item.is_active &&
              item.is_primary,
          ) ?? null;

        const freshBody:
          BarcodeReplaceBody = {
            uom_id: uomId,
            barcode:
              nextBarcode.trim(),
            expected_current_id:
              current?.id ?? null,
            expected_current_version:
              current?.version ??
              null,
          };

        if (!freshBody.barcode) {
          return false;
        }

        const scope =
          replaceScope(uomId);
        if (!scope) {
          return false;
        }

        setReplacing(true);
        try {
          const command =
            await getOrCreateDurableCommand(
              scope,
              freshBody,
            );

          parseProductBarcodeMutation(
            await authFetch(
              "/catalog/variants/" +
                product.id +
                "/barcodes/replace-primary",
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
            scope,
            command.requestId,
          );
          toast.success(
            t(
              "products.barcodeManager.replaced",
            ),
          );
          refreshBarcodes();
          await onChanged();
          return true;
        } catch (error) {
          const errorCode =
            apiErrorCode(error);
          if (
            errorCode !==
              "DURABLE_OPERATION_PENDING" &&
            errorCode !==
              "DURABLE_OPERATION_CORRUPT" &&
            !isAmbiguousRequestError(
              error,
            )
          ) {
            abandonDurableOperation(
              scope,
            );
          }
          toast.error(
            apiErrorMessage(
              error,
              t(
                errorCode ===
                  "DURABLE_OPERATION_PENDING"
                  ? "products.barcodeManager.replacePending"
                  : "products.barcodeManager.saveFailed",
              ),
            ),
          );
          return false;
        } finally {
          setReplacing(false);
        }
      },
      [
        authFetch,
        canMutate,
        items,
        onChanged,
        product,
        refreshBarcodes,
        replaceScope,
        t,
      ],
    );

  return {
    replacing,
    replacePrimaryBarcode,
  };
}
