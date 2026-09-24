import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  Pencil,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useNavigate,
  useSearchParams,
} from "react-router-dom";
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
  buildConversionCommandPayload,
  parseConversionMutation,
  parseConversions,
  parseUoms,
  parseVariants,
  type CatalogVariant,
  type UomConversion,
  type UomConversionCommandPayload,
} from "@/pages/inventory/catalog/contracts";

type ConversionField =
  | "from"
  | "to"
  | "numerator"
  | "denominator"
  | "scale";

type ConversionDraft = {
  from_uom_id: string;
  to_uom_id: string;
  numerator: string;
  denominator: string;
  quantity_scale: string;
};

type ConversionUpdateCommand =
  UomConversionCommandPayload & {
    expected_version: number;
  };

const commandPayload = (
  value: unknown,
): UomConversionCommandPayload | null => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return null;
  }
  const row =
    value as Record<string, unknown>;
  if (
    typeof row.from_uom_id !== "number" ||
    !Number.isSafeInteger(row.from_uom_id) ||
    row.from_uom_id <= 0 ||
    typeof row.to_uom_id !== "number" ||
    !Number.isSafeInteger(row.to_uom_id) ||
    row.to_uom_id <= 0 ||
    typeof row.numerator !== "string" ||
    typeof row.denominator !== "string" ||
    typeof row.quantity_scale !== "number" ||
    !Number.isSafeInteger(row.quantity_scale)
  ) {
    return null;
  }

  try {
    const parsed =
      buildConversionCommandPayload({
        from_uom_id:
          String(row.from_uom_id),
        to_uom_id:
          String(row.to_uom_id),
        numerator: row.numerator,
        denominator: row.denominator,
        quantity_scale:
          String(row.quantity_scale),
      });
    return (
      parsed.from_uom_id === row.from_uom_id &&
      parsed.to_uom_id === row.to_uom_id &&
      parsed.numerator === row.numerator &&
      parsed.denominator === row.denominator &&
      parsed.quantity_scale === row.quantity_scale
    )
      ? parsed
      : null;
  } catch {
    return null;
  }
};

const updateCommandPayload = (
  value: unknown,
): ConversionUpdateCommand | null => {
  const base = commandPayload(value);
  if (
    !base ||
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return null;
  }
  const expectedVersion = (
    value as Record<string, unknown>
  ).expected_version;
  if (
    typeof expectedVersion !== "number" ||
    !Number.isSafeInteger(expectedVersion) ||
    expectedVersion <= 0
  ) {
    return null;
  }
  return {
    ...base,
    expected_version: expectedVersion,
  };
};

const draftFromPayload = (
  payload: UomConversionCommandPayload,
): ConversionDraft => ({
  from_uom_id: String(payload.from_uom_id),
  to_uom_id: String(payload.to_uom_id),
  numerator: payload.numerator,
  denominator: payload.denominator,
  quantity_scale: String(payload.quantity_scale),
});

const EMPTY_DRAFT: ConversionDraft = {
  from_uom_id: "",
  to_uom_id: "",
  numerator: "1",
  denominator: "1",
  quantity_scale: "0",
};

const parseVariantParam = (
  raw: string | null,
): number | null => {
  if (!raw) {
    return null;
  }
  const value = Number(raw);
  return Number.isSafeInteger(value) &&
    value > 0
    ? value
    : null;
};

export default function AdvancedUomDashboard() {
  const { t } = useTranslation();
  const uomLabel = (uom: {
    code: string;
    name: string;
  }) =>
    t(`uom.${uom.code}`, {
      defaultValue:
        uom.name || uom.code,
    });
  const navigate = useNavigate();
  const [searchParams, setSearchParams] =
    useSearchParams();
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const isOnline = useNetworkStatus();
  const queryClient = useQueryClient();

  const companyId =
    access.data?.company_id ?? null;
  const driverId =
    access.data?.driver_id ?? null;
  const canRead =
    access.isCompanyAdmin ||
    access.canAny("catalog.read");
  const canManage =
    access.isCompanyAdmin ||
    access.canAny("catalog.manage");

  const selectedVariantId =
    parseVariantParam(
      searchParams.get("variant"),
    );

  const [searchInput, setSearchInput] =
    useState("");
  const [search, setSearch] =
    useState("");
  const [cursor, setCursor] =
    useState<string | null>(null);
  const [history, setHistory] =
    useState<Array<string | null>>([]);
  const [draft, setDraft] =
    useState<ConversionDraft>(
      EMPTY_DRAFT,
    );
  const [
    conversionFieldError,
    setConversionFieldError,
  ] = useState<{
    field: ConversionField;
    message: string;
  } | null>(null);
  const fromUomRef =
    useRef<HTMLSelectElement | null>(
      null,
    );
  const toUomRef =
    useRef<HTMLSelectElement | null>(
      null,
    );
  const numeratorRef =
    useRef<HTMLInputElement | null>(
      null,
    );
  const denominatorRef =
    useRef<HTMLInputElement | null>(
      null,
    );
  const scaleRef =
    useRef<HTMLInputElement | null>(
      null,
    );
  const [editing, setEditing] =
    useState<UomConversion | null>(
      null,
    );
  const [
    pendingCreate,
    setPendingCreate,
  ] = useState<
    DurableCommand<UomConversionCommandPayload> | null
  >(null);
  const [
    pendingUpdate,
    setPendingUpdate,
  ] = useState<{
    conversionId: number;
    command: DurableCommand<ConversionUpdateCommand>;
  } | null>(null);
  const [
    pendingBlocked,
    setPendingBlocked,
  ] = useState(false);
  const [
    pendingCheckReady,
    setPendingCheckReady,
  ] = useState(false);

  useEffect(() => {
    const timer =
      window.setTimeout(() => {
        const clean =
          searchInput
            .trim()
            .slice(0, 100);
        setSearch(
          clean.length >= 2
            ? clean
            : "",
        );
        setCursor(null);
        setHistory([]);
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [searchInput]);

  const variantParams = useMemo(
    () => {
      const params =
        new URLSearchParams({
          limit: "50",
        });
      if (search) {
        params.set("search", search);
      }
      if (cursor) {
        params.set("cursor", cursor);
      }
      return params.toString();
    },
    [cursor, search],
  );

  const variantsQuery = useQuery({
    queryKey: [
      "advanced-uom-variants",
      companyId,
      variantParams,
    ],
    enabled:
      Boolean(companyId) &&
      canRead,
    queryFn: async ({ signal }) =>
      parseVariants(
        await authFetch(
          `/catalog/variants?${variantParams}`,
          { signal },
        ),
      ),
  });

  const resolvedVariantQuery =
    useQuery({
      queryKey: [
        "advanced-uom-resolved-variant",
        companyId,
        selectedVariantId,
      ],
      enabled:
        Boolean(
          companyId &&
          selectedVariantId,
        ) && canRead,
      queryFn: async ({ signal }) =>
        parseVariants(
          await authFetch(
            "/catalog/variants/resolve",
            {
              method: "POST",
              signal,
              body: JSON.stringify({
                ids: [
                  selectedVariantId,
                ],
              }),
            },
          ),
        ),
    });

  const uomsQuery = useQuery({
    queryKey: [
      "advanced-uom-catalog-uoms",
      companyId,
    ],
    enabled:
      Boolean(companyId) &&
      canRead,
    queryFn: async ({ signal }) =>
      parseUoms(
        await authFetch(
          "/catalog/uoms",
          { signal },
        ),
      ),
  });

  const page =
    variantsQuery.data;
  const selectedVariant:
    CatalogVariant | null =
    (
      page?.items.find(
        (item) =>
          item.id ===
          selectedVariantId,
      ) ??
      resolvedVariantQuery.data
        ?.items[0]
    ) ?? null;

  const conversionsQuery =
    useQuery({
      queryKey: [
        "advanced-uom-conversions",
        companyId,
        selectedVariant?.id ??
          null,
      ],
      enabled:
        Boolean(
          companyId &&
          selectedVariant,
        ) && canRead,
      queryFn: async ({ signal }) =>
        parseConversions(
          await authFetch(
            `/catalog/variants/${selectedVariant!.id}/conversions`,
            { signal },
          ),
        ),
    });

  useEffect(() => {
    setDraft(EMPTY_DRAFT);
    setEditing(null);
    setPendingCreate(null);
    setPendingUpdate(null);
    setPendingBlocked(false);
    setPendingCheckReady(false);
  }, [selectedVariant?.id]);

  useEffect(() => {
    let cancelled = false;

    if (
      !selectedVariant ||
      selectedVariant.lifecycle_status !==
        "DRAFT" ||
      companyId === null ||
      driverId === null ||
      !conversionsQuery.isSuccess
    ) {
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const createScope =
          durableScope(
            companyId,
            driverId,
            "catalog-uom-conversion-create",
            selectedVariant.id,
          );
        const createPending =
          await readDurableCommand<unknown>(
            createScope,
          );
        if (cancelled) {
          return;
        }
        if (createPending) {
          const payload =
            commandPayload(
              createPending.payload,
            );
          if (!payload) {
            setPendingBlocked(true);
            setPendingCheckReady(true);
            return;
          }
          setDraft(
            draftFromPayload(payload),
          );
          setEditing(null);
          setPendingCreate({
            requestId:
              createPending.requestId,
            payload,
            createdAt:
              createPending.createdAt,
          });
          setPendingCheckReady(true);
          return;
        }

        const found: Array<{
          conversion: UomConversion;
          command: DurableCommand<ConversionUpdateCommand>;
        }> = [];

        for (
          const conversion of
          conversionsQuery.data ?? []
        ) {
          const scope =
            durableScope(
              companyId,
              driverId,
              "catalog-uom-conversion-update",
              conversion.id,
            );
          const pending =
            await readDurableCommand<unknown>(
              scope,
            );
          if (!pending) {
            continue;
          }

          const payload =
            updateCommandPayload(
              pending.payload,
            );
          if (!payload) {
            setPendingBlocked(true);
            setPendingCheckReady(true);
            return;
          }
          found.push({
            conversion,
            command: {
              requestId:
                pending.requestId,
              payload,
              createdAt:
                pending.createdAt,
            },
          });
        }

        if (cancelled) {
          return;
        }
        if (found.length === 0) {
          setPendingCheckReady(true);
          return;
        }
        if (found.length !== 1) {
          setPendingBlocked(true);
          setPendingCheckReady(true);
          return;
        }

        const restored =
          found[0];
        setEditing(
          restored.conversion,
        );
        setDraft(
          draftFromPayload(
            restored.command.payload,
          ),
        );
        setPendingUpdate({
          conversionId:
            restored.conversion.id,
          command:
            restored.command,
        });
        setPendingCheckReady(true);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPendingBlocked(true);
        setPendingCheckReady(true);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.advancedUom.saveFailed",
            ),
          ),
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    companyId,
    conversionsQuery.data,
    conversionsQuery.isSuccess,
    driverId,
    selectedVariant,
    t,
  ]);

  const durableBase = (
    operation: string,
    target: number,
  ) => {
    if (
      companyId === null ||
      driverId === null
    ) {
      throw new Error(
        "IDENTITY_NOT_READY",
      );
    }
    return durableScope(
      companyId,
      driverId,
      operation,
      target,
    );
  };

  const refreshConversions =
    async () => {
      await queryClient.invalidateQueries({
        queryKey: [
          "advanced-uom-conversions",
          companyId,
          selectedVariant?.id ??
            null,
        ],
      });
    };

  const createMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !selectedVariant ||
          selectedVariant
            .lifecycle_status !==
            "DRAFT"
        ) {
          throw new Error(
            "UOM_STRUCTURE_LOCKED",
          );
        }

        const payload =
          buildConversionCommandPayload(
            draft,
          );
        const scope = durableBase(
          "catalog-uom-conversion-create",
          selectedVariant.id,
        );
        const command =
          pendingCreate ??
          (await getOrCreateDurableCommand(
            scope,
            payload,
          ));
        setPendingCreate(command);

        try {
          const result =
            parseConversionMutation(
              await authFetch(
                `/catalog/variants/${selectedVariant.id}/conversions`,
                {
                  method: "POST",
                  body: JSON.stringify({
                    request_id:
                      command.requestId,
                    ...command.payload,
                  }),
                },
              ),
            );
          completeDurableOperation(
            scope,
            command.requestId,
          );
          setPendingCreate(null);
          return result;
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
            !isAmbiguousRequestError(
              error,
            ) &&
            code !==
              "DURABLE_OPERATION_PENDING" &&
            code !==
              "DURABLE_OPERATION_CORRUPT"
          ) {
            abandonDurableOperation(
              scope,
            );
            setPendingCreate(null);
          }
          throw error;
        }
      },
      onSuccess: async () => {
        toast.success(
          t(
            "products.advancedUom.saved",
          ),
        );
        setDraft(EMPTY_DRAFT);
        await refreshConversions();
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.advancedUom.saveFailed",
            ),
          ),
        ),
    });

  const updateMutation =
    useMutation({
      mutationFn: async () => {
        if (
          !selectedVariant ||
          selectedVariant
            .lifecycle_status !==
            "DRAFT" ||
          !editing
        ) {
          throw new Error(
            "UOM_STRUCTURE_LOCKED",
          );
        }

        const base =
          buildConversionCommandPayload(
            draft,
          );
        const payload:
          ConversionUpdateCommand = {
          ...base,
          expected_version:
            editing.version,
        };
        const scope = durableBase(
          "catalog-uom-conversion-update",
          editing.id,
        );
        const command =
          pendingUpdate?.conversionId ===
            editing.id
            ? pendingUpdate.command
            : await getOrCreateDurableCommand(
                scope,
                payload,
              );
        setPendingUpdate({
          conversionId: editing.id,
          command,
        });

        try {
          const result =
            parseConversionMutation(
              await authFetch(
                `/catalog/conversions/${editing.id}`,
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
          completeDurableOperation(
            scope,
            command.requestId,
          );
          setPendingUpdate(null);
          return result;
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
            !isAmbiguousRequestError(
              error,
            ) &&
            code !==
              "DURABLE_OPERATION_PENDING" &&
            code !==
              "DURABLE_OPERATION_CORRUPT"
          ) {
            abandonDurableOperation(
              scope,
            );
            setPendingUpdate(null);
          }
          throw error;
        }
      },
      onSuccess: async () => {
        toast.success(
          t(
            "products.advancedUom.saved",
          ),
        );
        setDraft(EMPTY_DRAFT);
        setEditing(null);
        await refreshConversions();
      },
      onError: (error) =>
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.advancedUom.saveFailed",
            ),
          ),
        ),
    });

  const selectVariant = (
    id: number,
  ) => {
    const next =
      new URLSearchParams(
        searchParams,
      );
    next.set(
      "variant",
      String(id),
    );
    setSearchParams(next);
  };

  const clearSelection = () => {
    const next =
      new URLSearchParams(
        searchParams,
      );
    next.delete("variant");
    setSearchParams(next);
  };

  const editConversion = (
    item: UomConversion,
  ) => {
    if (
      pendingCreate ||
      pendingUpdate ||
      pendingBlocked
    ) {
      return;
    }
    setConversionFieldError(null);
    setEditing(item);
    setDraft({
      from_uom_id:
        String(item.from_uom.id),
      to_uom_id:
        String(item.to_uom.id),
      numerator:
        item.numerator,
      denominator:
        item.denominator,
      quantity_scale:
        String(item.quantity_scale),
    });
  };

  const resetEditor = () => {
    if (
      pendingCreate ||
      pendingUpdate
    ) {
      return;
    }
    setConversionFieldError(null);
    setEditing(null);
    setDraft(EMPTY_DRAFT);
  };

  const submitConversion = () => {
    const fromId =
      Number(draft.from_uom_id);
    if (
      !Number.isSafeInteger(fromId) ||
      fromId <= 0
    ) {
      setConversionFieldError({
        field: "from",
        message: t(
          "products.advancedUom.uomRequired",
        ),
      });
      window.requestAnimationFrame(
        () => fromUomRef.current?.focus(),
      );
      return;
    }

    const toId =
      Number(draft.to_uom_id);
    if (
      !Number.isSafeInteger(toId) ||
      toId <= 0
    ) {
      setConversionFieldError({
        field: "to",
        message: t(
          "products.advancedUom.uomRequired",
        ),
      });
      window.requestAnimationFrame(
        () => toUomRef.current?.focus(),
      );
      return;
    }

    const exactPositive =
      (value: string) =>
        /^\d+(?:\.\d{1,6})?$/.test(
          value,
        ) &&
        Number(value) > 0;

    if (
      !exactPositive(
        draft.numerator,
      )
    ) {
      setConversionFieldError({
        field: "numerator",
        message: t(
          "products.advancedUom.invalidValue",
        ),
      });
      window.requestAnimationFrame(
        () => numeratorRef.current?.focus(),
      );
      return;
    }

    if (
      !exactPositive(
        draft.denominator,
      )
    ) {
      setConversionFieldError({
        field: "denominator",
        message: t(
          "products.advancedUom.invalidValue",
        ),
      });
      window.requestAnimationFrame(
        () =>
          denominatorRef.current?.focus(),
      );
      return;
    }

    const scale =
      Number(draft.quantity_scale);
    if (
      !Number.isSafeInteger(scale) ||
      scale < 0 ||
      scale > 6
    ) {
      setConversionFieldError({
        field: "scale",
        message: t(
          "products.advancedUom.invalidValue",
        ),
      });
      window.requestAnimationFrame(
        () => scaleRef.current?.focus(),
      );
      return;
    }

    setConversionFieldError(null);
    if (editing) {
      updateMutation.mutate();
    } else {
      createMutation.mutate();
    }
  };

  const busy =
    createMutation.isPending ||
    updateMutation.isPending;
  const editable =
    Boolean(
      selectedVariant &&
      selectedVariant
        .lifecycle_status ===
        "DRAFT" &&
      canManage &&
      pendingCheckReady,
    );
  const pendingCommand =
    pendingCreate !== null ||
    pendingUpdate !== null;
  const fieldsLocked =
    busy ||
    pendingCommand ||
    pendingBlocked;

  if (
    access.isSuccess &&
    !canRead
  ) {
    return (
      <div className="p-6">
        <p className="rounded-2xl bg-rose-50 p-4 text-sm font-black text-rose-800">
          {t(
            "products.advancedUom.noAccess",
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="products-a11y-scope flex min-h-0 flex-1 flex-col p-3 sm:p-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <button
            type="button"
            onClick={() =>
              navigate("/products")
            }
            className="mb-2 inline-flex items-center gap-2 text-xs font-black text-slate-500"
          >
            <ArrowLeft className="h-4 w-4 rtl:rotate-180" />
            {t(
              "products.advancedUom.back",
            )}
          </button>
          <h1 className="break-words text-xl font-black text-slate-900 sm:text-2xl">
            {t(
              "products.advancedUom.title",
            )}
          </h1>
          <p className="mt-1 max-w-3xl text-xs font-semibold leading-6 text-slate-500">
            {t(
              "products.advancedUom.description",
            )}
          </p>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto lg:grid-cols-[minmax(320px,0.85fr)_minmax(0,1.6fr)] lg:overflow-hidden">
        <section className="flex min-h-[280px] max-h-[45dvh] flex-col rounded-2xl border border-slate-200 bg-white lg:min-h-0 lg:max-h-none">
          <div className="border-b border-slate-100 p-3">
            <div className="relative">
              <Search className="absolute end-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchInput}
                onChange={(event) =>
                  setSearchInput(
                    event.target.value,
                  )
                }
                placeholder={t(
                  "products.advancedUom.searchPlaceholder",
                )}
                aria-label={t(
                  "products.advancedUom.searchPlaceholder",
                )}
                className="w-full rounded-xl border border-slate-200 px-3 py-2 pe-9 text-sm"
              />
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto p-2">
            {variantsQuery.isLoading ? (
              <p className="p-4 text-xs font-bold text-slate-400">
                {t("common.loading")}
              </p>
            ) : null}

            {variantsQuery.isError ? (
              <div className="m-2 rounded-xl bg-rose-50 p-3">
                <p className="text-xs font-bold text-rose-800">
                  {t(
                    "products.advancedUom.variantsLoadFailed",
                  )}
                </p>
                <button
                  type="button"
                  onClick={() =>
                    void variantsQuery.refetch()
                  }
                  className="mt-2 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                >
                  {t("common.retry")}
                </button>
              </div>
            ) : null}

            {!variantsQuery.isLoading &&
            !variantsQuery.isError &&
            !page?.items.length ? (
              <p className="p-4 text-xs font-bold text-slate-400">
                {t(
                  "products.advancedUom.noVariants",
                )}
              </p>
            ) : null}

            {page?.items.map(
              (item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() =>
                    selectVariant(
                      item.id,
                    )
                  }
                  data-active={
                    item.id ===
                    selectedVariantId
                  }
                  className="mb-2 w-full rounded-xl border border-slate-200 p-3 text-start data-[active=true]:border-slate-900 data-[active=true]:bg-slate-50"
                >
                  <p className="break-words font-black text-slate-900">
                    {item.name}
                  </p>
                  <p className="mt-1 break-all font-mono text-[11px] text-slate-500">
                    {item.sku}
                  </p>
                  <p className="mt-1 text-[11px] font-bold text-slate-500">
                    {t(
                      `products.details.lifecycleModes.${item.lifecycle_status}`
                    )}
                    {" · "}
                    {uomLabel(item.base_uom)}
                  </p>
                </button>
              ),
            )}
          </div>

          {history.length > 0 ||
          page?.next_cursor ? (
            <div className="grid grid-cols-2 gap-2 border-t border-slate-100 p-3 sm:flex sm:justify-end">
              <button
                type="button"
                disabled={
                  !history.length ||
                  variantsQuery.isFetching
                }
                onClick={() => {
                  const previous =
                    history.at(-1) ??
                    null;
                  setHistory(
                    (current) =>
                      current.slice(
                        0,
                        -1,
                      ),
                  );
                  setCursor(previous);
                }}
                className="w-full rounded-lg border px-3 py-2 text-xs font-black disabled:opacity-40 sm:w-auto"
              >
                {t(
                  "products.familyPrevious",
                )}
              </button>
              <button
                type="button"
                disabled={
                  !page?.next_cursor ||
                  variantsQuery.isFetching
                }
                onClick={() => {
                  if (
                    !page?.next_cursor
                  ) {
                    return;
                  }
                  setHistory(
                    (current) => [
                      ...current,
                      cursor,
                    ],
                  );
                  setCursor(
                    page.next_cursor,
                  );
                }}
                className="w-full rounded-lg border px-3 py-2 text-xs font-black disabled:opacity-40 sm:w-auto"
              >
                {t(
                  "products.familyNext",
                )}
              </button>
            </div>
          ) : null}
        </section>

        <section className="min-h-0 rounded-2xl border border-slate-200 bg-white p-3 sm:p-4 lg:overflow-auto">
          {!selectedVariantId ? (
            <p className="text-sm font-bold text-slate-500">
              {t(
                "products.advancedUom.selectVariant",
              )}
            </p>
          ) : null}

          {selectedVariantId &&
          resolvedVariantQuery.isLoading &&
          !selectedVariant ? (
            <p className="text-sm font-bold text-slate-400">
              {t("common.loading")}
            </p>
          ) : null}

          {selectedVariantId &&
          resolvedVariantQuery.isError &&
          !selectedVariant ? (
            <div className="rounded-xl bg-rose-50 p-4">
              <p className="text-sm font-bold text-rose-800">
                {t(
                  "products.advancedUom.variantLoadFailed",
                )}
              </p>
              <button
                type="button"
                onClick={() =>
                  void resolvedVariantQuery.refetch()
                }
                className="mt-2 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
              >
                {t("common.retry")}
              </button>
            </div>
          ) : null}

          {selectedVariantId &&
          resolvedVariantQuery.isSuccess &&
          !selectedVariant ? (
            <p className="rounded-xl bg-slate-50 p-4 text-sm font-bold text-slate-600">
              {t(
                "products.advancedUom.variantNotFound",
              )}
            </p>
          ) : null}

          {selectedVariant ? (
            <div>
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-4">
                <div>
                  <h2 className="text-xl font-black text-slate-900">
                    {selectedVariant.name}
                  </h2>
                  <p className="mt-1 font-mono text-xs text-slate-500">
                    {selectedVariant.sku}
                  </p>
                  <p className="mt-2 text-xs font-bold text-slate-500">
                    {t(
                      "products.advancedUom.baseUom",
                    )}
                    :{" "}
                    {uomLabel(
                      selectedVariant.base_uom
                    )}
                    {" ("}
                    {selectedVariant.base_uom.code}
                    {")"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={clearSelection}
                  className="rounded-lg border px-3 py-2 text-xs font-black"
                >
                  {t("common.close")}
                </button>
              </div>

              {selectedVariant.lifecycle_status !==
              "DRAFT" ? (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs font-bold leading-6 text-amber-900">
                  {t(
                    "products.advancedUom.lockedAfterPublish",
                  )}
                </div>
              ) : canManage ? (
                <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs font-bold text-emerald-900">
                  {t(
                    "products.advancedUom.draftEditable",
                  )}
                </div>
              ) : (
                <div className="mt-4 rounded-xl bg-slate-50 p-4 text-xs font-bold text-slate-600">
                  {t(
                    "products.advancedUom.readOnly",
                  )}
                </div>
              )}

              <div className="mt-5">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-black text-slate-900">
                    {t(
                      "products.advancedUom.conversions",
                    )}
                  </h3>
                  <button
                    type="button"
                    onClick={() =>
                      void conversionsQuery.refetch()
                    }
                    disabled={
                      conversionsQuery.isFetching
                    }
                    className="rounded-lg border p-2 disabled:opacity-40"
                    aria-label={t(
                      "common.refresh",
                    )}
                  >
                    <RefreshCw className="h-4 w-4" />
                  </button>
                </div>

                {conversionsQuery.isLoading ? (
                  <p className="mt-3 text-xs font-bold text-slate-400">
                    {t("common.loading")}
                  </p>
                ) : null}

                {conversionsQuery.isError ? (
                  <div className="mt-3 rounded-xl bg-rose-50 p-3">
                    <p className="text-xs font-bold text-rose-800">
                      {t(
                        "products.advancedUom.conversionsLoadFailed",
                      )}
                    </p>
                    <button
                      type="button"
                      onClick={() =>
                        void conversionsQuery.refetch()
                      }
                      className="mt-2 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                    >
                      {t("common.retry")}
                    </button>
                  </div>
                ) : null}

                {!conversionsQuery.isLoading &&
                !conversionsQuery.isError &&
                !conversionsQuery.data
                  ?.length ? (
                  <p className="mt-3 rounded-xl bg-slate-50 p-3 text-xs font-bold text-slate-500">
                    {t(
                      "products.advancedUom.noConversions",
                    )}
                  </p>
                ) : null}

                <div className="mt-3 space-y-2">
                  {conversionsQuery.data?.map(
                    (item) => (
                      <div
                        key={item.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-3"
                      >
                        <div>
                          <p className="text-sm font-black text-slate-900">
                            {item.from_uom.code}
                            {" × "}
                            {item.numerator}
                            {"/"}
                            {item.denominator}
                            {" → "}
                            {item.to_uom.code}
                          </p>
                          <p className="mt-1 text-[11px] font-bold text-slate-500">
                            {t(
                              "products.advancedUom.scale",
                            )}
                            :{" "}
                            {item.quantity_scale}
                          </p>
                        </div>
                        {editable ? (
                          <button
                            type="button"
                            disabled={
                              pendingCommand ||
                              pendingBlocked
                            }
                            onClick={() =>
                              editConversion(
                                item,
                              )
                            }
                            className="w-full rounded-lg border px-3 py-2 text-xs font-black disabled:opacity-40 sm:w-auto"
                          >
                            <Pencil className="me-1 inline h-4 w-4" />
                            {t(
                              "common.edit",
                            )}
                          </button>
                        ) : null}
                      </div>
                    ),
                  )}
                </div>
              </div>

              {editable ? (
                <form
                  className="mt-5 rounded-2xl border border-slate-200 p-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitConversion();
                  }}
                >
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h3 className="text-sm font-black text-slate-900">
                      {editing
                        ? t(
                            "products.advancedUom.editConversion",
                          )
                        : t(
                            "products.advancedUom.addConversion",
                          )}
                    </h3>
                    {editing &&
                    !pendingCommand ? (
                      <button
                        type="button"
                        onClick={resetEditor}
                        className="text-xs font-black text-slate-500"
                      >
                        {t("common.cancel")}
                      </button>
                    ) : null}
                  </div>

                  {pendingBlocked ? (
                    <div className="mb-3 rounded-xl bg-rose-50 p-3 text-xs font-bold text-rose-800">
                      {t(
                        "products.advancedUom.pendingBlocked",
                      )}
                    </div>
                  ) : pendingCommand ? (
                    <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold leading-6 text-amber-900">
                      {t(
                        "products.advancedUom.pendingRetry",
                      )}
                    </div>
                  ) : null}

                  {uomsQuery.isError ? (
                    <div className="rounded-xl bg-rose-50 p-3">
                      <p className="text-xs font-bold text-rose-800">
                        {t(
                          "products.advancedUom.uomsLoadFailed",
                        )}
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          void uomsQuery.refetch()
                        }
                        className="mt-2 rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
                      >
                        {t("common.retry")}
                      </button>
                    </div>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="text-xs font-black text-slate-600">
                        {t(
                          "products.advancedUom.from",
                        )}
                        <select
                          ref={fromUomRef}
                          value={draft.from_uom_id}
                          onChange={(event) => {
                            setDraft(
                              (current) => ({
                                ...current,
                                from_uom_id:
                                  event.target.value,
                              }),
                            );
                            if (
                              conversionFieldError?.field ===
                              "from"
                            ) {
                              setConversionFieldError(
                                null,
                              );
                            }
                          }}
                          disabled={
                            fieldsLocked ||
                            uomsQuery.isLoading
                          }
                          aria-invalid={
                            conversionFieldError?.field ===
                            "from"
                              ? "true"
                              : undefined
                          }
                          aria-describedby={
                            conversionFieldError?.field ===
                            "from"
                              ? "advanced-uom-from-error"
                              : undefined
                          }
                          className="mt-1 w-full rounded-lg border p-2"
                        >
                          <option value="">
                            {t(
                              "products.advancedUom.chooseUom",
                            )}
                          </option>
                          {uomsQuery.data?.map(
                            (uom) => (
                              <option
                                key={uom.id}
                                value={uom.id}
                              >
                                {uom.code}
                                {" — "}
                                {uomLabel(uom)}
                              </option>
                            ),
                          )}
                        </select>
                        {conversionFieldError?.field ===
                        "from" ? (
                          <span
                            id="advanced-uom-from-error"
                            role="alert"
                            className="mt-1 block text-[11px] font-bold text-rose-700"
                          >
                            {
                              conversionFieldError.message
                            }
                          </span>
                        ) : null}
                      </label>

                      <label className="text-xs font-black text-slate-600">
                        {t(
                          "products.advancedUom.to",
                        )}
                        <select
                          ref={toUomRef}
                          value={draft.to_uom_id}
                          onChange={(event) => {
                            setDraft(
                              (current) => ({
                                ...current,
                                to_uom_id:
                                  event.target.value,
                              }),
                            );
                            if (
                              conversionFieldError?.field ===
                              "to"
                            ) {
                              setConversionFieldError(
                                null,
                              );
                            }
                          }}
                          disabled={
                            fieldsLocked ||
                            uomsQuery.isLoading
                          }
                          aria-invalid={
                            conversionFieldError?.field ===
                            "to"
                              ? "true"
                              : undefined
                          }
                          aria-describedby={
                            conversionFieldError?.field ===
                            "to"
                              ? "advanced-uom-to-error"
                              : undefined
                          }
                          className="mt-1 w-full rounded-lg border p-2"
                        >
                          <option value="">
                            {t(
                              "products.advancedUom.chooseUom",
                            )}
                          </option>
                          {uomsQuery.data?.map(
                            (uom) => (
                              <option
                                key={uom.id}
                                value={uom.id}
                              >
                                {uom.code}
                                {" — "}
                                {uomLabel(uom)}
                              </option>
                            ),
                          )}
                        </select>
                        {conversionFieldError?.field ===
                        "to" ? (
                          <span
                            id="advanced-uom-to-error"
                            role="alert"
                            className="mt-1 block text-[11px] font-bold text-rose-700"
                          >
                            {
                              conversionFieldError.message
                            }
                          </span>
                        ) : null}
                      </label>

                      <label className="text-xs font-black text-slate-600">
                        {t(
                          "products.advancedUom.numerator",
                        )}
                        <input
                          ref={numeratorRef}
                          value={draft.numerator}
                          onChange={(event) => {
                            setDraft(
                              (current) => ({
                                ...current,
                                numerator:
                                  event.target.value,
                              }),
                            );
                            if (
                              conversionFieldError?.field ===
                              "numerator"
                            ) {
                              setConversionFieldError(
                                null,
                              );
                            }
                          }}
                          disabled={fieldsLocked}
                          aria-invalid={
                            conversionFieldError?.field ===
                            "numerator"
                              ? "true"
                              : undefined
                          }
                          aria-describedby={
                            conversionFieldError?.field ===
                            "numerator"
                              ? "advanced-uom-numerator-error"
                              : undefined
                          }
                          className="mt-1 w-full rounded-lg border p-2"
                        />
                        {conversionFieldError?.field ===
                        "numerator" ? (
                          <span
                            id="advanced-uom-numerator-error"
                            role="alert"
                            className="mt-1 block text-[11px] font-bold text-rose-700"
                          >
                            {
                              conversionFieldError.message
                            }
                          </span>
                        ) : null}
                      </label>

                      <label className="text-xs font-black text-slate-600">
                        {t(
                          "products.advancedUom.denominator",
                        )}
                        <input
                          ref={denominatorRef}
                          value={draft.denominator}
                          onChange={(event) => {
                            setDraft(
                              (current) => ({
                                ...current,
                                denominator:
                                  event.target.value,
                              }),
                            );
                            if (
                              conversionFieldError?.field ===
                              "denominator"
                            ) {
                              setConversionFieldError(
                                null,
                              );
                            }
                          }}
                          disabled={fieldsLocked}
                          aria-invalid={
                            conversionFieldError?.field ===
                            "denominator"
                              ? "true"
                              : undefined
                          }
                          aria-describedby={
                            conversionFieldError?.field ===
                            "denominator"
                              ? "advanced-uom-denominator-error"
                              : undefined
                          }
                          className="mt-1 w-full rounded-lg border p-2"
                        />
                        {conversionFieldError?.field ===
                        "denominator" ? (
                          <span
                            id="advanced-uom-denominator-error"
                            role="alert"
                            className="mt-1 block text-[11px] font-bold text-rose-700"
                          >
                            {
                              conversionFieldError.message
                            }
                          </span>
                        ) : null}
                      </label>

                      <label className="text-xs font-black text-slate-600 sm:col-span-2">
                        {t(
                          "products.advancedUom.scale",
                        )}
                        <input
                          ref={scaleRef}
                          value={draft.quantity_scale}
                          onChange={(event) => {
                            setDraft(
                              (current) => ({
                                ...current,
                                quantity_scale:
                                  event.target.value,
                              }),
                            );
                            if (
                              conversionFieldError?.field ===
                              "scale"
                            ) {
                              setConversionFieldError(
                                null,
                              );
                            }
                          }}
                          disabled={fieldsLocked}
                          aria-invalid={
                            conversionFieldError?.field ===
                            "scale"
                              ? "true"
                              : undefined
                          }
                          aria-describedby={
                            conversionFieldError?.field ===
                            "scale"
                              ? "advanced-uom-scale-error"
                              : undefined
                          }
                          className="mt-1 w-full rounded-lg border p-2"
                        />
                        {conversionFieldError?.field ===
                        "scale" ? (
                          <span
                            id="advanced-uom-scale-error"
                            role="alert"
                            className="mt-1 block text-[11px] font-bold text-rose-700"
                          >
                            {
                              conversionFieldError.message
                            }
                          </span>
                        ) : null}
                      </label>
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={
                      busy ||
                      !isOnline ||
                      pendingBlocked ||
                      uomsQuery.isLoading ||
                      uomsQuery.isError
                    }
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-xs font-black text-white disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" />
                    {pendingCommand
                      ? t("common.retry")
                      : editing
                        ? t("common.save")
                        : t(
                            "products.advancedUom.addConversion",
                          )}
                  </button>
                </form>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
