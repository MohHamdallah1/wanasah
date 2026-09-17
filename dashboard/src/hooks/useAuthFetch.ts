import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import i18n from "@/i18n";
import { normalizeApiErrorResponse } from "@/lib/apiErrors";

const API = (
  import.meta.env.VITE_API_URL || ""
).replace(/\/$/, "");

if (!API) {
  throw new Error(
    "VITE_API_URL is not set."
  );
}

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
}> = [];

const processQueue = (
  error: Error | null,
  token: string | null = null
) => {
  failedQueue.forEach((promise) => {
    if (error) {
      promise.reject(error);
    } else {
      promise.resolve(token!);
    }
  });
  failedQueue = [];
};

export type HttpError = Error & {
  status: number;
  data: unknown;
  code?: string;
  context?: Record<string, unknown>;
  requestId?: string;
  serverMessage?: string;
};

const makeHttpError = (
  message: string,
  status: number,
  data: unknown = null,
  code?: string,
  context?: Record<string, unknown>,
  requestId?: string,
  serverMessage?: string
): HttpError => {
  const error = new Error(
    message
  ) as HttpError;
  error.status = status;
  error.data = data;
  if (code) error.code = code;
  if (context) error.context = context;
  if (requestId) error.requestId = requestId;
  if (serverMessage) {
    error.serverMessage = serverMessage;
  }
  return error;
};

const networkError = () =>
  makeHttpError(
    i18n.t("network.offline"),
    0,
    null,
    "NETWORK_UNAVAILABLE"
  );

const timeoutError = () =>
  makeHttpError(
    i18n.t("network.timeout"),
    408,
    null,
    "REQUEST_TIMEOUT"
  );

const requestSignal = (
  supplied: AbortSignal | null | undefined,
  timeoutMs: number
) => {
  const controller =
    new AbortController();
  const timer = window.setTimeout(
    () => controller.abort(),
    timeoutMs
  );
  return {
    signal: supplied
      ? AbortSignal.any([
          supplied,
          controller.signal,
        ])
      : controller.signal,
    timer,
    controller,
  };
};

export function useAuthFetch() {
  const navigate = useNavigate();

  const forceLogout = useCallback(() => {
    const currentToken =
      localStorage.getItem(
        "admin_token"
      );
    const currentRefresh =
      localStorage.getItem(
        "refresh_token"
      );

    if (
      API &&
      currentToken &&
      navigator.onLine
    ) {
      void fetch(`${API}/logout`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${currentToken}`,
          "X-Refresh-Token":
            currentRefresh || "",
        },
      }).catch(() => undefined);
    }

    localStorage.removeItem(
      "admin_token"
    );
    localStorage.removeItem(
      "refresh_token"
    );
    navigate(
      "/login",
      { replace: true }
    );
  }, [navigate]);

  return useCallback(
    async (
      path: string,
      opts: RequestInit = {}
    ) => {
      const token =
        localStorage.getItem(
          "admin_token"
        );
      if (!token) {
        forceLogout();
        throw makeHttpError(
          i18n.t(
            "network.sessionExpired"
          ),
          401
        );
      }

      if (
        typeof navigator !==
          "undefined" &&
        navigator.onLine === false
      ) {
        throw networkError();
      }

      const cleanPath =
        path.startsWith("/")
          ? path
          : `/${path}`;
      const isFormData =
        typeof FormData !==
          "undefined" &&
        opts.body instanceof FormData;
      const timeoutMs =
        isFormData
          ? 120_000
          : 15_000;

      const perform = async (
        accessToken: string,
        signal: AbortSignal
      ) =>
        fetch(
          `${API}${cleanPath}`,
          {
            ...opts,
            signal,
            headers: {
              ...(isFormData
                ? {}
                : {
                    "Content-Type":
                      "application/json",
                  }),
              Authorization:
                `Bearer ${accessToken}`,
              ...(opts.headers ?? {}),
            },
          }
        );

      const first = requestSignal(
        opts.signal,
        timeoutMs
      );

      try {
        let res: Response;
        try {
          res = await perform(
            token,
            first.signal
          );
        } catch (error) {
          if (
            error instanceof Error &&
            error.name === "AbortError"
          ) {
            if (opts.signal?.aborted) {
              throw error;
            }
            throw timeoutError();
          }
          if (
            error instanceof TypeError
          ) {
            throw networkError();
          }
          throw error;
        } finally {
          clearTimeout(first.timer);
        }

        if (res.status === 401) {
          const refreshToken =
            localStorage.getItem(
              "refresh_token"
            );
          if (!refreshToken) {
            forceLogout();
            throw makeHttpError(
              i18n.t(
                "network.sessionExpired"
              ),
              401
            );
          }

          const newTokenPromise =
            new Promise<string>(
              (resolve, reject) => {
                failedQueue.push({
                  resolve,
                  reject,
                });
              }
            );

          if (!isRefreshing) {
            isRefreshing = true;
            try {
              if (
                typeof navigator !==
                  "undefined" &&
                navigator.onLine ===
                  false
              ) {
                throw networkError();
              }

              let refreshRes: Response;
              try {
                refreshRes =
                  await fetch(
                    `${API}/refresh`,
                    {
                      method: "POST",
                      headers: {
                        "Content-Type":
                          "application/json",
                      },
                      body: JSON.stringify({
                        refresh_token:
                          refreshToken,
                      }),
                    }
                  );
              } catch (error) {
                if (
                  error instanceof
                  TypeError
                ) {
                  throw networkError();
                }
                throw error;
              }

              if (!refreshRes.ok) {
                const authError =
                  makeHttpError(
                    i18n.t(
                      "network.refreshFailed"
                    ),
                    refreshRes.status
                  );
                processQueue(
                  authError,
                  null
                );
                if (
                  [400, 401, 403].includes(
                    refreshRes.status
                  )
                ) {
                  forceLogout();
                }
                throw authError;
              }

              const data =
                await refreshRes.json();
              localStorage.setItem(
                "admin_token",
                data.token
              );
              if (
                data.refresh_token
              ) {
                localStorage.setItem(
                  "refresh_token",
                  data.refresh_token
                );
              }
              processQueue(
                null,
                data.token
              );
            } catch (error) {
              const normalized =
                error instanceof Error
                  ? error
                  : networkError();
              processQueue(
                normalized,
                null
              );
              if (
                (
                  normalized as HttpError
                ).status === 401 ||
                (
                  normalized as HttpError
                ).status === 403
              ) {
                forceLogout();
              }
              throw normalized;
            } finally {
              isRefreshing = false;
            }
          }

          const newToken =
            await newTokenPromise;
          const retry =
            requestSignal(
              opts.signal,
              timeoutMs
            );
          try {
            try {
              res = await perform(
                newToken,
                retry.signal
              );
            } catch (error) {
              if (
                error instanceof Error &&
                error.name ===
                  "AbortError"
              ) {
                if (
                  opts.signal
                    ?.aborted
                ) {
                  throw error;
                }
                throw timeoutError();
              }
              if (
                error instanceof
                TypeError
              ) {
                throw networkError();
              }
              throw error;
            }
          } finally {
            clearTimeout(
              retry.timer
            );
          }
        }

        let data: unknown = null;
        const raw =
          await res.text();
        if (raw) {
          try {
            data =
              JSON.parse(raw);
          } catch {
            throw makeHttpError(
              i18n.t(
                "network.invalidResponse"
              ),
              502,
              null,
              "INVALID_SERVER_RESPONSE",
              undefined,
              res.headers.get(
                "X-Request-Id"
              ) || undefined
            );
          }
        }

        if (!res.ok) {
          const normalized =
            normalizeApiErrorResponse(
              data
            );
          const requestId =
            normalized.requestId ||
            res.headers.get(
              "X-Request-Id"
            ) ||
            undefined;

          if (
            res.status === 403 &&
            !cleanPath.startsWith(
              "/inventory/access/me"
            )
          ) {
            window.dispatchEvent(
              new Event(
                "inventory-permission-denied"
              )
            );
          }

          if (
            res.status === 403 &&
            normalized.code ===
              "ACCOUNT_DISABLED"
          ) {
            forceLogout();
          }

          throw makeHttpError(
            i18n.t(
              "network.serverError"
            ),
            res.status,
            data,
            normalized.code,
            normalized.context,
            requestId,
            normalized.message
          );
        }

        return data;
      } catch (error) {
        if (
          error instanceof
            TypeError
        ) {
          throw networkError();
        }
        throw error;
      }
    },
    [forceLogout]
  );
}
