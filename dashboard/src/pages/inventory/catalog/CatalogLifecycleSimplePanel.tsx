import {
  Archive,
  CircleAlert,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  type ArchivePreflight,
  type CatalogVariant,
} from "@/pages/inventory/catalog/contracts";

export type RecallCompletionBlocker = {
  code: string;
  count: number;
};

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
  recallCompletionBlockers: RecallCompletionBlocker[];
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

type ActionItemProps = {
  icon: ReactNode;
  label: string;
  hint: string;
  disabled: boolean;
  onClick: () => void;
  title?: string;
  emphasis?: "normal" | "warning";
};

function ActionItem({
  icon,
  label,
  hint,
  disabled,
  onClick,
  title,
  emphasis = "normal",
}: ActionItemProps) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="group grid w-full grid-cols-[2rem_minmax(0,1fr)] items-start gap-2 rounded-xl px-2 py-2 text-start transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <span
        className={`flex h-8 w-8 items-center justify-center rounded-full ring-1 ring-inset ${
          emphasis === "warning"
            ? "bg-rose-50 text-rose-700 ring-rose-100"
            : "bg-slate-50 text-slate-600 ring-slate-200"
        }`}
      >
        {icon}
      </span>
      <span className="min-w-0 pt-0.5">
        <span
          className={`block text-[11px] font-black ${
            emphasis === "warning"
              ? "text-rose-800"
              : "text-slate-900"
          }`}
        >
          {label}
        </span>
        <span className="mt-0.5 block text-[9px] font-semibold leading-4 text-slate-500">
          {hint}
        </span>
      </span>
    </button>
  );
}

const productDot = (
  status: CatalogVariant["lifecycle_status"],
) =>
  status === "ACTIVE"
    ? "bg-emerald-500"
    : status === "RETIRING"
      ? "bg-amber-500"
      : status === "ARCHIVED"
        ? "bg-slate-400"
        : "bg-sky-500";

const salesDot = (
  hold: CatalogVariant["operational_hold"],
) =>
  hold === "NONE"
    ? "bg-emerald-500"
    : hold === "SALES_HOLD"
      ? "bg-amber-500"
      : "bg-rose-500";

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
  recallCompletionBlockers,
  onChooseCommand,
  onReasonChange,
  onConfirm,
  onCancel,
  onRetryPending,
}: Props) {
  const { t } = useTranslation();

  return (
    <section className="overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_18px_50px_-42px_rgba(15,23,42,0.65)]">
      <div className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_15rem] md:items-center">
        <div className="min-w-0">
          <p className="text-[10px] font-black text-slate-400">
            {t(
              "catalogLifecycle.simple.productStatusTitle",
            )}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${productDot(
                variant.lifecycle_status,
              )}`}
            />
            <span className="text-base font-black text-slate-950">
              {t(
                `products.details.lifecycleModes.${variant.lifecycle_status}`,
              )}
            </span>
          </div>
          <p className="mt-1 max-w-xl text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              `catalogLifecycle.simple.lifecycleStatusHints.${variant.lifecycle_status}`,
            )}
          </p>
        </div>

        <div className="grid gap-1 border-slate-100 md:border-s md:ps-3">
          {variant.lifecycle_status ===
            "DRAFT" &&
          canPublish ? (
            <ActionItem
              icon={<Play className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.publish",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.publish",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "publish",
                )
              }
            />
          ) : null}

          {variant.lifecycle_status ===
            "ACTIVE" &&
          canRetire ? (
            <ActionItem
              icon={<Pause className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.retire",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.retire",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "retire",
                )
              }
            />
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
            <ActionItem
              icon={<RotateCcw className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.restore",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.restore",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "restore",
                )
              }
            />
          ) : null}

          {variant.lifecycle_status ===
            "RETIRING" &&
          canArchive ? (
            <ActionItem
              icon={<Archive className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.archive",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.archive",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "archive",
                )
              }
            />
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 border-t border-slate-100 px-5 py-4 md:grid-cols-[minmax(0,1fr)_15rem] md:items-start">
        <div className="min-w-0">
          <p className="text-[10px] font-black text-slate-400">
            {t(
              "catalogLifecycle.simple.salesStatusTitle",
            )}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`h-2 w-2 rounded-full ${salesDot(
                variant.operational_hold,
              )}`}
            />
            <span className="text-base font-black text-slate-950">
              {t(
                `products.details.holdModes.${variant.operational_hold}`,
              )}
            </span>
          </div>
          <p className="mt-1 max-w-xl text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              `catalogLifecycle.simple.salesHints.${variant.operational_hold}`,
            )}
          </p>

          {variant.operational_hold ===
          "RECALL" ? (
            <div className="mt-3 border-s-2 border-rose-400 ps-3">
              <p className="text-[10px] font-black text-rose-800">
                {t(
                  "catalogLifecycle.simple.problemSaleStopTitle",
                )}
              </p>
              <p className="mt-0.5 text-[9px] font-semibold leading-5 text-slate-600">
                {t(
                  "catalogLifecycle.simple.problemSaleStopHint",
                )}
              </p>
            </div>
          ) : null}
        </div>

        <div className="grid gap-1 border-slate-100 md:border-s md:ps-3">
          {variant.operational_hold ===
            "NONE" &&
          [
            "ACTIVE",
            "RETIRING",
          ].includes(
            variant.lifecycle_status,
          ) &&
          canHold ? (
            <>
              <ActionItem
                icon={<Pause className="h-3.5 w-3.5" />}
                label={t(
                  "catalogLifecycle.actions.salesHold",
                )}
                hint={t(
                  "catalogLifecycle.simple.salesHoldDifference",
                )}
                title={t(
                  "catalogLifecycle.simple.actionHints.salesHold",
                )}
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "sales-hold",
                  )
                }
              />
              <ActionItem
                icon={<CircleAlert className="h-3.5 w-3.5" />}
                label={t(
                  "catalogLifecycle.actions.recall",
                )}
                hint={t(
                  "catalogLifecycle.simple.recallDifference",
                )}
                title={t(
                  "catalogLifecycle.simple.actionHints.recall",
                )}
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "recall",
                  )
                }
                emphasis="warning"
              />
            </>
          ) : null}

          {variant.operational_hold ===
            "SALES_HOLD" &&
          canHold ? (
            <ActionItem
              icon={<Play className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.releaseSalesHold",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.releaseSalesHold",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "release-sales-hold",
                )
              }
            />
          ) : null}

          {variant.operational_hold ===
            "RECALL" &&
          canHold ? (
            <ActionItem
              icon={<ShieldCheck className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.closeRecall",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.closeRecall",
              )}
              title={t(
                "catalogLifecycle.simple.actionHints.closeRecall",
              )}
              disabled={actionsDisabled}
              onClick={() =>
                onChooseCommand(
                  "close-recall",
                )
              }
            />
          ) : null}
        </div>
      </div>

      {selectedCommand &&
      selectedActionKey ? (
        <div className="border-t border-slate-100 bg-slate-50/60 px-5 py-4">
          <p className="text-xs font-black text-slate-900">
            {t(
              `catalogLifecycle.actions.${selectedActionKey}`,
            )}
          </p>
          <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-500">
            {t(
              `catalogLifecycle.simple.actionHints.${selectedActionKey}`,
            )}
          </p>

          <label className="mt-3 block text-[10px] font-black text-slate-600">
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
              className="rounded-lg bg-slate-950 px-4 py-2 text-[10px] font-black text-white transition hover:bg-slate-800 disabled:opacity-40"
            >
              {t(
                "catalogLifecycle.simple.confirm",
              )}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="rounded-lg px-3 py-2 text-[10px] font-black text-slate-500 transition hover:bg-white hover:text-slate-900 disabled:opacity-40"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {recallCompletionBlockers.length > 0 ? (
        <div
          role="alert"
          className="border-t border-slate-100 px-5 py-4"
        >
          <div className="border-s-2 border-rose-400 ps-3">
            <p className="text-xs font-black text-slate-950">
              {t(
                "catalogLifecycle.simple.recallCompletionTitle",
              )}
            </p>
            <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-600">
              {t(
                "catalogLifecycle.simple.recallCompletionHint",
              )}
            </p>
          </div>

          <div className="mt-3 divide-y divide-slate-100">
            {recallCompletionBlockers.map(
              (item) => (
                <div
                  key={item.code}
                  className="grid gap-1 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                >
                  <div className="min-w-0">
                    <p className="text-[10px] font-black text-slate-900">
                      {t(
                        `catalogLifecycle.blockers.${item.code}`,
                        {
                          defaultValue:
                            item.code,
                        },
                      )}
                    </p>
                    <p className="mt-0.5 text-[9px] font-semibold leading-4 text-slate-500">
                      {t(
                        `catalogLifecycle.simple.recallBlockerActions.${item.code}`,
                        {
                          defaultValue: t(
                            "catalogLifecycle.simple.recallCompletionHint",
                          ),
                        },
                      )}
                    </p>
                  </div>
                  <span className="text-xs font-black tabular-nums text-rose-700">
                    {item.count}
                  </span>
                </div>
              ),
            )}
          </div>
        </div>
      ) : null}

      {pendingActionKey ? (
        <div className="border-t border-slate-100 bg-amber-50/60 px-5 py-3 text-[10px] font-bold leading-5 text-amber-900">
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
            className="mt-2 text-[10px] font-black underline underline-offset-4 disabled:opacity-40"
          >
            {t(
              "catalogLifecycle.retryPending",
            )}
          </button>
        </div>
      ) : null}

      {pendingBlocked ? (
        <p className="border-t border-slate-100 bg-rose-50/60 px-5 py-3 text-[10px] font-bold leading-5 text-rose-800">
          {t(
            "catalogLifecycle.pendingBlocked",
          )}
        </p>
      ) : null}

      {preflight &&
      !preflight.can_archive ? (
        <div className="border-t border-slate-100 bg-amber-50/50 px-5 py-4 text-[10px] font-bold text-amber-900">
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
