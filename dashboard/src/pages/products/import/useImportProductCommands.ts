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
  parseProductImportCommandResponse,
  type ProductImportState,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  importJobId: string | null;
  mapping: Record<string, string>;
  authFetch: AuthFetch;
  setImportPollError: Dispatch<
    SetStateAction<string | null>
  >;
  setImportStatus: Dispatch<
    SetStateAction<ProductImportState | null>
  >;
  setImportPollKey: Dispatch<
    SetStateAction<number>
  >;
  t: TFunction;
};

export function useImportProductCommands({
  importJobId,
  mapping,
  authFetch,
  setImportPollError,
  setImportStatus,
  setImportPollKey,
  t,
}: Params) {
  const mappingMutation =
    useMutation({
      mutationFn: async () => {
        if (!importJobId) {
          return;
        }
        const result =
          parseProductImportCommandResponse(
            await authFetch(
              `/simple-products/imports/${importJobId}/mapping`,
              {
                method: "PUT",
                body: JSON.stringify({
                  mapping,
                }),
              }
            )
          );
        if (
          result.job_id !==
          importJobId
        ) {
          throw new Error(
            "PRODUCT_IMPORT_COMMAND_SCOPE_MISMATCH"
          );
        }
        return result;
      },
      onSuccess: (result) => {
        setImportPollError(null);
        setImportStatus(
          (current) =>
            current
              ? {
                  ...current,
                  status:
                    result?.status ??
                    current.status,
                }
              : current
        );
        setImportPollKey(
          (current) =>
            current + 1
        );
        toast.success(
          t(
            "products.mappingAccepted"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.mappingFailed"
            )
          )
        ),
    });

  const retryImportMutation =
    useMutation({
      mutationFn: async () => {
        if (!importJobId) {
          return;
        }
        const result =
          parseProductImportCommandResponse(
            await authFetch(
              `/simple-products/imports/${importJobId}/retry`,
              {
                method: "POST",
              }
            )
          );
        if (
          result.job_id !==
          importJobId
        ) {
          throw new Error(
            "PRODUCT_IMPORT_COMMAND_SCOPE_MISMATCH"
          );
        }
        return result;
      },
      onSuccess: (result) => {
        setImportPollError(null);
        setImportStatus(
          (current) =>
            current
              ? {
                  ...current,
                  status:
                    result?.status ??
                    current.status,
                }
              : current
        );
        setImportPollKey(
          (current) =>
            current + 1
        );
        toast.success(
          t(
            "products.retryQueued"
          )
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.retryFailed"
            )
          )
        ),
    });


  return {
    mappingMutation,
    retryImportMutation,
  };
}
