import {
  AlertTriangle,
  Boxes,
  CloudOff,
  LoaderCircle,
  RotateCcw,
  SearchX,
  ShieldX,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  apiErrorMessage,
} from "@/lib/apiErrors";

export type ProductListBlockingState =
  | "loading"
  | "empty"
  | "filtered-empty"
  | "error"
  | "offline"
  | "permission";

type BlockingProps = {
  state: ProductListBlockingState;
  error?: unknown;
  onRetry: () => void;
  onClearCriteria: () => void;
};

export function ProductsListBlockingState({
  state,
  error,
  onRetry,
  onClearCriteria,
}: BlockingProps) {
  const { t } = useTranslation();

  const config =
    state === "loading"
      ? {
          Icon: LoaderCircle,
          iconClass:
            "animate-spin text-slate-500",
          title: t(
            "products.states.loadingTitle",
          ),
          description: t(
            "products.states.loadingDescription",
          ),
        }
      : state === "filtered-empty"
        ? {
            Icon: SearchX,
            iconClass:
              "text-slate-500",
            title: t(
              "products.states.filteredEmptyTitle",
            ),
            description: t(
              "products.states.filteredEmptyDescription",
            ),
          }
        : state === "offline"
          ? {
              Icon: CloudOff,
              iconClass:
                "text-amber-700",
              title: t(
                "products.states.offlineTitle",
              ),
              description: t(
                "products.states.offlineDescription",
              ),
            }
          : state === "permission"
            ? {
                Icon: ShieldX,
                iconClass:
                  "text-rose-700",
                title: t(
                  "products.states.permissionTitle",
                ),
                description: t(
                  "products.states.permissionDescription",
                ),
              }
            : state === "error"
              ? {
                  Icon: AlertTriangle,
                  iconClass:
                    "text-rose-700",
                  title: t(
                    "products.errors.listLoadTitle",
                  ),
                  description:
                    apiErrorMessage(
                      error,
                      t(
                        "products.errors.listLoadDescription",
                      ),
                    ),
                }
              : {
                  Icon: Boxes,
                  iconClass:
                    "text-slate-400",
                  title: t(
                    "products.emptyTitle",
                  ),
                  description: t(
                    "products.emptyDescription",
                  ),
                };

  const Icon = config.Icon;
  const alertState =
    state === "error" ||
    state === "permission";

  return (
    <div
      role={
        alertState
          ? "alert"
          : "status"
      }
      aria-live={
        alertState
          ? "assertive"
          : "polite"
      }
      className="flex min-h-0 flex-1 items-center justify-center bg-white px-5 py-12"
    >
      <div className="w-full max-w-md text-center">
        <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-50 ring-1 ring-slate-200">
          <Icon
            className={`h-5 w-5 ${config.iconClass}`}
          />
        </span>

        <h2 className="mt-3 text-sm font-black text-slate-900">
          {config.title}
        </h2>
        <p className="mx-auto mt-1 max-w-sm text-xs font-semibold leading-5 text-slate-500">
          {config.description}
        </p>

        {state ===
        "filtered-empty" ? (
          <button
            type="button"
            onClick={onClearCriteria}
            className="mt-4 inline-flex min-h-9 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-black text-slate-700 shadow-sm transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {t(
              "products.states.clearCriteria",
            )}
          </button>
        ) : null}

        {state === "error" ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-4 inline-flex min-h-9 items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 text-xs font-black text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {t("common.retry")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

type NoticeProps = {
  offline: boolean;
  error?: unknown;
  onRetry: () => void;
};

export function ProductsListNotice({
  offline,
  error,
  onRetry,
}: NoticeProps) {
  const { t } = useTranslation();
  const Icon =
    offline
      ? CloudOff
      : AlertTriangle;

  return (
    <div
      role="status"
      aria-live="polite"
      className={
        "mx-3 mt-3 flex shrink-0 flex-col gap-2 rounded-xl border px-3 py-2.5 sm:mx-4 sm:flex-row sm:items-center sm:justify-between " +
        (
          offline
            ? "border-amber-200 bg-amber-50/70"
            : "border-rose-200 bg-rose-50/70"
        )
      }
    >
      <div className="flex min-w-0 items-start gap-2">
        <Icon
          className={
            "mt-0.5 h-4 w-4 shrink-0 " +
            (
              offline
                ? "text-amber-700"
                : "text-rose-700"
            )
          }
        />
        <p
          className={
            "min-w-0 text-[11px] font-bold leading-5 " +
            (
              offline
                ? "text-amber-900"
                : "text-rose-900"
            )
          }
        >
          {offline
            ? t(
                "products.states.offlineCachedDescription",
              )
            : apiErrorMessage(
                error,
                t(
                  "products.states.refreshFailedDescription",
                ),
              )}
        </p>
      </div>

      {!offline ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg bg-white px-2.5 text-[10px] font-black text-rose-800 ring-1 ring-rose-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          {t("common.retry")}
        </button>
      ) : null}
    </div>
  );
}
