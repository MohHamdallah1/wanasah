import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
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
  parseProductFamilies,
  parseProductFamilyReassignMutation,
  type ProductFamilyReassignMutationResponse,
  type SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  companyId: number | null;
  driverId: number | null;
  onClose: () => void;
  onReassigned: (
    result: ProductFamilyReassignMutationResponse,
  ) => void | Promise<void>;
};

type FamilyReassignPayload = {
  expected_version: number;
  family_id: number;
};

const validFamilyReassignPayload = (
  value: unknown,
): value is FamilyReassignPayload => {
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
  return (
    Object.keys(row).length === 2 &&
    typeof row.expected_version ===
      "number" &&
    Number.isSafeInteger(
      row.expected_version
    ) &&
    row.expected_version > 0 &&
    typeof row.family_id === "number" &&
    Number.isSafeInteger(row.family_id) &&
    row.family_id > 0
  );
};

const codedError = (
  code: string,
): Error & { code: string } => {
  const error = new Error(code) as Error & {
    code: string;
  };
  error.code = code;
  return error;
};

const retainPendingReassign = (
  error: unknown,
): boolean => {
  const code = apiErrorCode(error);
  return (
    isAmbiguousRequestError(error) ||
    code === "DURABLE_OPERATION_PENDING" ||
    code === "DURABLE_OPERATION_CORRUPT" ||
    code ===
      "PRODUCT_FAMILY_REASSIGN_RESPONSE_INVALID" ||
    code ===
      "PRODUCT_FAMILY_REASSIGN_SCOPE_MISMATCH"
  );
};

export function ProductFamilyReassignDialog({
  product,
  companyId,
  driverId,
  onClose,
  onReassigned,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const queryClient =
    useQueryClient();
  const isOnline =
    useNetworkStatus();

  const [
    searchInput,
    setSearchInput,
  ] = useState("");
  const [
    search,
    setSearch,
  ] = useState("");
  const [
    targetFamilyId,
    setTargetFamilyId,
  ] = useState<number | null>(
    null
  );
  const [
    expectedVersion,
    setExpectedVersion,
  ] = useState<number | null>(
    null
  );
  const [
    pending,
    setPending,
  ] = useState<
    DurableCommand<FamilyReassignPayload> | null
  >(null);
  const [
    pendingBlocked,
    setPendingBlocked,
  ] = useState(false);
  const [
    busy,
    setBusy,
  ] = useState(false);
  const [
    fieldError,
    setFieldError,
  ] = useState<string | null>(
    null
  );

  const scope = useMemo(() => {
    if (
      product === null ||
      companyId === null ||
      driverId === null
    ) {
      return null;
    }
    return durableScope(
      companyId,
      driverId,
      "catalog-product-family-reassign-v1",
      product.id,
    );
  }, [
    companyId,
    driverId,
    product,
  ]);

  useEffect(() => {
    if (!product) {
      setSearchInput("");
      setSearch("");
      setTargetFamilyId(null);
      setExpectedVersion(null);
      setPending(null);
      setPendingBlocked(false);
      setBusy(false);
      setFieldError(null);
      return;
    }

    setSearchInput("");
    setSearch("");
    setTargetFamilyId(null);
    setExpectedVersion(
      product.version
    );
    setPending(null);
    setPendingBlocked(false);
    setBusy(false);
    setFieldError(null);
  }, [
    product,
  ]);

  useEffect(() => {
    if (!product) {
      return;
    }

    const next =
      searchInput.trim();
    if (next === search) {
      return;
    }

    const timer =
      window.setTimeout(() => {
        setSearch(next);
        if (!pending) {
          setTargetFamilyId(null);
        }
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [
    pending,
    product,
    search,
    searchInput,
  ]);

  useEffect(() => {
    if (
      !product ||
      !scope
    ) {
      return;
    }

    let cancelled = false;
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
          !validFamilyReassignPayload(
            stored.payload,
          )
        ) {
          throw codedError(
            "DURABLE_OPERATION_CORRUPT",
          );
        }
        setPending({
          requestId:
            stored.requestId,
          payload:
            stored.payload,
          createdAt:
            stored.createdAt,
        });
        setExpectedVersion(
          stored.payload
            .expected_version,
        );
        setTargetFamilyId(
          stored.payload.family_id,
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
              "products.familyReassign.errors.saveFailed"
            ),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    product,
    scope,
    t,
  ]);

  const familyParams =
    useMemo(() => {
      const params =
        new URLSearchParams({
          limit: "50",
        });
      if (search) {
        params.set(
          "search",
          search
        );
      }
      return params.toString();
    }, [
      search,
    ]);

  const familiesQuery =
    useQuery({
      queryKey: [
        "simple-product-families",
        companyId,
        "reassign",
        search,
      ],
      enabled: Boolean(
        product &&
        companyId
      ),
      queryFn: async ({
        signal,
      }) =>
        parseProductFamilies(
          await authFetch(
            `/simple-products/families?${familyParams}`,
            { signal },
          ),
        ),
      staleTime: 30_000,
    });

  if (!product) {
    return null;
  }

  const families =
    familiesQuery.data
      ?.items ?? [];
  const selectableFamilies =
    families.filter(
      (family) =>
        family.id !==
        product.product_id
    );
  const pendingTargetVisible =
    targetFamilyId !== null &&
    !selectableFamilies.some(
      (family) =>
        family.id ===
        targetFamilyId
    );

  const save = async () => {
    if (
      busy ||
      !scope ||
      !isOnline ||
      pendingBlocked
    ) {
      return;
    }

    if (
      !pending &&
      targetFamilyId === null
    ) {
      setFieldError(
        t(
          "products.familyReassign.errors.targetRequired"
        )
      );
      return;
    }

    const payload:
      FamilyReassignPayload = {
        expected_version:
          expectedVersion ??
          product.version,
        family_id:
          pending?.payload
            .family_id ??
          targetFamilyId ??
          product.product_id,
      };

    if (
      !pending &&
      payload.family_id ===
        product.product_id
    ) {
      setFieldError(
        t(
          "products.familyReassign.errors.unchanged"
        )
      );
      return;
    }

    setBusy(true);
    try {
      const command =
        pending ??
        (await getOrCreateDurableCommand(
          scope,
          payload,
        ));
      setPending(command);

      const result =
        parseProductFamilyReassignMutation(
          await authFetch(
            `/catalog/variants/${product.id}/family`,
            {
              method: "PATCH",
              body: JSON.stringify({
                request_id:
                  command.requestId,
                ...command.payload,
              }),
            },
          ),
        );

      if (
        result.product_variant_id !==
        product.id
      ) {
        throw codedError(
          "PRODUCT_FAMILY_REASSIGN_SCOPE_MISMATCH",
        );
      }

      completeDurableOperation(
        scope,
        command.requestId,
      );
      setPending(null);
      setPendingBlocked(false);
      setFieldError(null);

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

      toast.success(
        t(
          "products.familyReassign.saved"
        )
      );
      await onReassigned(result);
    } catch (error) {
      const code =
        apiErrorCode(error);
      if (
        code ===
        "DURABLE_OPERATION_CORRUPT"
      ) {
        setPendingBlocked(true);
      }

      if (
        !retainPendingReassign(
          error
        )
      ) {
        abandonDurableOperation(
          scope
        );
        setPending(null);
        setPendingBlocked(false);
      }

      if (
        code ===
        "VARIANT_VERSION_CONFLICT"
      ) {
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-products",
            ],
          }
        );
      }

      toast.error(
        apiErrorMessage(
          error,
          t(
            code ===
              "PRODUCT_FAMILY_REASSIGN_HISTORY_LOCKED"
              ? "products.familyReassign.errors.historyLocked"
              : code ===
                  "PRODUCT_FAMILY_REASSIGN_LIFECYCLE_BLOCKED"
                ? "products.familyReassign.errors.lifecycleLocked"
                : "products.familyReassign.errors.saveFailed"
          ),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const fieldsLocked =
    busy ||
    pending !== null ||
    pendingBlocked;

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => {
        if (!busy) {
          onClose();
        }
      }}
      title={t(
        "products.familyReassign.title"
      )}
      maxWidth="max-w-lg"
      footer={
        <>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="px-4 py-2 text-sm font-bold text-slate-600 disabled:opacity-40"
          >
            {t(
              "common.cancel"
            )}
          </button>
          <button
            type="button"
            disabled={
              busy ||
              !isOnline ||
              pendingBlocked ||
              (!pending &&
                targetFamilyId ===
                  null)
            }
            onClick={() =>
              void save()
            }
            className="rounded-xl bg-slate-950 px-5 py-2.5 text-sm font-black text-white disabled:opacity-40"
          >
            {pending
              ? t(
                  "products.familyReassign.retry"
                )
              : t(
                  "products.familyReassign.save"
                )}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="rounded-2xl bg-slate-50 p-3 text-xs font-bold leading-6 text-slate-600">
          {t(
            "products.familyReassign.description"
          )}
        </p>

        <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs">
          <span className="font-bold text-slate-500">
            {t(
              "products.familyReassign.current"
            )}
          </span>
          <strong className="ms-2 text-slate-900">
            {product.family_name}
          </strong>
        </div>

        <label className="block text-xs font-black text-slate-600">
          {t(
            "products.familyReassign.search"
          )}
          <input
            type="search"
            value={searchInput}
            maxLength={100}
            disabled={fieldsLocked}
            onChange={(event) =>
              setSearchInput(
                event.target.value
              )
            }
            placeholder={t(
              "products.familyReassign.searchPlaceholder"
            )}
            className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold outline-none disabled:opacity-50"
          />
        </label>

        <label className="block text-xs font-black text-slate-600">
          {t(
            "products.familyReassign.target"
          )}
          <select
            value={
              targetFamilyId ??
              ""
            }
            disabled={
              fieldsLocked ||
              familiesQuery.isLoading
            }
            onChange={(event) => {
              const value =
                Number(
                  event.target.value
                );
              setTargetFamilyId(
                Number.isSafeInteger(
                  value
                ) &&
                value > 0
                  ? value
                  : null
              );
              if (fieldError) {
                setFieldError(null);
              }
            }}
            aria-invalid={
              fieldError
                ? "true"
                : undefined
            }
            aria-describedby={
              fieldError
                ? "product-family-reassign-error"
                : undefined
            }
            className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold outline-none disabled:opacity-50"
          >
            <option value="">
              {t(
                familiesQuery.isLoading
                  ? "common.loading"
                  : "products.familyReassign.targetPlaceholder"
              )}
            </option>
            {pendingTargetVisible ? (
              <option
                value={
                  targetFamilyId ??
                  ""
                }
              >
                {t(
                  "products.familyReassign.pendingTarget",
                  {
                    id:
                      targetFamilyId,
                  }
                )}
              </option>
            ) : null}
            {selectableFamilies.map(
              (family) => (
                <option
                  key={
                    family.id
                  }
                  value={
                    family.id
                  }
                >
                  {family.name}
                </option>
              )
            )}
          </select>
        </label>

        {familiesQuery.isError ? (
          <button
            type="button"
            onClick={() =>
              void familiesQuery.refetch()
            }
            className="text-xs font-black text-rose-700"
          >
            {t(
              "products.errors.familiesLoad"
            )}{" "}
            {t(
              "common.retry"
            )}
          </button>
        ) : null}

        {fieldError ? (
          <p
            id="product-family-reassign-error"
            role="alert"
            className="text-xs font-bold text-rose-700"
          >
            {fieldError}
          </p>
        ) : null}

        <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
          {t(
            "products.familyReassign.historyHint"
          )}
        </p>

        {pending ? (
          <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
            {t(
              "products.familyReassign.pendingRetry"
            )}
          </p>
        ) : pendingBlocked ? (
          <p className="rounded-xl bg-rose-50 p-3 text-[11px] font-semibold leading-5 text-rose-900">
            {t(
              "products.familyReassign.pendingBlocked"
            )}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
