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

const settledImportStatuses =
  new Set([
    "COMPLETED",
    "COMPLETED_WITH_ERRORS",
    "VALIDATION_FAILED",
    "FAILED",
    "CANCELLED",
    "NEEDS_MAPPING",
  ]);

export function productImportBackoffDelay(
  attempt: number,
  jitter: number,
  baseMs = 1500,
): number {
  const safeAttempt =
    Math.max(
      0,
      Math.min(
        Math.floor(attempt),
        8,
      ),
    );
  const boundedJitter =
    Math.max(
      0,
      Math.min(
        jitter,
        1,
      ),
    );
  return (
    Math.min(
      baseMs *
        2 ** safeAttempt,
      30_000,
    ) +
    Math.floor(
      boundedJitter * 500,
    )
  );
}

export function isProductImportProgressEvent(
  raw: unknown,
  jobId: string,
): boolean {
  if (
    typeof raw !== "object" ||
    raw === null
  ) {
    return false;
  }
  const event = raw as {
    event?: unknown;
    job_id?: unknown;
  };
  return (
    event.event ===
      "PRODUCT_IMPORT_PROGRESS" &&
    event.job_id === jobId
  );
}

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  enabled: boolean;
  importJobId: string | null;
  importPollKey: number;
  setImportPollKey: Dispatch<
    SetStateAction<number>
  >;
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
  enabled,
  importJobId,
  importPollKey,
  setImportPollKey,
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
    if (
      !enabled ||
      !importJobId
    ) {
      return;
    }

    let disposed = false;
    let settled = false;
    let realtimeOpen = false;
    let completionHandled =
      false;
    let completionToastId: string | number | undefined;
    let fallbackAttempt = 0;
    let reconnectAttempt = 0;
    let websocket:
      | WebSocket
      | undefined;
    let fallbackTimer:
      | number
      | undefined;
    let reconnectTimer:
      | number
      | undefined;
    let refreshTimer:
      | number
      | undefined;

    const clearTimer = (
      timer:
        | number
        | undefined,
    ) => {
      if (
        timer !== undefined
      ) {
        window.clearTimeout(
          timer,
        );
      }
    };

    const clearTransportTimers =
      () => {
        clearTimer(
          fallbackTimer,
        );
        clearTimer(
          reconnectTimer,
        );
        clearTimer(
          refreshTimer,
        );
        fallbackTimer =
          undefined;
        reconnectTimer =
          undefined;
        refreshTimer =
          undefined;
      };

    const closeRealtime = () => {
      const current =
        websocket;
      websocket = undefined;
      realtimeOpen = false;
      if (
        current &&
        (
          current.readyState ===
            WebSocket.OPEN ||
          current.readyState ===
            WebSocket.CONNECTING
        )
      ) {
        current.close();
      }
    };

    const finishTransport =
      () => {
        settled = true;
        clearTransportTimers();
        closeRealtime();
      };

    const applyStatus = async (
      status:
        ProductImportState,
    ) => {
      // Late HTTP responses must never replace an already-terminal snapshot.
      if (disposed || settled) {
        return true;
      }

      setImportPollError(null);
      setImportStatus(
        status,
      );
      setImportLotControlMode(
        status.default_lot_control_mode,
      );
      setImportExpiryControlMode(
        status.default_expiry_control_mode,
      );

      if (
        status.status ===
        "NEEDS_MAPPING"
      ) {
        setMapping(
          Object.keys(
            status.column_mapping ||
              {},
          ).length
            ? status.column_mapping
            : status.suggested_mapping,
        );
      }

      const isSettled =
        settledImportStatuses.has(
          status.status,
        );
      // Commit transport closure synchronously before awaited React Query
      // invalidations; any earlier HTTP response is now ignored.
      if (isSettled) {
        finishTransport();
      }

      if (
        (
          status.status ===
            "COMPLETED" ||
          status.status ===
            "COMPLETED_WITH_ERRORS"
        ) &&
        !completionHandled
      ) {
        completionHandled =
          true;
        if (
          status.status ===
          "COMPLETED"
        ) {
          completionToastId = toast.success(
            t(
              "products.importCompleted",
              {
                count:
                  status.imported_rows,
              },
            ),
          );
        } else {
          completionToastId = toast.warning(
            t(
              "products.importCompletedWithErrors",
              {
                imported:
                  status.imported_rows,
                errors:
                  status.invalid_rows +
                  status.import_failed_rows,
              },
            ),
          );
        }
        await Promise.all([
          queryClient.invalidateQueries(
            {
              queryKey: [
                "simple-products",
              ],
            },
          ),
          queryClient.invalidateQueries(
            {
              queryKey: [
                "simple-product-families",
              ],
            },
          ),
        ]);
      }

      return isSettled;
    };

    const refreshStatus =
      async (): Promise<boolean> => {
        if (
          disposed ||
          settled
        ) {
          return true;
        }
        if (
          !isOnline ||
          !navigator.onLine
        ) {
          return false;
        }

        try {
          const status =
            parseProductImportState(
              await authFetch(
                `/simple-products/imports/${importJobId}`,
              ),
            );
          return await applyStatus(
            status,
          );
        } catch (error) {
          // An obsolete request may fail after another request has already
          // completed the import. Do not resurrect the error banner.
          if (!disposed && !settled) {
            setImportPollError(
              apiErrorMessage(
                error,
                t(
                  "products.errors.importStatusLoad",
                ),
              ),
            );
          }
          return settled;
        }
      };

    const scheduleFallback =
      () => {
        // Retain a pending HTTP fallback while repeated WebSocket failures
        // schedule reconnects. Otherwise each failure postpones the fallback.
        if (fallbackTimer !== undefined) {
          return;
        }

        if (
          disposed ||
          settled ||
          realtimeOpen ||
          document.visibilityState !==
            "visible"
        ) {
          return;
        }

        const delay =
          productImportBackoffDelay(
            fallbackAttempt,
            Math.random(),
          );
        fallbackAttempt += 1;
        fallbackTimer =
          window.setTimeout(
            () => {
              fallbackTimer =
                undefined;
              void refreshStatus()
                .finally(
                  () => {
                    if (
                      !disposed &&
                      !settled &&
                      !realtimeOpen
                    ) {
                      scheduleFallback();
                    }
                  },
                );
            },
            delay,
          );
      };

    const scheduleRealtimeRefresh =
      () => {
        clearTimer(
          refreshTimer,
        );
        refreshTimer =
          window.setTimeout(
            () => {
              refreshTimer =
                undefined;
              void refreshStatus();
            },
            200,
          );
      };

    const scheduleReconnect =
      () => {
        clearTimer(
          reconnectTimer,
        );
        reconnectTimer =
          undefined;
        if (
          disposed ||
          settled ||
          document.visibilityState !==
            "visible"
        ) {
          return;
        }

        const delay =
          productImportBackoffDelay(
            reconnectAttempt,
            Math.random(),
            1000,
          );
        reconnectAttempt += 1;
        reconnectTimer =
          window.setTimeout(
            () => {
              reconnectTimer =
                undefined;
              connectRealtime();
            },
            delay,
          );
      };

    const connectRealtime =
      () => {
        if (
          disposed ||
          settled ||
          document.visibilityState !==
            "visible"
        ) {
          return;
        }
        // At most one live or connecting socket may own the job feed.
        if (
          websocket &&
          (
            websocket.readyState === WebSocket.OPEN ||
            websocket.readyState === WebSocket.CONNECTING
          )
        ) {
          return;
        }
        if (!isOnline || !navigator.onLine) {
          scheduleFallback();
          return;
        }

        const token =
          localStorage.getItem(
            "admin_token",
          );
        if (!token) {
          scheduleFallback();
          return;
        }

        const apiBase = (
          import.meta.env.VITE_API_URL ||
          window.location.origin
        ).replace(
          /\/+$/,
          "",
        );
        const wsBase =
          apiBase.replace(
            /^http/,
            "ws",
          );
        let nextSocket: WebSocket;
        try {
          nextSocket =
            new WebSocket(
              `${wsBase}/simple-products/imports/${encodeURIComponent(
                importJobId,
              )}/ws`,
            );
        } catch {
          // Invalid endpoint configuration or browser security policy can
          // reject construction synchronously; preserve HTTP polling.
          websocket = undefined;
          realtimeOpen = false;
          scheduleFallback();
          scheduleReconnect();
          return;
        }
        websocket =
          nextSocket;

        nextSocket.onopen =
          () => {
            if (
              disposed ||
              settled ||
              websocket !==
                nextSocket
            ) {
              nextSocket.close();
              return;
            }
            const liveToken =
              localStorage.getItem(
                "admin_token",
              );
            if (!liveToken) {
              nextSocket.close();
              return;
            }
            nextSocket.send(
              JSON.stringify({
                type: "auth",
                token: liveToken,
              }),
            );
            // onopen is transport-only: keep HTTP fallback until the
            // server proves that authentication and tenant scope succeeded.
            void refreshStatus();
          };

        nextSocket.onmessage =
          (message) => {
            if (
              disposed ||
              settled ||
              websocket !==
                nextSocket
            ) {
              return;
            }
            try {
              const payload:
                unknown =
                JSON.parse(
                  message.data,
                );
              if (
                typeof payload === "object" &&
                payload !== null &&
                "event" in payload &&
                payload.event ===
                  "WS_AUTHENTICATED"
              ) {
                realtimeOpen =
                  true;
                reconnectAttempt =
                  0;
                fallbackAttempt =
                  0;
                clearTimer(
                  fallbackTimer,
                );
                fallbackTimer =
                  undefined;
                void refreshStatus();
                return;
              }
              if (
                isProductImportProgressEvent(
                  payload,
                  importJobId,
                )
              ) {
                scheduleRealtimeRefresh();
              }
            } catch {
              // Ignore malformed push data; canonical HTTP state remains authoritative.
            }
          };

        nextSocket.onclose =
          () => {
            // A previous connection can close after a newer one opens.
            // Never let a stale close event replace or reconnect the new feed.
            if (websocket !== nextSocket) {
              return;
            }
            websocket = undefined;
            realtimeOpen = false;
            if (
              disposed ||
              settled
            ) {
              return;
            }
            scheduleFallback();
            scheduleReconnect();
          };

        nextSocket.onerror =
          () => {
            // onclose owns fallback/reconnect to avoid duplicate timers.
          };
      };

    const handleVisibility =
      () => {
        if (
          document.visibilityState ===
          "hidden"
        ) {
          clearTransportTimers();
          closeRealtime();
          return;
        }

        fallbackAttempt = 0;
        reconnectAttempt = 0;
        void refreshStatus();
        connectRealtime();
      };

    document.addEventListener(
      "visibilitychange",
      handleVisibility,
    );

    void refreshStatus();
    connectRealtime();
    scheduleFallback();

    return () => {
      disposed = true;
      // Completion notifications belong to this job view, not a later tenant.
      if (completionToastId !== undefined) toast.dismiss(completionToastId);
      clearTransportTimers();
      closeRealtime();
      document.removeEventListener(
        "visibilitychange",
        handleVisibility,
      );
    };
  }, [
    authFetch,
    enabled,
    importJobId,
    importPollKey,
    isOnline,
    queryClient,
    setImportExpiryControlMode,
    setImportLotControlMode,
    setImportPollError,
    setImportStatus,
    setMapping,
    t,
  ]);

  const retryPoll =
    () => {
      setImportPollError(null);
      setImportPollKey(
        (current) =>
          current + 1,
      );
    };

  return {
    retryPoll,
  };
}
