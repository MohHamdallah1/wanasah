import type {
  Dispatch,
  SetStateAction,
} from "react";
import {
  useMutation,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  completeDurableOperation,
  fileFingerprint,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseProductImportAccepted,
  type ProductImportState,
  type ProductTrackingMode,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  importFile: File | null;
  importLotControlMode: ProductTrackingMode | null;
  importExpiryControlMode: ProductTrackingMode | null;
  operationScope: (
    operation: string,
    target?: string | number,
  ) => string;
  authFetch: AuthFetch;
  setImportJobId: Dispatch<
    SetStateAction<string | null>
  >;
  setImportLotControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportStatus: Dispatch<
    SetStateAction<ProductImportState | null>
  >;
  setImportPollError: Dispatch<
    SetStateAction<string | null>
  >;
  importSessionKey: string | null;
  t: TFunction;
};

export function useImportProductUpload({
  importFile,
  importLotControlMode,
  importExpiryControlMode,
  operationScope,
  authFetch,
  setImportJobId,
  setImportLotControlMode,
  setImportExpiryControlMode,
  setImportStatus,
  setImportPollError,
  importSessionKey,
  t,
}: Params) {
  const importMutation =
    useMutation({
      mutationFn: async () => {
        if (!importFile) {
          throw new Error(
            t(
              "products.errors.fileRequired"
            )
          );
        }
        if (
          !importLotControlMode ||
          !importExpiryControlMode
        ) {
          throw new Error(
            t(
              "products.errors.trackingDefaultsRequired"
            )
          );
        }

        const fingerprint =
          await fileFingerprint(
            importFile
          );
        const scope =
          operationScope(
            "product-import",
            `${fingerprint}:${importLotControlMode}:${importExpiryControlMode}`
          );
        const requestId =
          await getOrCreateDurableRequestId(
            scope,
            {
              fingerprint,
              name: importFile.name,
              size: importFile.size,
              default_lot_control_mode:
                importLotControlMode,
              default_expiry_control_mode:
                importExpiryControlMode,
            }
          );

        const form =
          new FormData();
        form.append(
          "request_id",
          requestId
        );
        form.append(
          "default_lot_control_mode",
          importLotControlMode
        );
        form.append(
          "default_expiry_control_mode",
          importExpiryControlMode
        );
        form.append(
          "file",
          importFile
        );

        const result =
          parseProductImportAccepted(
            await authFetch(
              "/simple-products/imports",
              {
                method: "POST",
                body: form,
              }
            )
          );

        return {
          result,
          requestId,
          scope,
        };
      },
      onSuccess: ({
        result,
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setImportJobId(
          result.job_id
        );
        setImportLotControlMode(
          result.default_lot_control_mode
        );
        setImportExpiryControlMode(
          result.default_expiry_control_mode
        );
        setImportStatus(null);
        setImportPollError(null);
        if (
          importSessionKey
        ) {
          sessionStorage.setItem(
            importSessionKey,
            result.job_id
          );
        }
        toast.success(
          t(
            "products.importAccepted"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.importFailed"
            )
          )
        ),
    });


  const startImport =
    () =>
      importMutation.mutate();

  return {
    importMutation,
    startImport,
  };
}
