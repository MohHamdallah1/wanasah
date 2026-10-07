import {
  Archive,
  CircleAlert,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ReasonPresetField } from "@/components/forms/ReasonPresetField";
import { ArchiveBlockerList } from "@/features/catalog/archive/ArchiveBlockerList";
import {
  type ArchivePreflight,
  type CatalogVariant,
} from "@/features/catalog/contracts";
import {
  productCommercialStatus,
} from "@/features/catalog/status/productCommercialStatus";

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
  | "cancel-recall";

const lifecycleReasonPresetKeys: Record<
  SimpleLifecycleCommand,
  readonly string[]
> = {
  publish: ["initialActivation"],
  retire: [
    "productDiscontinued",
    "productReplaced",
    "supplierStopped",
    "noLongerUsed",
  ],
  restore: [
    "resumeUse",
    "decisionReversed",
    "supplyRestored",
  ],
  archive: ["recordCleanup", "endOfUse"],
  "sales-hold": [
    "temporarySupplyPause",
    "temporaryReview",
    "pricingReview",
    "administrativePause",
  ],
  "release-sales-hold": [
    "temporaryIssueResolved",
    "reviewCompleted",
    "supplyRestored",
  ],
  recall: [
    "qualityIssue",
    "safetyIssue",
    "labelingIssue",
    "supplierRequest",
    "regulatoryRequest",
  ],
  "cancel-recall": [
    "issueNotConfirmed",
    "falseAlarm",
    "scopeLimitedToBatch",
    "inspectionPassed",
  ],
};

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
  recallHasCurrentStock: boolean | null;
  onChooseCommand: (
    command: SimpleLifecycleCommand,
  ) => void;
  onManageBatchIssue: () => void;
  onManageWholeProductIssue: () => void;
  onOpenBlocker: (code: string) => void;
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
  disabledReason?: string;
  onClick: () => void;
  emphasis?: "normal" | "warning";
};

function ActionItem({
  icon,
  label,
  hint,
  disabled,
  disabledReason,
  onClick,
  emphasis = "normal",
}: ActionItemProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      title={disabled && disabledReason ? disabledReason : undefined}
      onClick={onClick}
      className="group grid w-full grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-2.5 py-2 text-start transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-40"
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
      <span className="min-w-0">
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
      <span
        aria-hidden="true"
        className="text-sm font-black text-slate-300 transition group-hover:text-slate-500"
      >
        ←
      </span>
    </button>
  );
}

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
  recallHasCurrentStock,
  onChooseCommand,
  onManageBatchIssue,
  onManageWholeProductIssue,
  onOpenBlocker,
  onReasonChange,
  onConfirm,
  onCancel,
  onRetryPending,
}: Props) {
  const { t } = useTranslation();
  const commercial =
    productCommercialStatus(variant);
  const [issueScopeOpen, setIssueScopeOpen] =
    useState(false);
  const reasonPresets = useMemo(
    () =>
      selectedCommand
        ? lifecycleReasonPresetKeys[selectedCommand].map((key) =>
            t(`catalogLifecycle.simple.reasonPresets.${key}`),
          )
        : [],
    [selectedCommand, t],
  );

  const showAvailableStopOptions =
    commercial.state === "available";
  const supportsBatchScope =
    variant.lot_control_mode !== "NONE" ||
    variant.expiry_control_mode !== "NONE";
  const showTemporaryRecovery =
    commercial.state === "stopped" &&
    variant.operational_hold ===
      "SALES_HOLD";
  const showProblemRecovery =
    commercial.state === "stopped" &&
    variant.operational_hold === "RECALL";
  const showDraftActivation =
    commercial.state === "stopped" &&
    variant.lifecycle_status === "DRAFT" &&
    variant.operational_hold === "NONE";
  const showStoppedProductActions =
    commercial.state === "stopped" &&
    variant.lifecycle_status ===
      "RETIRING" &&
    variant.operational_hold === "NONE";
  const showArchivedRecovery =
    commercial.state === "archived";

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-[0_14px_36px_-34px_rgba(15,23,42,0.55)]">
      <div className="px-4 py-3 sm:px-5 sm:py-4">
        {!issueScopeOpen && !selectedCommand ? (
          <>
        <p className="mb-2 text-[10px] font-black text-slate-400">
          {t("products.commercialStatus.availableActionsTitle")}
        </p>

        <div className="grid gap-1 md:max-w-2xl">
          {showAvailableStopOptions &&
          canHold ? (
            <>
              <ActionItem
                icon={<Pause className="h-3.5 w-3.5" />}
                label={t(
                  "catalogLifecycle.actions.salesHold",
                )}
                hint={t(
                  "catalogLifecycle.simple.actionHints.salesHold",
                )}
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "sales-hold",
                  )
                }
              />
            </>
          ) : null}

          {showAvailableStopOptions &&
          canRetire ? (
            <ActionItem
              icon={<Archive className="h-3.5 w-3.5" />}
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

          {showTemporaryRecovery &&
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

          {showProblemRecovery &&
          canHold ? (
            <>
              <ActionItem
                icon={<Play className="h-3.5 w-3.5" />}
                label={t(
                  "catalogLifecycle.actions.cancelRecall",
                )}
                hint={t(
                  "catalogLifecycle.simple.actionHints.cancelRecall",
                )}
                disabled={actionsDisabled}
                onClick={() =>
                  onChooseCommand(
                    "cancel-recall",
                  )
                }
              />
              <span
                className="block w-full"
                title={
                  recallHasCurrentStock === false
                    ? t("catalogLifecycle.simple.qualityIssueNoStock")
                    : undefined
                }
              >
                <ActionItem
                  icon={<ShieldCheck className="h-3.5 w-3.5" />}
                  label={t(
                    "catalogLifecycle.simple.manageConfirmedIssue",
                  )}
                  hint={t(
                    recallHasCurrentStock === false
                      ? "catalogLifecycle.simple.qualityIssueNoStock"
                      : "catalogLifecycle.simple.manageConfirmedIssueHint",
                  )}
                  disabled={actionsDisabled || recallHasCurrentStock !== true}
                  disabledReason={
                    recallHasCurrentStock === false
                      ? t("catalogLifecycle.simple.qualityIssueNoStock")
                      : undefined
                  }
                  onClick={onManageWholeProductIssue}
                  emphasis="warning"
                />
              </span>
            </>
          ) : null}

          {showDraftActivation &&
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

          {showStoppedProductActions &&
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

          {showStoppedProductActions &&
          canArchive ? (
            <ActionItem
              icon={<Archive className="h-3.5 w-3.5" />}
              label={t(
                "catalogLifecycle.actions.archive",
              )}
              hint={t(
                "catalogLifecycle.simple.actionHints.archiveDeferred",
              )}
              disabled
              onClick={() => undefined}
            />
          ) : null}

          {showArchivedRecovery &&
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
        </div>
          </>
        ) : null}

        {showAvailableStopOptions && canHold && !selectedCommand ? (
          <div className={issueScopeOpen ? "md:max-w-2xl" : "mt-4 border-t border-slate-100 pt-4 md:max-w-2xl"}>
            {!issueScopeOpen ? (
              <>
                <span
                  className="block w-full"
                  title={
                    recallHasCurrentStock === false
                      ? t("catalogLifecycle.simple.qualityIssueNoStock")
                      : undefined
                  }
                >
                  <ActionItem
                    icon={<CircleAlert className="h-3.5 w-3.5" />}
                    label={t(
                      "catalogLifecycle.simple.qualityIssueTitle",
                    )}
                    hint={t(
                      recallHasCurrentStock === false
                        ? "catalogLifecycle.simple.qualityIssueNoStock"
                        : "catalogLifecycle.simple.qualityIssueHint",
                    )}
                    disabled={actionsDisabled || recallHasCurrentStock !== true}
                    disabledReason={
                      recallHasCurrentStock === false
                        ? t("catalogLifecycle.simple.qualityIssueNoStock")
                        : undefined
                    }
                    onClick={() => {
                      onCancel();
                      setIssueScopeOpen(true);
                    }}
                    emphasis="warning"
                  />
                </span>
                {recallHasCurrentStock === false ? (
                  <p className="mt-1 px-2 text-[9px] font-bold leading-4 text-slate-500">
                    {t("catalogLifecycle.simple.qualityIssueNoStock")}
                  </p>
                ) : null}
              </>
            ) : (
              <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.45)]">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-black text-slate-950">
                      {t(
                        "catalogLifecycle.simple.issueScopeQuestion",
                      )}
                    </p>
                    <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
                      {t(
                        "catalogLifecycle.simple.issueScopeHint",
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={actionsDisabled}
                    onClick={() => setIssueScopeOpen(false)}
                    className="shrink-0 rounded-lg px-2 py-1 text-[9px] font-black text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40"
                  >
                    {t("common.back")}
                  </button>
                </div>
                <div className="mt-3 divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 [&>button]:rounded-none">
                  <ActionItem
                    icon={<CircleAlert className="h-3.5 w-3.5" />}
                    label={t(
                      "catalogLifecycle.simple.issueScopes.batch.label",
                    )}
                    hint={t(
                      supportsBatchScope
                        ? "catalogLifecycle.simple.issueScopes.batch.hint"
                        : "catalogLifecycle.simple.issueScopes.batch.unavailableHint",
                    )}
                    disabled={actionsDisabled || !supportsBatchScope}
                    onClick={() => {
                      setIssueScopeOpen(false);
                      onManageBatchIssue();
                    }}
                  />
                  <ActionItem
                    icon={<ShieldCheck className="h-3.5 w-3.5" />}
                    label={t(
                      "catalogLifecycle.simple.issueScopes.product.label",
                    )}
                    hint={t(
                      "catalogLifecycle.simple.issueScopes.product.hint",
                    )}
                    disabled={actionsDisabled || recallHasCurrentStock !== true}
                    onClick={() => {
                      setIssueScopeOpen(false);
                      onChooseCommand("recall");
                    }}
                    emphasis="warning"
                  />
                </div>
              </div>
            )}
          </div>
        ) : null}
      </div>

      {selectedCommand &&
      selectedActionKey ? (
        <div className="px-4 py-3 sm:px-5 sm:py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
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
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="shrink-0 rounded-lg px-2 py-1 text-[9px] font-black text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200 disabled:opacity-40"
            >
              {t("common.back")}
            </button>
          </div>

          <div className="mt-3">
            <ReasonPresetField
              label={t("catalogLifecycle.reason")}
              chooseLabel={t(
                "catalogLifecycle.simple.reasonChoose",
              )}
              otherLabel={t(
                "catalogLifecycle.simple.reasonOther",
              )}
              customPlaceholder={t(
                "catalogLifecycle.reasonPlaceholder",
              )}
              presets={reasonPresets}
              value={reason}
              onChange={onReasonChange}
              disabled={
                busy ||
                pendingActionKey !== null ||
                pendingBlocked
              }
              maxLength={1000}
              autoFocus
              canSubmit={reason.trim().length >= 3}
              onSubmit={onConfirm}
              onCancel={onCancel}
            />
          </div>

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
                selectedCommand === "recall"
                  ? "catalogLifecycle.simple.continueToHandling"
                  : "catalogLifecycle.simple.confirm",
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
        <div className="border-t border-slate-100 bg-amber-50/50 px-5 py-4 text-[10px] font-bold text-amber-950">
          <p className="text-xs font-black">
            {t(
              "catalogLifecycle.blockersTitle",
            )}
          </p>
          <p className="mt-1 text-[9px] font-semibold leading-4 text-amber-900/80">
            {t("catalogLifecycle.simple.archiveBlockersHint")}
          </p>
          <ArchiveBlockerList blockers={preflight.blockers} variantId={variant.id} />
        </div>
      ) : null}
    </section>
  );
}
