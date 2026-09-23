import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Search } from "lucide-react";
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
} from "@/lib/durableOperations";
import {
  parseProductFamilies,
  parseProductFamilyMutation,
  type ProductFamily,
} from "@/pages/products/contracts";

type Props = {
  isOpen: boolean;
  companyId: number | null;
  driverId: number | null;
  onClose: () => void;
};

type MutationResult = {
  requestId: string;
  scope: string;
};

type FamilyCreateCommandPayload = {
  name: string;
};

type FamilyRenameCommandPayload = {
  expected_version: number;
  name: string;
};

const localCodedError = (
  code: string,
): Error & { code: string } => {
  const error = new Error() as Error & {
    code: string;
  };
  error.code = code;
  return error;
};

const validFamilyCreatePayload = (
  value: unknown,
): value is FamilyCreateCommandPayload => {
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
    Object.keys(row).length === 1 &&
    typeof row.name === "string" &&
    row.name.trim().length > 0 &&
    row.name.trim().length <= 150
  );
};

const validFamilyRenamePayload = (
  value: unknown,
): value is FamilyRenameCommandPayload => {
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
    typeof row.name === "string" &&
    row.name.trim().length > 0 &&
    row.name.trim().length <= 150 &&
    typeof row.expected_version ===
      "number" &&
    Number.isSafeInteger(
      row.expected_version
    ) &&
    row.expected_version > 0
  );
};

const shouldRetainDurableFamilyCommand = (
  error: unknown,
): boolean => {
  const code =
    apiErrorCode(error);
  return (
    isAmbiguousRequestError(error) ||
    code ===
      "DURABLE_OPERATION_PENDING" ||
    code ===
      "DURABLE_OPERATION_CORRUPT" ||
    code ===
      "PRODUCT_FAMILY_MUTATION_RESPONSE_INVALID"
  );
};

export function ProductFamiliesManager({
  isOpen,
  companyId,
  driverId,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const authFetch =
    useAuthFetch();
  const isOnline =
    useNetworkStatus();
  const queryClient =
    useQueryClient();

  const [
    searchInput,
    setSearchInput,
  ] = useState("");
  const [
    search,
    setSearch,
  ] = useState("");
  const [
    cursor,
    setCursor,
  ] = useState<string | null>(
    null
  );
  const [
    history,
    setHistory,
  ] = useState<
    Array<string | null>
  >([]);
  const [
    newFamilyName,
    setNewFamilyName,
  ] = useState("");
  const [
    createCommandPending,
    setCreateCommandPending,
  ] = useState(false);
  const [
    createCommandBlocked,
    setCreateCommandBlocked,
  ] = useState(false);
  const [
    editingFamily,
    setEditingFamily,
  ] = useState<ProductFamily | null>(
    null
  );
  const [
    editingFamilyName,
    setEditingFamilyName,
  ] = useState("");
  const [
    editingExpectedVersion,
    setEditingExpectedVersion,
  ] = useState<number | null>(
    null
  );
  const [
    renameCommandPending,
    setRenameCommandPending,
  ] = useState(false);
  const [
    renameCommandBlocked,
    setRenameCommandBlocked,
  ] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const timer =
      window.setTimeout(() => {
        setSearch(
          searchInput.trim()
        );
        setCursor(null);
        setHistory([]);
        setEditingFamily(null);
        setEditingFamilyName("");
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [
    isOpen,
    searchInput,
  ]);

  useEffect(() => {
    setSearchInput("");
    setSearch("");
    setCursor(null);
    setHistory([]);
    setNewFamilyName("");
    setCreateCommandPending(false);
    setCreateCommandBlocked(false);
    setEditingFamily(null);
    setEditingFamilyName("");
    setEditingExpectedVersion(null);
    setRenameCommandPending(false);
    setRenameCommandBlocked(false);
  }, [companyId]);

  useEffect(() => {
    if (
      !isOpen ||
      !companyId ||
      !driverId
    ) {
      return;
    }

    let cancelled = false;
    const scope = durableScope(
      companyId,
      driverId,
      "family-create",
    );

    void (async () => {
      try {
        const command =
          await readDurableCommand<unknown>(
            scope,
          );
        if (cancelled || !command) {
          return;
        }
        if (
          !validFamilyCreatePayload(
            command.payload,
          )
        ) {
          throw localCodedError(
            "DURABLE_OPERATION_CORRUPT",
          );
        }
        setNewFamilyName(
          command.payload.name,
        );
        setCreateCommandPending(
          true,
        );
        setCreateCommandBlocked(
          false,
        );
      } catch (error) {
        if (cancelled) {
          return;
        }
        setCreateCommandPending(false);
        setCreateCommandBlocked(true);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.familyFailed",
            ),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    isOpen,
    companyId,
    driverId,
    t,
  ]);

  const params = useMemo(
    () => {
      const value =
        new URLSearchParams({
          limit: "50",
        });
      if (search) {
        value.set(
          "search",
          search
        );
      }
      if (cursor) {
        value.set(
          "cursor",
          cursor
        );
      }
      return value.toString();
    },
    [
      search,
      cursor,
    ]
  );

  const familiesQuery =
    useQuery({
      queryKey: [
        "simple-product-families",
        companyId,
        "manager",
        search,
        cursor,
      ],
      enabled: Boolean(
        isOpen &&
        companyId
      ),
      queryFn: async ({
        signal,
      }) =>
        parseProductFamilies(
          await authFetch(
            `/simple-products/families?${params}`,
            { signal }
          )
        ),
    });

  const operationScope = (
    operation: string,
    target:
      | string
      | number = "default"
  ) => {
    if (
      !companyId ||
      !driverId
    ) {
      throw new Error(
        "IDENTITY_NOT_READY"
      );
    }
    return durableScope(
      companyId,
      driverId,
      operation,
      target
    );
  };

  const createFamilyMutation =
    useMutation({
      mutationFn:
        async (): Promise<MutationResult> => {
          const name =
            newFamilyName.trim();
          if (!name) {
            throw new Error(
              t(
                "products.newFamilyPlaceholder"
              )
            );
          }

          const body:
            FamilyCreateCommandPayload = {
              name,
            };
          const scope =
            operationScope(
              "family-create"
            );
          try {
            const command =
              await getOrCreateDurableCommand(
                scope,
                body
              );
            parseProductFamilyMutation(
              await authFetch(
                "/simple-products/families",
                {
                  method: "POST",
                  body: JSON.stringify(
                    {
                      request_id:
                        command.requestId,
                      ...command.payload,
                    }
                  ),
                }
              )
            );
            return {
              requestId:
                command.requestId,
              scope,
            };
          } catch (error) {
            if (
              shouldRetainDurableFamilyCommand(
                error
              )
            ) {
              setCreateCommandPending(
                true
              );
            } else {
              abandonDurableOperation(
                scope
              );
              setCreateCommandPending(
                false
              );
              setCreateCommandBlocked(
                false
              );
            }
            throw error;
          }
        },
      onSuccess: async ({
        requestId,
        scope,
      }) => {
        completeDurableOperation(
          scope,
          requestId
        );
        setNewFamilyName("");
        setCreateCommandPending(false);
        setCreateCommandBlocked(false);
        setCursor(null);
        setHistory([]);
        toast.success(
          t(
            "products.familyCreated"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-product-families",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.familyFailed"
            )
          )
        ),
    });

  const updateFamilyMutation =
    useMutation({
      mutationFn:
        async (): Promise<
          MutationResult | undefined
        > => {
          if (
            !editingFamily ||
            !editingFamilyName.trim()
          ) {
            return undefined;
          }

          const body:
            FamilyRenameCommandPayload = {
              expected_version:
                editingExpectedVersion ??
                editingFamily.version,
              name:
                editingFamilyName.trim(),
            };
          const scope =
            operationScope(
              "family-rename",
              editingFamily.id
            );
          try {
            const command =
              await getOrCreateDurableCommand(
                scope,
                body
              );
            parseProductFamilyMutation(
              await authFetch(
                `/simple-products/families/${editingFamily.id}`,
                {
                  method: "PATCH",
                  body: JSON.stringify(
                    {
                      request_id:
                        command.requestId,
                      ...command.payload,
                    }
                  ),
                }
              )
            );
            return {
              requestId:
                command.requestId,
              scope,
            };
          } catch (error) {
            if (
              shouldRetainDurableFamilyCommand(
                error
              )
            ) {
              setRenameCommandPending(
                true
              );
            } else {
              abandonDurableOperation(
                scope
              );
              setRenameCommandPending(
                false
              );
              setRenameCommandBlocked(
                false
              );
            }
            throw error;
          }
        },
      onSuccess: async (
        completed
      ) => {
        if (completed) {
          completeDurableOperation(
            completed.scope,
            completed.requestId
          );
        }
        setEditingFamily(null);
        setEditingFamilyName("");
        setEditingExpectedVersion(null);
        setRenameCommandPending(false);
        setRenameCommandBlocked(false);
        setCursor(null);
        setHistory([]);
        toast.success(
          t(
            "products.familyUpdated"
          )
        );
        await queryClient.invalidateQueries(
          {
            queryKey: [
              "simple-product-families",
            ],
          }
        );
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.familyFailed"
            )
          )
        ),
    });

  const families =
    familiesQuery.data
      ?.items ?? [];

  const openFamilyEditor =
    async (
      family: ProductFamily,
    ) => {
      setEditingFamily(family);
      setEditingFamilyName(
        family.name,
      );
      setEditingExpectedVersion(
        family.version,
      );
      setRenameCommandPending(false);
      setRenameCommandBlocked(false);

      if (
        !companyId ||
        !driverId
      ) {
        setRenameCommandBlocked(true);
        return;
      }

      const scope = durableScope(
        companyId,
        driverId,
        "family-rename",
        family.id,
      );
      try {
        const command =
          await readDurableCommand<unknown>(
            scope,
          );
        if (!command) {
          return;
        }
        if (
          !validFamilyRenamePayload(
            command.payload,
          )
        ) {
          throw localCodedError(
            "DURABLE_OPERATION_CORRUPT",
          );
        }
        setEditingFamilyName(
          command.payload.name,
        );
        setEditingExpectedVersion(
          command.payload
            .expected_version,
        );
        setRenameCommandPending(true);
      } catch (error) {
        setRenameCommandBlocked(true);
        setEditingExpectedVersion(null);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.errors.familyFailed",
            ),
          ),
        );
      }
    };

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        if (
          !createFamilyMutation.isPending &&
          !updateFamilyMutation.isPending
        ) {
          onClose();
        }
      }}
      title={t(
        "products.familiesTitle"
      )}
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4">
        <p className="rounded-2xl bg-slate-50 p-3 text-xs font-bold leading-6 text-slate-600">
          {t(
            "products.familiesDescription"
          )}
        </p>

        <div className="relative">
          <Search className="absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={searchInput}
            maxLength={100}
            onChange={(
              event
            ) =>
              setSearchInput(
                event.target.value
              )
            }
            placeholder={t(
              "products.familySearchPlaceholder"
            )}
            className="w-full rounded-xl border border-slate-200 py-2.5 pe-10 ps-3 text-sm font-bold outline-none"
          />
        </div>

        <div className="flex gap-2">
          <input
            value={
              newFamilyName
            }
            maxLength={150}
            disabled={
              createCommandPending ||
              createCommandBlocked
            }
            onChange={(
              event
            ) =>
              setNewFamilyName(
                event.target.value
              )
            }
            placeholder={t(
              "products.newFamilyPlaceholder"
            )}
            className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-bold"
          />
          <button
            type="button"
            disabled={
              createFamilyMutation.isPending ||
              createCommandBlocked ||
              !isOnline
            }
            onClick={() =>
              createFamilyMutation.mutate()
            }
            className="rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-black text-white disabled:opacity-40"
          >
            {t(
              "products.addFamily"
            )}
          </button>
        </div>

        {createCommandPending ? (
          <p className="rounded-xl bg-amber-50 p-3 text-[11px] font-semibold leading-5 text-amber-900">
            {t(
              "products.familyPendingRetry"
            )}
          </p>
        ) : createCommandBlocked ? (
          <p className="rounded-xl bg-rose-50 p-3 text-[11px] font-semibold leading-5 text-rose-900">
            {t(
              "products.familyPendingBlocked"
            )}
          </p>
        ) : null}

        <div className="max-h-[420px] overflow-auto rounded-2xl border border-slate-200">
          {familiesQuery.isLoading ? (
            <p className="p-8 text-center text-xs font-bold text-slate-400">
              {t(
                "common.loading"
              )}
            </p>
          ) : familiesQuery.isError ? (
            <div className="p-6 text-center">
              <p className="text-xs font-black text-rose-800">
                {t(
                  "products.errors.familiesLoad"
                )}
              </p>
              <button
                type="button"
                onClick={() =>
                  void familiesQuery.refetch()
                }
                className="mt-3 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-700"
              >
                {t(
                  "common.retry"
                )}
              </button>
            </div>
          ) : !families.length ? (
            <p className="p-8 text-center text-xs font-bold text-slate-400">
              {t(
                search
                  ? "products.noMatchingFamilies"
                  : "products.noFamilies"
              )}
            </p>
          ) : (
            families.map(
              (family) => (
                <div
                  key={
                    family.id
                  }
                  className="flex items-center gap-3 border-b border-slate-100 p-3 last:border-b-0"
                >
                  {editingFamily?.id ===
                  family.id ? (
                    <input
                      autoFocus
                      value={
                        editingFamilyName
                      }
                      maxLength={150}
                      disabled={
                        renameCommandPending ||
                        renameCommandBlocked
                      }
                      onChange={(
                        event
                      ) =>
                        setEditingFamilyName(
                          event
                            .target
                            .value
                        )
                      }
                      className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm font-bold"
                    />
                  ) : (
                    <div className="min-w-0 flex-1">
                      <strong className="block truncate text-sm text-slate-900">
                        {
                          family.name
                        }
                      </strong>
                      <span className="text-[10px] font-bold text-slate-400">
                        {t(
                          "products.variantCount",
                          {
                            count:
                              family.variant_count,
                          }
                        )}
                      </span>
                    </div>
                  )}

                  {editingFamily?.id ===
                  family.id ? (
                    <>
                      <button
                        type="button"
                        disabled={
                          updateFamilyMutation.isPending ||
                          renameCommandBlocked ||
                          !isOnline
                        }
                        onClick={() =>
                          updateFamilyMutation.mutate()
                        }
                        className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-black text-white disabled:opacity-40"
                      >
                        {t(
                          "common.save"
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditingFamily(
                            null
                          );
                          setEditingFamilyName(
                            ""
                          );
                          setEditingExpectedVersion(
                            null
                          );
                          setRenameCommandPending(
                            false
                          );
                          setRenameCommandBlocked(
                            false
                          );
                        }}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-black text-slate-600"
                      >
                        {t(
                          "common.cancel"
                        )}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        void openFamilyEditor(
                          family
                        )
                      }
                      className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-black text-slate-600"
                    >
                      {t(
                        "common.edit"
                      )}
                    </button>
                  )}
                </div>
              )
            )
          )}
        </div>

        {history.length > 0 ||
        familiesQuery.data
          ?.next_cursor ? (
          <div className="flex justify-end gap-2">
            <button
              type="button"
              disabled={
                !history.length ||
                familiesQuery.isFetching
              }
              onClick={() => {
                const previous =
                  history.at(
                    -1
                  ) ?? null;
                setHistory(
                  (current) =>
                    current.slice(
                      0,
                      -1
                    )
                );
                setCursor(
                  previous
                );
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black disabled:opacity-30"
            >
              {t(
                "products.familyPrevious"
              )}
            </button>
            <button
              type="button"
              disabled={
                !familiesQuery.data
                  ?.next_cursor ||
                familiesQuery.isFetching
              }
              onClick={() => {
                const next =
                  familiesQuery.data
                    ?.next_cursor;
                if (!next) {
                  return;
                }
                setHistory(
                  (current) => [
                    ...current,
                    cursor,
                  ]
                );
                setCursor(
                  next
                );
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black disabled:opacity-30"
            >
              {t(
                "products.familyNext"
              )}
            </button>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
