import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

import i18n from "@/i18n";
import { normalizeApiErrorResponse } from "@/lib/apiErrors";
import {
  captureDashboardSession, isDashboardSessionCurrent, invalidateDashboardSession,
  readAccessTokenIfRefreshAdvanced, type DashboardSession,
} from "@/lib/authStorage";

const API = (
  import.meta.env.VITE_API_URL || ""
).replace(/\/$/, "");

if (!API) {
  throw new Error(
    "VITE_API_URL is not set."
  );
}

type RefreshFlight = {
  controller: AbortController;
  consumers: Set<symbol>;
  promise: Promise<string>;
};
// No queue or credentials are shared across login generations/identities.
const refreshFlights = new Map<string, RefreshFlight>();
const abandonedSession = () => new DOMException("Session changed or request aborted", "AbortError");
const assertSession = (session: DashboardSession, signal?: AbortSignal | null) => {
  if (!isDashboardSessionCurrent(session) || signal?.aborted) throw abandonedSession();
};

const joinRefresh = (
  session: DashboardSession,
  signal: AbortSignal | null | undefined,
  run: (signal: AbortSignal) => Promise<string>,
): Promise<string> => {
  assertSession(session, signal);
  const key = JSON.stringify(session);
  let flight = refreshFlights.get(key);
  if (!flight || flight.controller.signal.aborted) {
    const controller = new AbortController();
    const created: RefreshFlight = { controller, consumers: new Set(), promise: Promise.resolve("") };
    created.promise = Promise.resolve().then(() => run(controller.signal)).finally(() => {
      if (refreshFlights.get(key) === created) refreshFlights.delete(key);
    });
    refreshFlights.set(key, created);
    flight = created;
  }
  const joined = flight;
  const consumer = Symbol();
  joined.consumers.add(consumer);
  return new Promise<string>((resolve, reject) => {
    const leave = () => {
      signal?.removeEventListener("abort", abort);
      joined.consumers.delete(consumer);
      if (!joined.consumers.size) joined.controller.abort();
    };
    const abort = () => { leave(); reject(abandonedSession()); };
    signal?.addEventListener("abort", abort, { once: true });
    joined.promise.then(
      token => { leave(); try { assertSession(session, signal); resolve(token); } catch (error) { reject(error); } },
      error => { leave(); reject(error); },
    );
  });
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

  const forceLogout = useCallback((session: DashboardSession) => {
    if (!isDashboardSessionCurrent(session)) return;
    invalidateDashboardSession();
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
      const session = captureDashboardSession();
      assertSession(session, opts.signal);
      const token =
        localStorage.getItem(
          "admin_token"
        );
      if (!token) {
        forceLogout(session);
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
      ) => {
        assertSession(session, signal);
        const headers = new Headers(opts.headers);
        if (!isFormData && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
        headers.set("Authorization", `Bearer ${accessToken}`);
        return fetch(`${API}${cleanPath}`, { ...opts, signal, headers });
      };

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

        assertSession(session, opts.signal);
        if (res.status === 401) {
          // A concurrent same-session request may already have rotated access.
          const currentAccess = localStorage.getItem("admin_token");
          const newToken = currentAccess && currentAccess !== token
            ? currentAccess
            : await joinRefresh(session, opts.signal, async (refreshSignal) => {
              assertSession(session, refreshSignal);
              const refreshToken = localStorage.getItem("refresh_token");
              if (!refreshToken) {
                forceLogout(session);
                throw makeHttpError(i18n.t("network.sessionExpired"), 401);
              }
              try {
                if (navigator.onLine === false) throw networkError();
                const refreshRes = await fetch(`${API}/refresh`, {
                  method: "POST",
                  signal: refreshSignal,
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ refresh_token: refreshToken }),
                });
                assertSession(session, refreshSignal);
                // Another tab may have rotated this generation. Never replace its pair.
                const advanced = readAccessTokenIfRefreshAdvanced(refreshToken);
                if (advanced) return advanced;
                if (!refreshRes.ok) {
                  throw makeHttpError(i18n.t("network.refreshFailed"), refreshRes.status);
                }
                const data = await refreshRes.json();
                assertSession(session, refreshSignal);
                const advancedAfterBody = readAccessTokenIfRefreshAdvanced(refreshToken);
                if (advancedAfterBody) return advancedAfterBody;
                if (typeof data.token !== "string" || !data.token ||
                    (data.refresh_token !== undefined &&
                     (typeof data.refresh_token !== "string" || !data.refresh_token))) {
                  throw makeHttpError(i18n.t("network.invalidResponse"), 502);
                }
                localStorage.setItem("admin_token", data.token);
                if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
                return data.token as string;
              } catch (error) {
                // An old failure must not invalidate a new login or an aborted flight.
                assertSession(session, refreshSignal);
                const normalized = error instanceof TypeError ? networkError() : error;
                if ((normalized as HttpError)?.status === 401 ||
                    (normalized as HttpError)?.status === 403) forceLogout(session);
                throw normalized;
              }
            });
          assertSession(session, opts.signal);
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

        assertSession(session, opts.signal);
        let data: unknown = null;
        const raw =
          await res.text();
        assertSession(session, opts.signal);
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
            forceLogout(session);
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
