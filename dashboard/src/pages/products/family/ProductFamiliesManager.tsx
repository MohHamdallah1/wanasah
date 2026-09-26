import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  useMutation,
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
} from "@/lib/durableOperations";
import {
  parseProductFamilies,
  parseProductFamilyMutation,
  type ProductFamily,
} from "@/pages/products/contracts";
import { ProductFamiliesList } from "@/pages/products/family/ProductFamiliesList";
import { ProductFamiliesToolbar } from "@/pages/products/family/ProductFamiliesToolbar";

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
    newFamilyError,
    setNewFamilyError,
  ] = useState<string | null>(null);
  const newFamilyRef =
    useRef<HTMLInputElement | null>(
      null
    );
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

    const nextSearch =
      searchInput.trim();
    if (nextSearch === search) {
      return;
    }

    const timer =
      window.setTimeout(() => {
        setSearch(nextSearch);
        setCursor(null);
        setHistory([]);
        setEditingFamily(null);
        setEditingFamilyName("");
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [
    isOpen,
    search,
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
            const code =
              apiErrorCode(error);
            if (
              code ===
              "DURABLE_OPERATION_CORRUPT"
            ) {
              setCreateCommandPending(
                false
              );
              setCreateCommandBlocked(
                true
              );
            } else if (
              code ===
              "DURABLE_OPERATION_PENDING"
            ) {
              // A legacy request-only record may still be recoverable
              // by re-entering its exact original payload.
            } else if (
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
        setNewFamilyError(null);
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

  const submitNewFamily = () => {
    if (!newFamilyName.trim()) {
      setNewFamilyError(
        t(
          "products.newFamilyPlaceholder"
        )
      );
      window.requestAnimationFrame(
        () =>
          newFamilyRef.current?.focus()
      );
      return;
    }
    setNewFamilyError(null);
    createFamilyMutation.mutate();
  };

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
            const code =
              apiErrorCode(error);
            if (
              code ===
              "DURABLE_OPERATION_CORRUPT"
            ) {
              setRenameCommandPending(
                false
              );
              setRenameCommandBlocked(
                true
              );
            } else if (
              code ===
              "DURABLE_OPERATION_PENDING"
            ) {
              // Keep the editor usable so a legacy request-only
              // record can be matched by its exact original payload.
            } else if (
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

  const cancelFamilyEditor = () => {
    setEditingFamily(null);
    setEditingFamilyName("");
    setEditingExpectedVersion(null);
    setRenameCommandPending(false);
    setRenameCommandBlocked(false);
  };

  const goToPreviousFamilyPage = () => {
    const previous =
      history.at(-1) ?? null;
    setHistory((current) =>
      current.slice(0, -1)
    );
    setCursor(previous);
  };

  const goToNextFamilyPage = () => {
    const next =
      familiesQuery.data
        ?.next_cursor;
    if (!next) {
      return;
    }
    setHistory((current) => [
      ...current,
      cursor,
    ]);
    setCursor(next);
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
      subtitle={t(
        "products.familiesDescription"
      )}
      maxWidth="max-w-4xl"
      bodyClassName="p-0"
    >
      <div className="min-h-0 bg-white">
        <ProductFamiliesToolbar
          searchInput={searchInput}
          newFamilyName={
            newFamilyName
          }
          newFamilyError={
            newFamilyError
          }
          createCommandPending={
            createCommandPending
          }
          createCommandBlocked={
            createCommandBlocked
          }
          createPending={
            createFamilyMutation.isPending
          }
          online={isOnline}
          newFamilyRef={
            newFamilyRef
          }
          onSearchChange={
            setSearchInput
          }
          onNewFamilyNameChange={(
            value
          ) => {
            setNewFamilyName(value);
            if (newFamilyError) {
              setNewFamilyError(null);
            }
          }}
          onCreate={
            submitNewFamily
          }
        />

        <ProductFamiliesList
          families={families}
          loading={
            familiesQuery.isLoading
          }
          error={
            familiesQuery.isError
          }
          fetching={
            familiesQuery.isFetching
          }
          search={search}
          hasPrevious={
            history.length > 0
          }
          hasNext={Boolean(
            familiesQuery.data
              ?.next_cursor
          )}
          editingFamilyId={
            editingFamily?.id ??
            null
          }
          editingFamilyName={
            editingFamilyName
          }
          renameCommandPending={
            renameCommandPending
          }
          renameCommandBlocked={
            renameCommandBlocked
          }
          updatePending={
            updateFamilyMutation.isPending
          }
          online={isOnline}
          onRetry={() =>
            void familiesQuery.refetch()
          }
          onEdit={(family) =>
            void openFamilyEditor(
              family
            )
          }
          onEditingNameChange={
            setEditingFamilyName
          }
          onSaveEdit={() =>
            updateFamilyMutation.mutate()
          }
          onCancelEdit={
            cancelFamilyEditor
          }
          onPrevious={
            goToPreviousFamilyPage
          }
          onNext={
            goToNextFamilyPage
          }
        />
      </div>
    </Modal>
  );
}
