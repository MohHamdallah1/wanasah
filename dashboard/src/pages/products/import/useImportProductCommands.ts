import {
  useEffect,
  useRef,
  type Dispatch,
  type SetStateAction,
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
  setMapping: Dispatch<
    SetStateAction<Record<string, string>>
  >;
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
  setMapping,
  authFetch,
  setImportPollError,
  setImportStatus,
  setImportPollKey,
  t,
}: Params) {
  // Async command replies belong to the job that initiated them, not a
  // replacement job selected while the network request was in flight.
  const currentJobRef = useRef(importJobId);
  useEffect(() => {
    currentJobRef.current = importJobId;
  }, [importJobId]);

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
        if (
          !result ||
          result.job_id !== currentJobRef.current
        ) {
          return;
        }
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

  const cancelImportMutation =
    useMutation({
      mutationFn: async () => {
        if (!importJobId) {
          throw new Error("PRODUCT_IMPORT_COMMAND_JOB_MISSING");
        }
        const result =
          parseProductImportCommandResponse(
            await authFetch(
              `/simple-products/imports/${importJobId}/cancel`,
              { method: "POST" },
            ),
          );
        if (result.job_id !== importJobId) {
          throw new Error("PRODUCT_IMPORT_COMMAND_SCOPE_MISMATCH");
        }
        return result;
      },
      onSuccess: (result) => {
        if (
          !result ||
          result.job_id !== currentJobRef.current
        ) {
          return;
        }
        setImportPollError(null);
        setImportStatus(
          (current) =>
            current
              ? { ...current, status: result.status }
              : current,
        );
        // Restart the canonical HTTP/WS watch on the original job; never
        // infer cancellation completion from the client-side button click.
        setImportPollKey((current) => current + 1);
        toast.message(t("products.importCancelRequested"));
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t("products.errors.cancelImportFailed"),
          ),
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
        if (
          !result ||
          result.job_id !== currentJobRef.current
        ) {
          return;
        }
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

  const updateMapping = (
    field: string,
    value: string,
  ) =>
    setMapping(
      (current) => ({
        ...current,
        [field]: value,
      })
    );

  const submitMapping =
    () =>
      mappingMutation.mutate();

  const retryImport =
    () =>
      retryImportMutation.mutate();

  const cancelImport = () => {
    if (
      !importJobId ||
      cancelImportMutation.isPending ||
      !window.confirm(t("products.importCancelConfirm"))
    ) {
      return;
    }
    cancelImportMutation.mutate();
  };

  return {
    mappingMutation,
    retryImportMutation,
    cancelImportMutation,
    updateMapping,
    submitMapping,
    retryImport,
    cancelImport,
  };
}
