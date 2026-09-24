import {
  useEffect,
  useState,
} from "react";
import {
  AlertTriangle,
  Archive,
  PauseCircle,
  PlayCircle,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  apiErrorCode,
  apiErrorMessage,
  isAmbiguousRequestError,
} from "@/lib/apiErrors";
import {
  abandonDurableOperation,
  completeDurableOperation,
  durableScope,
  getOrCreateDurableCommand,
  readDurableCommand,
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  parseArchivePreflight,
  parseMutationMessage,
  parseVariantMutation,
  type ArchivePreflight,
  type CatalogVariant,
} from "./contracts";

type LifecycleCommandName =
  | "publish"
  | "delete-draft"
  | "retire"
  | "restore"
  | "archive"
  | "sales-hold"
  | "release-sales-hold"
  | "recall"
  | "close-recall";

type LifecyclePayload = {
  command: LifecycleCommandName;
  expected_version: number;
  reason: string;
  target_hold?: "NONE" | "SALES_HOLD";
};

type Props = {
  variant: CatalogVariant;
  onVariantChanged: (
    variant: CatalogVariant,
  ) => void | Promise<void>;
  onVariantDeleted?: (
    variantId: number,
  ) => void | Promise<void>;
};

const COMMANDS: LifecycleCommandName[] = [
  "publish",
  "delete-draft",
  "retire",
  "restore",
  "archive",
  "sales-hold",
  "release-sales-hold",
  "recall",
  "close-recall",
];

const isLifecyclePayload = (
  value: unknown,
): value is LifecyclePayload => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<
    string,
    unknown
  >;
  const command =
    String(row.command);
  const reason = row.reason;
  const expectedVersion =
    row.expected_version;
  const targetHold =
    row.target_hold;

  if (
    !COMMANDS.includes(
      command as LifecycleCommandName,
    ) ||
    typeof expectedVersion !==
      "number" ||
    !Number.isSafeInteger(
      expectedVersion,
    ) ||
    expectedVersion <= 0 ||
    typeof reason !== "string" ||
    reason.trim().length < 3 ||
    reason.length > 1000
  ) {
    return false;
  }

  if (command === "close-recall") {
    return (
      targetHold === "NONE" ||
      targetHold === "SALES_HOLD"
    );
  }

  return targetHold === undefined;
};

export function CatalogLifecycleActions({
  variant,
  onVariantChanged,
  onVariantDeleted,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();

  const [reason, setReason] =
    useState("");
  const [busy, setBusy] =
    useState(false);
  const [
    preflight,
    setPreflight,
  ] =
    useState<ArchivePreflight | null>(
      null,
    );
  const [
    pending,
    setPending,
  ] = useState<
    DurableCommand<LifecyclePayload> | null
  >(null);
  const [
    pendingBlocked,
    setPendingBlocked,
  ] = useState(false);

  const companyId =
    access.data?.company_id ??
    null;
  const driverId =
    access.data?.driver_id ??
    null;
  const scope =
    companyId !== null &&
    driverId !== null
      ? durableScope(
          companyId,
          driverId,
          "catalog-lifecycle-command-v1",
          variant.id,
        )
      : null;

  const can = (
    permission: string,
  ) =>
    access.isCompanyAdmin ||
    access.can(permission);

  useEffect(() => {
    setPreflight(null);
  }, [
    variant.id,
    variant.version,
  ]);

  useEffect(() => {
    let cancelled = false;
    setPending(null);
    setPendingBlocked(false);

    if (!scope) {
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const stored =
          await readDurableCommand<unknown>(
            scope,
          );
        if (
          cancelled ||
          !stored
        ) {
          return;
        }
        if (
          !isLifecyclePayload(
            stored.payload,
          )
        ) {
          setPendingBlocked(true);
          toast.error(
            apiErrorMessage(
              Object.assign(
                new Error(),
                {
                  code:
                    "DURABLE_OPERATION_CORRUPT",
                },
              ),
              t(
                "catalogLifecycle.errors.action",
              ),
            ),
          );
          return;
        }
        const restored = {
          requestId:
            stored.requestId,
          payload:
            stored.payload,
          createdAt:
            stored.createdAt,
        };
        setPending(restored);
        setReason(
          restored.payload.reason,
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPendingBlocked(true);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "catalogLifecycle.errors.action",
            ),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [scope, t]);

  const runCommand = async (
    command:
      | LifecycleCommandName
      | null,
    extra: {
      target_hold?:
        | "NONE"
        | "SALES_HOLD";
    } = {},
  ) => {
    if (
      busy ||
      !scope ||
      !isOnline ||
      pendingBlocked
    ) {
      return;
    }

    const clean =
      reason.trim();
    if (
      !pending &&
      (clean.length < 3 ||
        clean.length > 1000)
    ) {
      toast.error(
        t(
          "catalogLifecycle.errors.reason",
        ),
      );
      return;
    }

    if (
      !pending &&
      command === "archive" &&
      (
        !preflight?.can_archive ||
        preflight.variant_id !==
          variant.id ||
        preflight.version !==
          variant.version
      )
    ) {
      toast.error(
        t(
          "catalogLifecycle.errors.preflightRequired",
        ),
      );
      return;
    }

    setBusy(true);
    try {
      const freshPayload:
        LifecyclePayload | null =
        command === null
          ? null
          : {
              command,
              expected_version:
                variant.version,
              reason: clean,
              ...(command ===
              "close-recall"
                ? {
                    target_hold:
                      extra.target_hold ??
                      "NONE",
                  }
                : {}),
            };

      const durable =
        pending ??
        (freshPayload
          ? await getOrCreateDurableCommand(
              scope,
              freshPayload,
            )
          : null);

      if (
        !durable ||
        !isLifecyclePayload(
          durable.payload,
        )
      ) {
        throw Object.assign(
          new Error(),
          {
            code:
              "DURABLE_OPERATION_CORRUPT",
          },
        );
      }

      setPending(durable);
      const payload =
        durable.payload;
      const responseBody = {
        request_id:
          durable.requestId,
        expected_version:
          payload.expected_version,
        reason:
          payload.reason,
        ...(payload.command ===
        "close-recall"
          ? {
              target_hold:
                payload.target_hold ??
                "NONE",
            }
          : {}),
      };

      if (
        payload.command ===
        "delete-draft"
      ) {
        parseMutationMessage(
          await authFetch(
            `/catalog/variants/${variant.id}/${payload.command}`,
            {
              method: "POST",
              body: JSON.stringify(
                responseBody,
              ),
            },
          ),
        );
        completeDurableOperation(
          scope,
          durable.requestId,
        );
        setPending(null);
        setReason("");
        toast.success(
          t(
            "catalogLifecycle.success.deleteDraft",
          ),
        );
        if (onVariantDeleted) {
          await onVariantDeleted(
            variant.id,
          );
        }
        return;
      }

      const result =
        parseVariantMutation(
          await authFetch(
            `/catalog/variants/${variant.id}/${payload.command}`,
            {
              method: "POST",
              body: JSON.stringify(
                responseBody,
              ),
            },
          ),
        );

      if (
        result.variant.id !==
        variant.id
      ) {
        throw new Error(
          "CATALOG_LIFECYCLE_SCOPE_MISMATCH",
        );
      }

      completeDurableOperation(
        scope,
        durable.requestId,
      );
      setPending(null);
      setPendingBlocked(false);
      setReason("");
      setPreflight(null);
      toast.success(
        result.message,
      );
      await onVariantChanged(
        result.variant,
      );
    } catch (error) {
      const code =
        apiErrorCode(error);
      const durableConflict =
        code ===
        "DURABLE_OPERATION_PENDING";
      const durableCorrupt =
        code ===
        "DURABLE_OPERATION_CORRUPT";

      if (durableCorrupt) {
        setPendingBlocked(true);
      }

      if (
        !durableConflict &&
        !durableCorrupt &&
        !isAmbiguousRequestError(
          error,
        ) &&
        scope
      ) {
        abandonDurableOperation(
          scope,
        );
        setPending(null);
      }

      toast.error(
        apiErrorMessage(
          error,
          t(
            "catalogLifecycle.errors.action",
          ),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const checkArchive =
    async () => {
      if (
        busy ||
        !isOnline
      ) {
        return;
      }
      setBusy(true);
      try {
        const result =
          parseArchivePreflight(
            await authFetch(
              `/catalog/variants/${variant.id}/archive-preflight`,
            ),
          );
        if (
          result.variant_id !==
            variant.id ||
          result.version !==
            variant.version
        ) {
          throw new Error(
            "CATALOG_LIFECYCLE_PREFLIGHT_STALE",
          );
        }
        setPreflight(result);
        if (
          result.can_archive
        ) {
          toast.success(
            t(
              "catalogLifecycle.preflightPassed",
            ),
          );
        }
      } catch (error) {
        setPreflight(null);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "catalogLifecycle.errors.preflight",
            ),
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const actionClass =
    "rounded-lg border px-3 py-2 text-xs font-black disabled:cursor-not-allowed disabled:opacity-40";
  const actionsDisabled =
    busy ||
    !isOnline ||
    pending !== null ||
    pendingBlocked ||
    scope === null;

  return (
    <section className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-black text-slate-800">
            {t(
              "catalogLifecycle.title",
            )}
          </h3>
          <p className="mt-1 text-xs font-bold text-slate-500">
            {t(
              "catalogLifecycle.summary",
              {
                lifecycle: t(
                  `products.details.lifecycleModes.${variant.lifecycle_status}`,
                ),
                hold: t(
                  `products.details.holdModes.${variant.operational_hold}`,
                ),
                version:
                  variant.version,
              },
            )}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {variant.lifecycle_status ===
            "DRAFT" &&
          can(
            "catalog.publish",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "publish",
                )
              }
            >
              <PlayCircle className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.publish",
              )}
            </button>
          ) : null}

          {variant.lifecycle_status ===
            "DRAFT" &&
          can(
            "catalog.manage",
          ) &&
          onVariantDeleted ? (
            <button
              type="button"
              className={
                `${actionClass} border-red-200 text-red-700`
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "delete-draft",
                )
              }
            >
              <Trash2 className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.deleteDraft",
              )}
            </button>
          ) : null}

          {variant.lifecycle_status ===
            "ACTIVE" &&
          can(
            "catalog.retire",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "retire",
                )
              }
            >
              <PauseCircle className="me-1 inline h-4 w-4" />
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
          can(
            "catalog.restore",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "restore",
                )
              }
            >
              <PlayCircle className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.restore",
              )}
            </button>
          ) : null}

          {variant.lifecycle_status ===
            "RETIRING" &&
          can(
            "catalog.archive",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                busy ||
                !isOnline ||
                pendingBlocked
              }
              onClick={() =>
                void checkArchive()
              }
            >
              <Archive className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.checkArchive",
              )}
            </button>
          ) : null}

          {variant.lifecycle_status ===
            "RETIRING" &&
          preflight?.can_archive &&
          preflight.version ===
            variant.version &&
          can(
            "catalog.archive",
          ) ? (
            <button
              type="button"
              className={
                `${actionClass} bg-slate-800 text-white`
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "archive",
                )
              }
            >
              <Archive className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.archive",
              )}
            </button>
          ) : null}

          {variant.operational_hold ===
            "NONE" &&
          [
            "ACTIVE",
            "RETIRING",
          ].includes(
            variant.lifecycle_status,
          ) &&
          can(
            "catalog.hold",
          ) ? (
            <button
              type="button"
              className={
                `${actionClass} border-amber-200 text-amber-700`
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "sales-hold",
                )
              }
            >
              <AlertTriangle className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.salesHold",
              )}
            </button>
          ) : null}

          {variant.operational_hold ===
            "SALES_HOLD" &&
          can(
            "catalog.hold",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "release-sales-hold",
                )
              }
            >
              <PlayCircle className="me-1 inline h-4 w-4" />
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
          can(
            "catalog.hold",
          ) ? (
            <button
              type="button"
              className={
                `${actionClass} border-red-200 text-red-700`
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "recall",
                )
              }
            >
              <ShieldAlert className="me-1 inline h-4 w-4" />
              {t(
                "catalogLifecycle.actions.recall",
              )}
            </button>
          ) : null}

          {variant.operational_hold ===
            "RECALL" &&
          can(
            "catalog.hold",
          ) ? (
            <button
              type="button"
              className={
                actionClass
              }
              disabled={
                actionsDisabled
              }
              onClick={() =>
                void runCommand(
                  "close-recall",
                  {
                    target_hold:
                      "NONE",
                  },
                )
              }
            >
              {t(
                "catalogLifecycle.actions.closeRecall",
              )}
            </button>
          ) : null}
        </div>
      </div>

      <label className="mt-3 block text-xs font-bold text-slate-600">
        {t(
          "catalogLifecycle.reason",
        )}
        <input
          value={reason}
          maxLength={1000}
          disabled={
            busy ||
            pending !== null ||
            pendingBlocked
          }
          onChange={(event) =>
            setReason(
              event.target.value,
            )
          }
          placeholder={t(
            "catalogLifecycle.reasonPlaceholder",
          )}
          className="mt-1 w-full rounded-lg border p-2 disabled:bg-slate-50"
        />
      </label>

      {pending ? (
        <div className="mt-3 rounded-xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
          <p>
            {t(
              "catalogLifecycle.pendingRetry",
              {
                action: t(
                  `catalogLifecycle.actions.${pending.payload.command === "delete-draft" ? "deleteDraft" : pending.payload.command === "sales-hold" ? "salesHold" : pending.payload.command === "release-sales-hold" ? "releaseSalesHold" : pending.payload.command === "close-recall" ? "closeRecall" : pending.payload.command}`,
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
            onClick={() =>
              void runCommand(
                null,
              )
            }
            className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-black text-amber-900 disabled:opacity-40"
          >
            {t(
              "catalogLifecycle.retryPending",
            )}
          </button>
        </div>
      ) : null}

      {pendingBlocked ? (
        <p className="mt-3 rounded-xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-800">
          {t(
            "catalogLifecycle.pendingBlocked",
          )}
        </p>
      ) : null}

      {preflight &&
      !preflight.can_archive ? (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-900">
          <p>
            {t(
              "catalogLifecycle.blockersTitle",
            )}
          </p>
          <ul className="mt-2 space-y-1">
            {preflight.blockers.map(
              (item) => (
                <li
                  key={
                    item.code
                  }
                >
                  {t(
                    `catalogLifecycle.blockers.${item.code}`,
                    {
                      defaultValue:
                        item.code,
                    },
                  )}
                  : {item.count}
                  {item.sample_id
                    ? ` · #${item.sample_id}`
                    : ""}
                </li>
              ),
            )}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
