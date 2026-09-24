import {
  useCallback,
  useEffect,
  useState,
} from "react";
import {
  Link2,
  Trash2,
} from "lucide-react";
import {
  useTranslation,
} from "react-i18next";
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
  parseMutationMessage,
  parseProductLocations,
  type CatalogVariant,
  type ProductLocationAssignment,
} from "./contracts";
import { CatalogLifecycleActions } from "./CatalogLifecycleActions";

interface LocationOption {
  id: number;
  code: string;
  name: string;
}

interface Props {
  variant: CatalogVariant;
  locations: LocationOption[];
  onVariantChanged: (
    variant: CatalogVariant,
  ) => void | Promise<void>;
  onVariantDeleted: (
    variantId: number,
  ) => void | Promise<void>;
}

type OperationalFlags = {
  inbound_enabled: boolean;
  outbound_enabled: boolean;
};

type AssignmentCommand =
  | {
      command: "create";
      product_variant_id: number;
      location_id: number;
      operational_flags: OperationalFlags;
    }
  | {
      command: "update";
      product_variant_id: number;
      product_location_id: number;
      location_id: number;
      expected_version: number;
      operational_flags: OperationalFlags;
    }
  | {
      command: "delete";
      product_variant_id: number;
      product_location_id: number;
      location_id: number;
      expected_version: number;
      reason: string;
    };

const positiveInteger = (
  value: unknown,
): value is number =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0;

const operationalFlags = (
  value: unknown,
): value is OperationalFlags => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row =
    value as Record<string, unknown>;
  return (
    typeof row.inbound_enabled ===
      "boolean" &&
    typeof row.outbound_enabled ===
      "boolean"
  );
};

const isAssignmentCommand = (
  value: unknown,
): value is AssignmentCommand => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row =
    value as Record<string, unknown>;

  if (
    !positiveInteger(
      row.product_variant_id,
    )
  ) {
    return false;
  }

  if (row.command === "create") {
    return (
      positiveInteger(
        row.location_id,
      ) &&
      operationalFlags(
        row.operational_flags,
      )
    );
  }

  if (row.command === "update") {
    return (
      positiveInteger(
        row.product_location_id,
      ) &&
      positiveInteger(
        row.location_id,
      ) &&
      positiveInteger(
        row.expected_version,
      ) &&
      operationalFlags(
        row.operational_flags,
      )
    );
  }

  if (row.command === "delete") {
    return (
      positiveInteger(
        row.product_location_id,
      ) &&
      positiveInteger(
        row.location_id,
      ) &&
      positiveInteger(
        row.expected_version,
      ) &&
      typeof row.reason ===
        "string" &&
      row.reason.trim().length >=
        3 &&
      row.reason.length <= 1000
    );
  }

  return false;
};

const codedError = (
  code: string,
): Error & { code: string } => {
  const error =
    new Error(code) as Error & {
      code: string;
    };
  error.code = code;
  return error;
};

const assignmentFallbackKey = (
  command:
    | AssignmentCommand["command"]
    | undefined,
) => {
  if (command === "create") {
    return "catalogLifecycle.assignments.errors.create";
  }
  if (command === "delete") {
    return "catalogLifecycle.assignments.errors.delete";
  }
  return "catalogLifecycle.assignments.errors.update";
};

const parseAssignmentMutation = (
  raw: unknown,
  *,
  variantId: number,
  locationId: number,
  assignmentId?: number,
): ProductLocationAssignment => {
  parseMutationMessage(raw);
  if (
    raw === null ||
    typeof raw !== "object" ||
    Array.isArray(raw)
  ) {
    throw codedError(
      "CATALOG_CONTRACT_INVALID",
    );
  }

  const item =
    parseProductLocations({
      items: [
        (
          raw as Record<
            string,
            unknown
          >
        ).product_location,
      ],
      next_cursor: null,
      has_more: false,
    }).items[0];

  if (
    item.product_variant.id !==
      variantId ||
    item.location.id !==
      locationId ||
    (
      assignmentId !== undefined &&
      item.id !== assignmentId
    )
  ) {
    throw codedError(
      "CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH",
    );
  }
  return item;
};

const parseAssignmentDelete = (
  raw: unknown,
  *,
  assignmentId: number,
  locationId: number,
) => {
  parseMutationMessage(raw);
  if (
    raw === null ||
    typeof raw !== "object" ||
    Array.isArray(raw)
  ) {
    throw codedError(
      "CATALOG_CONTRACT_INVALID",
    );
  }
  const row =
    raw as Record<string, unknown>;

  if (
    row.product_location_id !==
      assignmentId ||
    (
      row.location_id !== undefined &&
      row.location_id !==
        locationId
    )
  ) {
    throw codedError(
      "CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH",
    );
  }
};

export function CatalogLifecyclePanel({
  variant,
  locations,
  onVariantChanged,
  onVariantDeleted,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const access =
    useInventoryAccess();
  const isOnline =
    useNetworkStatus();

  const [
    assignmentReason,
    setAssignmentReason,
  ] = useState("");
  const [busy, setBusy] =
    useState(false);
  const [
    assignments,
    setAssignments,
  ] = useState<
    ProductLocationAssignment[]
  >([]);
  const [
    assignmentsLoading,
    setAssignmentsLoading,
  ] = useState(false);
  const [
    locationId,
    setLocationId,
  ] = useState("");
  const [
    inboundEnabled,
    setInboundEnabled,
  ] = useState(true);
  const [
    outboundEnabled,
    setOutboundEnabled,
  ] = useState(true);
  const [
    pending,
    setPending,
  ] = useState<
    DurableCommand<AssignmentCommand> | null
  >(null);
  const [
    pendingBlocked,
    setPendingBlocked,
  ] = useState(false);

  const canReadAssignments =
    access.canAny(
      "product_location.read",
    );
  const canManageAssignments =
    access.canAny(
      "product_location.manage",
    );
  const companyId =
    access.data?.company_id ??
    null;
  const driverId =
    access.data?.driver_id ??
    null;
  const assignmentScope =
    companyId !== null &&
    driverId !== null
      ? durableScope(
          companyId,
          driverId,
          "catalog-product-location-command-v1",
          variant.id,
        )
      : null;

  const loadAssignments =
    useCallback(async () => {
      if (!canReadAssignments) {
        setAssignments([]);
        return;
      }

      setAssignmentsLoading(true);
      try {
        const page =
          parseProductLocations(
            await authFetch(
              `/warehouse/product-locations?product_variant_id=${variant.id}&limit=200`,
            ),
          );

        if (page.has_more) {
          throw codedError(
            "CATALOG_PRODUCT_LOCATIONS_LIMIT_EXCEEDED",
          );
        }
        setAssignments(
          page.items,
        );
      } catch (error) {
        setAssignments([]);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "catalogLifecycle.assignments.errors.load",
            ),
          ),
        );
      } finally {
        setAssignmentsLoading(
          false,
        );
      }
    }, [
      authFetch,
      canReadAssignments,
      t,
      variant.id,
    ]);

  useEffect(() => {
    void loadAssignments();
  }, [loadAssignments]);

  useEffect(() => {
    let cancelled = false;
    setPending(null);
    setPendingBlocked(false);

    if (!assignmentScope) {
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const stored =
          await readDurableCommand<unknown>(
            assignmentScope,
          );
        if (
          cancelled ||
          !stored
        ) {
          return;
        }

        if (
          !isAssignmentCommand(
            stored.payload,
          ) ||
          stored.payload
            .product_variant_id !==
            variant.id
        ) {
          setPendingBlocked(true);
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

        if (
          restored.payload
            .command === "delete"
        ) {
          setAssignmentReason(
            restored.payload.reason,
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPendingBlocked(true);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "catalogLifecycle.assignments.errors.pending",
            ),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    assignmentScope,
    variant.id,
    t,
  ]);

  const runAssignmentCommand =
    async (
      fresh:
        AssignmentCommand | null,
    ) => {
      if (
        busy ||
        !assignmentScope ||
        !isOnline ||
        pendingBlocked
      ) {
        return;
      }

      const attempted =
        pending?.payload ??
        fresh ??
        undefined;
      setBusy(true);

      try {
        const durable =
          pending ??
          (
            fresh
              ? await getOrCreateDurableCommand(
                  assignmentScope,
                  fresh,
                )
              : null
          );

        if (
          !durable ||
          !isAssignmentCommand(
            durable.payload,
          ) ||
          durable.payload
            .product_variant_id !==
            variant.id
        ) {
          throw codedError(
            "DURABLE_OPERATION_CORRUPT",
          );
        }

        setPending(durable);
        const payload =
          durable.payload;

        if (
          payload.command ===
          "create"
        ) {
          const raw =
            await authFetch(
              "/warehouse/product-locations",
              {
                method: "POST",
                body: JSON.stringify({
                  request_id:
                    durable.requestId,
                  location_id:
                    payload.location_id,
                  product_variant_id:
                    payload.product_variant_id,
                  operational_flags:
                    payload.operational_flags,
                }),
              },
            );

          parseAssignmentMutation(
            raw,
            {
              variantId:
                variant.id,
              locationId:
                payload.location_id,
            },
          );
        } else if (
          payload.command ===
          "update"
        ) {
          const raw =
            await authFetch(
              `/warehouse/product-locations/${payload.product_location_id}`,
              {
                method: "PATCH",
                body: JSON.stringify({
                  request_id:
                    durable.requestId,
                  expected_version:
                    payload.expected_version,
                  operational_flags:
                    payload.operational_flags,
                }),
              },
            );

          parseAssignmentMutation(
            raw,
            {
              variantId:
                variant.id,
              locationId:
                payload.location_id,
              assignmentId:
                payload.product_location_id,
            },
          );
        } else {
          const raw =
            await authFetch(
              `/warehouse/product-locations/${payload.product_location_id}`,
              {
                method:
                  "DELETE",
                body: JSON.stringify({
                  request_id:
                    durable.requestId,
                  expected_version:
                    payload.expected_version,
                  location_id:
                    payload.location_id,
                  reason:
                    payload.reason,
                }),
              },
            );

          parseAssignmentDelete(
            raw,
            {
              assignmentId:
                payload.product_location_id,
              locationId:
                payload.location_id,
            },
          );
        }

        completeDurableOperation(
          assignmentScope,
          durable.requestId,
        );
        setPending(null);
        setPendingBlocked(false);

        if (
          payload.command ===
          "create"
        ) {
          setLocationId("");
        }
        if (
          payload.command ===
          "delete"
        ) {
          setAssignmentReason("");
        }

        toast.success(
          t(
            `catalogLifecycle.assignments.success.${payload.command}`,
          ),
        );
        await loadAssignments();
      } catch (error) {
        const code =
          apiErrorCode(error);
        const durableConflict =
          code ===
          "DURABLE_OPERATION_PENDING";
        const durableCorrupt =
          code ===
          "DURABLE_OPERATION_CORRUPT";
        const uncertainResponse =
          code ===
            "CATALOG_CONTRACT_INVALID" ||
          code ===
            "CATALOG_PRODUCT_LOCATION_SCOPE_MISMATCH";

        if (durableCorrupt) {
          setPendingBlocked(true);
        }

        if (
          durableConflict &&
          assignmentScope
        ) {
          try {
            const stored =
              await readDurableCommand<unknown>(
                assignmentScope,
              );
            if (
              stored &&
              isAssignmentCommand(
                stored.payload,
              ) &&
              stored.payload
                .product_variant_id ===
                variant.id
            ) {
              setPending({
                requestId:
                  stored.requestId,
                payload:
                  stored.payload,
                createdAt:
                  stored.createdAt,
              });
            }
          } catch {
            setPendingBlocked(true);
          }
        }

        if (
          !durableConflict &&
          !durableCorrupt &&
          !uncertainResponse &&
          !isAmbiguousRequestError(
            error,
          ) &&
          assignmentScope
        ) {
          abandonDurableOperation(
            assignmentScope,
          );
          setPending(null);
        }

        toast.error(
          apiErrorMessage(
            error,
            t(
              assignmentFallbackKey(
                attempted?.command,
              ),
            ),
          ),
        );
      } finally {
        setBusy(false);
      }
    };

  const createAssignment =
    async () => {
      const selected =
        Number(locationId);

      if (
        !Number.isSafeInteger(
          selected,
        ) ||
        selected <= 0
      ) {
        toast.error(
          t(
            "catalogLifecycle.assignments.errors.locationRequired",
          ),
        );
        return;
      }

      await runAssignmentCommand({
        command: "create",
        product_variant_id:
          variant.id,
        location_id: selected,
        operational_flags: {
          inbound_enabled:
            inboundEnabled,
          outbound_enabled:
            outboundEnabled,
        },
      });
    };

  const updateAssignment =
    async (
      assignment:
        ProductLocationAssignment,
      flag:
        | "inbound_enabled"
        | "outbound_enabled",
      value: boolean,
    ) => {
      await runAssignmentCommand({
        command: "update",
        product_variant_id:
          variant.id,
        product_location_id:
          assignment.id,
        location_id:
          assignment.location.id,
        expected_version:
          assignment.version,
        operational_flags: {
          ...assignment.operational_flags,
          [flag]: value,
        },
      });
    };

  const removeAssignment =
    async (
      assignment:
        ProductLocationAssignment,
    ) => {
      const reason =
        assignmentReason.trim();

      if (
        reason.length < 3 ||
        reason.length > 1000
      ) {
        toast.error(
          t(
            "catalogLifecycle.assignments.errors.reason",
          ),
        );
        return;
      }

      await runAssignmentCommand({
        command: "delete",
        product_variant_id:
          variant.id,
        product_location_id:
          assignment.id,
        location_id:
          assignment.location.id,
        expected_version:
          assignment.version,
        reason,
      });
    };

  const assignedIds =
    new Set(
      assignments.map(
        (item) =>
          item.location.id,
      ),
    );
  const availableLocations =
    locations.filter(
      (item) =>
        !assignedIds.has(
          item.id,
        ),
    );
  const mutationDisabled =
    busy ||
    !isOnline ||
    pending !== null ||
    pendingBlocked ||
    assignmentScope === null;

  return (
    <div className="space-y-4">
      <CatalogLifecycleActions
        variant={variant}
        onVariantChanged={
          onVariantChanged
        }
        onVariantDeleted={
          onVariantDeleted
        }
      />

      {canReadAssignments ? (
        <section className="rounded-xl border border-slate-200 p-4">
          <h3 className="font-black text-slate-800">
            <Link2 className="me-1 inline h-4 w-4" />
            {t(
              "catalogLifecycle.assignments.title",
            )}
          </h3>
          <p className="mt-1 text-xs font-bold text-slate-500">
            {t(
              "catalogLifecycle.assignments.description",
            )}
          </p>

          {canManageAssignments &&
          assignments.length >
            0 ? (
            <label className="mt-3 block text-xs font-bold text-slate-600">
              {t(
                "catalogLifecycle.assignments.removeReason",
              )}
              <input
                value={
                  assignmentReason
                }
                maxLength={1000}
                disabled={
                  mutationDisabled
                }
                onChange={(
                  event,
                ) =>
                  setAssignmentReason(
                    event.target
                      .value,
                  )
                }
                placeholder={t(
                  "catalogLifecycle.assignments.removeReasonPlaceholder",
                )}
                className="mt-1 w-full rounded-lg border p-2 disabled:bg-slate-50"
              />
            </label>
          ) : null}

          {pending ? (
            <div className="mt-3 rounded-xl bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
              <p>
                {t(
                  "catalogLifecycle.assignments.pendingRetry",
                  {
                    action: t(
                      `catalogLifecycle.assignments.actions.${pending.payload.command}`,
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
                  void runAssignmentCommand(
                    null,
                  )
                }
                className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-black text-amber-900 disabled:opacity-40"
              >
                {t(
                  "catalogLifecycle.assignments.retryPending",
                )}
              </button>
            </div>
          ) : null}

          {pendingBlocked ? (
            <p className="mt-3 rounded-xl bg-rose-50 p-3 text-xs font-bold leading-6 text-rose-800">
              {t(
                "catalogLifecycle.assignments.pendingBlocked",
              )}
            </p>
          ) : null}

          <div className="mt-3 space-y-2">
            {assignmentsLoading ? (
              <p className="text-xs text-slate-400">
                {t(
                  "catalogLifecycle.assignments.loading",
                )}
              </p>
            ) : null}

            {!assignmentsLoading &&
            assignments.length ===
              0 ? (
              <p className="text-xs text-slate-400">
                {t(
                  "catalogLifecycle.assignments.empty",
                )}
              </p>
            ) : null}

            {assignments.map(
              (assignment) => (
                <div
                  key={
                    assignment.id
                  }
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 p-3 text-xs font-bold"
                >
                  <span>
                    {
                      assignment
                        .location
                        .name
                    }{" "}
                    <span className="font-mono text-slate-400">
                      {
                        assignment
                          .location
                          .code
                      }
                    </span>
                  </span>
                  <div className="flex items-center gap-3">
                    <label>
                      <input
                        type="checkbox"
                        checked={
                          assignment
                            .operational_flags
                            .inbound_enabled
                        }
                        disabled={
                          mutationDisabled ||
                          !canManageAssignments
                        }
                        onChange={(
                          event,
                        ) =>
                          void updateAssignment(
                            assignment,
                            "inbound_enabled",
                            event
                              .target
                              .checked,
                          )
                        }
                      />{" "}
                      {t(
                        "catalogLifecycle.assignments.inbound",
                      )}
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={
                          assignment
                            .operational_flags
                            .outbound_enabled
                        }
                        disabled={
                          mutationDisabled ||
                          !canManageAssignments
                        }
                        onChange={(
                          event,
                        ) =>
                          void updateAssignment(
                            assignment,
                            "outbound_enabled",
                            event
                              .target
                              .checked,
                          )
                        }
                      />{" "}
                      {t(
                        "catalogLifecycle.assignments.outbound",
                      )}
                    </label>
                    {canManageAssignments ? (
                      <button
                        type="button"
                        aria-label={t(
                          "catalogLifecycle.assignments.remove",
                        )}
                        disabled={
                          mutationDisabled
                        }
                        className="text-red-600 disabled:opacity-40"
                        onClick={() =>
                          void removeAssignment(
                            assignment,
                          )
                        }
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    ) : null}
                  </div>
                </div>
              ),
            )}
          </div>

          {canManageAssignments &&
          variant.lifecycle_status ===
            "ACTIVE" &&
          availableLocations.length >
            0 ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
              <select
                value={locationId}
                disabled={
                  mutationDisabled
                }
                onChange={(
                  event,
                ) =>
                  setLocationId(
                    event.target
                      .value,
                  )
                }
                className="rounded-lg border p-2 text-xs font-bold disabled:bg-slate-50"
              >
                <option value="">
                  {t(
                    "catalogLifecycle.assignments.chooseLocation",
                  )}
                </option>
                {availableLocations.map(
                  (location) => (
                    <option
                      key={
                        location.id
                      }
                      value={
                        location.id
                      }
                    >
                      {
                        location.code
                      }{" "}
                      —{" "}
                      {
                        location.name
                      }
                    </option>
                  ),
                )}
              </select>
              <label className="self-center text-xs font-bold">
                <input
                  type="checkbox"
                  checked={
                    inboundEnabled
                  }
                  disabled={
                    mutationDisabled
                  }
                  onChange={(
                    event,
                  ) =>
                    setInboundEnabled(
                      event.target
                        .checked,
                    )
                  }
                />{" "}
                {t(
                  "catalogLifecycle.assignments.inbound",
                )}
              </label>
              <label className="self-center text-xs font-bold">
                <input
                  type="checkbox"
                  checked={
                    outboundEnabled
                  }
                  disabled={
                    mutationDisabled
                  }
                  onChange={(
                    event,
                  ) =>
                    setOutboundEnabled(
                      event.target
                        .checked,
                    )
                  }
                />{" "}
                {t(
                  "catalogLifecycle.assignments.outbound",
                )}
              </label>
              <button
                type="button"
                disabled={
                  mutationDisabled ||
                  !locationId
                }
                onClick={() =>
                  void createAssignment()
                }
                className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-black text-white disabled:opacity-40"
              >
                {t(
                  "catalogLifecycle.assignments.link",
                )}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
