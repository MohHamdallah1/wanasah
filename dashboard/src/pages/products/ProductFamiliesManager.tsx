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
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableRequestId,
} from "@/lib/durableOperations";
import {
  parseProductFamilies,
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
    editingFamily,
    setEditingFamily,
  ] = useState<ProductFamily | null>(
    null
  );
  const [
    editingFamilyName,
    setEditingFamilyName,
  ] = useState("");

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
    setEditingFamily(null);
    setEditingFamilyName("");
  }, [companyId]);

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

          const body = {
            name,
          };
          const scope =
            operationScope(
              "family-create"
            );
          const requestId =
            await getOrCreateDurableRequestId(
              scope,
              body
            );
          await authFetch(
            "/simple-products/families",
            {
              method: "POST",
              body: JSON.stringify(
                {
                  request_id:
                    requestId,
                  ...body,
                }
              ),
            }
          );
          return {
            requestId,
            scope,
          };
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

          const body = {
            expected_version:
              editingFamily.version,
            name:
              editingFamilyName.trim(),
          };
          const scope =
            operationScope(
              "family-rename",
              editingFamily.id
            );
          const requestId =
            await getOrCreateDurableRequestId(
              scope,
              body
            );
          await authFetch(
            `/simple-products/families/${editingFamily.id}`,
            {
              method: "PATCH",
              body: JSON.stringify(
                {
                  request_id:
                    requestId,
                  ...body,
                }
              ),
            }
          );
          return {
            requestId,
            scope,
          };
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
                      onClick={() => {
                        setEditingFamily(
                          family
                        );
                        setEditingFamilyName(
                          family.name
                        );
                      }}
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
