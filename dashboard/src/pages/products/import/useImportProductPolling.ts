import type {
  Dispatch,
  SetStateAction,
} from "react";
import {
  useEffect,
} from "react";
import type {
  QueryClient,
} from "@tanstack/react-query";
import type {
  TFunction,
} from "i18next";
import { toast } from "sonner";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  parseProductImportState,
  type ProductImportState,
  type ProductTrackingMode,
} from "@/pages/products/contracts";

const terminalImportStatuses =
  new Set([
    "COMPLETED",
    "VALIDATION_FAILED",
    "FAILED",
    "NEEDS_MAPPING",
  ]);

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  importJobId: string | null;
  importPollKey: number;
  authFetch: AuthFetch;
  queryClient: QueryClient;
  t: TFunction;
  isOnline: boolean;
  setImportPollError: Dispatch<
    SetStateAction<string | null>
  >;
  setImportStatus: Dispatch<
    SetStateAction<ProductImportState | null>
  >;
  setImportLotControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setImportExpiryControlMode: Dispatch<
    SetStateAction<ProductTrackingMode | null>
  >;
  setMapping: Dispatch<
    SetStateAction<Record<string, string>>
  >;
};

export function useImportProductPolling({
  importJobId,
  importPollKey,
  authFetch,
  queryClient,
  t,
  isOnline,
  setImportPollError,
  setImportStatus,
  setImportLotControlMode,
  setImportExpiryControlMode,
  setMapping,
}: Params) {
  useEffect(() => {
    if (!importJobId) {
      return;
    }

    let disposed = false;
    let timer:
      | number
      | undefined;

    const poll = async () => {
      if (!navigator.onLine) {
        timer =
          window.setTimeout(
            poll,
            3000
          );
        return;
      }

      try {
        const status =
          parseProductImportState(
            await authFetch(
              `/simple-products/imports/${importJobId}`
            )
          );

        if (disposed) {
          return;
        }

        setImportPollError(null);
        setImportStatus(
          status
        );
        setImportLotControlMode(
          status.default_lot_control_mode
        );
        setImportExpiryControlMode(
          status.default_expiry_control_mode
        );

        if (
          status.status ===
          "NEEDS_MAPPING"
        ) {
          setMapping(
            Object.keys(
              status.column_mapping ||
                {}
            ).length
              ? status.column_mapping
              : status.suggested_mapping
          );
        }

        if (
          status.status ===
          "COMPLETED"
        ) {
          toast.success(
            t(
              "products.importCompleted",
              {
                count:
                  status.processed_rows,
              }
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
          return;
        }

        if (
          !terminalImportStatuses.has(
            status.status
          )
        ) {
          timer =
            window.setTimeout(
              poll,
              1500
            );
        }
      } catch (error) {
        if (!disposed) {
          setImportPollError(
            apiErrorMessage(
              error,
              t(
                "products.errors.importStatusLoad"
              )
            )
          );
          timer =
            window.setTimeout(
              poll,
              3000
            );
        }
      }
    };

    void poll();

    return () => {
      disposed = true;
      if (
        timer !== undefined
      ) {
        window.clearTimeout(
          timer
        );
      }
    };
  }, [
    authFetch,
    importJobId,
    importPollKey,
    queryClient,
    t,
    isOnline,
  ]);


}
