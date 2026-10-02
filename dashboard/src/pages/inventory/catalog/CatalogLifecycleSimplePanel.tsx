import {
  AlertTriangle,
  Archive,
  PauseCircle,
  PlayCircle,
  ShieldAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  type ArchivePreflight,
  type CatalogVariant,
} from "@/pages/inventory/catalog/contracts";

type SimpleLifecycleCommand =
  | "publish"
  | "retire"
  | "restore"
  | "archive"
  | "sales-hold"
  | "release-sales-hold"
  | "recall"
  | "close-recall";

type Props = {
  variant: CatalogVariant;
  actionsDisabled: boolean;
  busy: boolean;
  isOnline: boolean;
  pendingBlocked: boolean;
  canPublish: boolean;
  canRetire: boolean;
  canRestore: boolean;
  canArchive: boolean;
  canHold: boolean;
  selectedCommand:
    | SimpleLifecycleCommand
    | null;
  selectedActionKey: string | null;
  reason: string;
  pendingActionKey: string | null;
  preflight: ArchivePreflight | null;
  onChooseCommand: (
    command: SimpleLifecycleCommand,
  ) => void;
  onReasonChange: (
    value: string,
  ) => void;
  onConfirm: () => void;
  onCancel: () => void;
  onRetryPending: () => void;
};

export function CatalogLifecycleSimplePanel({
  variant,
  actionsDisabled,
  busy,
  isOnline,
  pendingBlocked,
  canPublish,
  canRetire,
  canRestore,
  canArchive,
  canHold,
  selectedCommand,
  selectedActionKey,
  reason,
  pendingActionKey,
  preflight,
  onChooseCommand,
  onReasonChange,
  onConfirm,
  onCancel,
  onRetryPending,
}: Props) {
  const { t } = useTranslation();

  return (
    <section className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-black text-slate-900">
            {t(
              "catalogLifecycle.simple.productStatusTitle",
            )}
          </h3>
          <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              "catalogLifecycle.simple.productStatusHint",
            )}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            {variant.lifecycle_status ===
              "DRAFT" &&
            canPublish ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "publish",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl bg-slate-950 px-3 text-xs font-black text-white disabled:opacity-40"
              >
                <PlayCircle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.publish",
                )}
              </button>
            ) : null}

            {variant.lifecycle_status ===
              "ACTIVE" &&
            canRetire ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "retire",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 text-xs font-black text-amber-900 disabled:opacity-40"
              >
                <PauseCircle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.retire",
                )}
              </button>
            ) : null}

            {(
              [
                "RETIRING",
                "ARCHIVED",
              ] as const
            ).includes(
              variant.lifecycle_status as
                | "RETIRING"
                | "ARCHIVED",
            ) &&
            canRestore ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "restore",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-black text-emerald-800 disabled:opacity-40"
              >
                <PlayCircle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.restore",
                )}
              </button>
            ) : null}

            {variant.lifecycle_status ===
              "RETIRING" &&
            canArchive ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "archive",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 text-xs font-black text-slate-700 disabled:opacity-40"
              >
                <Archive className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.archive",
                )}
              </button>
            ) : null}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-black text-slate-900">
            {t(
              "catalogLifecycle.simple.salesStatusTitle",
            )}
          </h3>
          <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              `catalogLifecycle.simple.salesHints.${variant.operational_hold}`,
            )}
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            {variant.operational_hold ===
              "NONE" &&
            [
              "ACTIVE",
              "RETIRING",
            ].includes(
              variant.lifecycle_status,
            ) &&
            canHold ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "sales-hold",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 text-xs font-black text-amber-900 disabled:opacity-40"
              >
                <AlertTriangle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.salesHold",
                )}
              </button>
            ) : null}

            {variant.operational_hold ===
              "SALES_HOLD" &&
            canHold ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "release-sales-hold",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-black text-emerald-800 disabled:opacity-40"
              >
                <PlayCircle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.releaseSalesHold",
                )}
              </button>
            ) : null}

            {[
              "NONE",
              "SALES_HOLD",
            ].includes(
              variant.operational_hold,
            ) &&
            [
              "ACTIVE",
              "RETIRING",
            ].includes(
              variant.lifecycle_status,
            ) &&
            canHold ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "recall",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-3 text-xs font-black text-rose-800 disabled:opacity-40"
              >
                <ShieldAlert className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.recall",
                )}
              </button>
            ) : null}

            {variant.operational_hold ===
              "RECALL" &&
            canHold ? (
              <button
                type="button"
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "close-recall",
                  )
                }
                className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 text-xs font-black text-slate-700 disabled:opacity-40"
              >
                <PlayCircle className="h-4 w-4" />
                {t(
                  "catalogLifecycle.actions.closeRecall",
                )}
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {selectedCommand &&
      selectedActionKey ? (
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
          <h3 className="text-xs font-black text-slate-900">
            {t(
              `catalogLifecycle.actions.${selectedActionKey}`,
            )}
          </h3>
          <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              `catalogLifecycle.simple.actionHints.${selectedActionKey}`,
            )}
          </p>

          <label className="mt-3 block text-xs font-black text-slate-600">
            {t(
              "catalogLifecycle.reason",
            )}
            <input
              autoFocus
              value={reason}
              maxLength={1000}
              disabled={
                busy ||
                pendingActionKey !== null ||
                pendingBlocked
              }
              onChange={(event) =>
                onReasonChange(
                  event.target.value,
                )
              }
              onKeyDown={(event) => {
                if (
                  event.key ===
                    "Enter" &&
                  reason.trim().length >=
                    3
                ) {
                  event.preventDefault();
                  onConfirm();
                }
                if (
                  event.key ===
                  "Escape"
                ) {
                  event.preventDefault();
                  onCancel();
                }
              }}
              placeholder={t(
                "catalogLifecycle.reasonPlaceholder",
              )}
              className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100 disabled:opacity-50"
            />
          </label>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={
                actionsDisabled ||
                reason.trim().length < 3
              }
              onClick={onConfirm}
              className="rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white disabled:opacity-40"
            >
              {t(
                "catalogLifecycle.simple.confirm",
              )}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-600 disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {pendingActionKey ? (
        <div className="rounded-xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
          <p>
            {t(
              "catalogLifecycle.pendingRetry",
              {
                action: t(
                  `catalogLifecycle.actions.${pendingActionKey}`,
                ),
              },
            )}
          </p>
          <button
            type="button"
            disabled={
              busy ||
              !isOnline
            }
            onClick={onRetryPending}
            className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-black text-amber-900 disabled:opacity-40"
          >
            {t(
              "catalogLifecycle.retryPending",
            )}
          </button>
        </div>
      ) : null}

      {pendingBlocked ? (
        <p className="rounded-xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-800">
          {t(
            "catalogLifecycle.pendingBlocked",
          )}
        </p>
      ) : null}

      {preflight &&
      !preflight.can_archive ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-900">
          <p>
            {t(
              "catalogLifecycle.blockersTitle",
            )}
          </p>
          <ul className="mt-2 space-y-1">
            {preflight.blockers.map(
              (item) => (
                <li key={item.code}>
                  {t(
                    `catalogLifecycle.blockers.${item.code}`,
                    {
                      defaultValue:
                        item.code,
                    },
                  )}
                  : {item.count}
                </li>
              ),
            )}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
