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
} from "@/features/catalog/contracts";

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
  const backofficeUserId =
    access.data?.backoffice_user_id ?? null;
  const canRead =
    access.isCompanyOwner ||
    access.canAny("catalog.read");
  const canManage =
    access.isCompanyOwner ||
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
  const pageHeadingRef =
    useRef<HTMLHeadingElement | null>(
      null,
    );
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
    window.requestAnimationFrame(
      () =>
        pageHeadingRef.current?.focus(),
    );
  }, []);

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
      backofficeUserId === null ||
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
            backofficeUserId,
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
              backofficeUserId,
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
    backofficeUserId,
    selectedVariant,
    t,
  ]);

  const durableBase = (
    operation: string,
    target: number,
  ) => {
    if (
      companyId === null ||
      backofficeUserId === null
    ) {
      throw new Error(
        "IDENTITY_NOT_READY",
      );
    }
    return durableScope(
      companyId,
      backofficeUserId,
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
                `/catalog/variants/${selectedVariant.id}/conversions/${editing.id}`,
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
        setEditing(null);
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

  const startCreate = () => {
    if (
      pendingBlocked ||
      pendingCreate ||
      pendingUpdate ||
      !pendingCheckReady
    ) {
      return;
    }
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    window.requestAnimationFrame(
      () => fromUomRef.current?.focus(),
    );
  };

  const startEdit = (
    conversion: UomConversion,
  ) => {
    if (
      pendingBlocked ||
      pendingCreate ||
      pendingUpdate ||
      !pendingCheckReady
    ) {
      return;
    }
    setEditing(conversion);
    setDraft({
      from_uom_id:
        String(conversion.from_uom_id),
      to_uom_id:
        String(conversion.to_uom_id),
      numerator: conversion.numerator,
      denominator: conversion.denominator,
      quantity_scale:
        String(conversion.quantity_scale),
    });
    window.requestAnimationFrame(
      () => fromUomRef.current?.focus(),
    );
  };

  const canEditVariant =
    canManage &&
    selectedVariant?.lifecycle_status ===
      "DRAFT";

  const isSaveDisabled =
    !isOnline ||
    !canEditVariant ||
    pendingBlocked ||
    !pendingCheckReady ||
    createMutation.isPending ||
    updateMutation.isPending;

  return (
    <main className="min-h-screen bg-slate-50/70 text-slate-900">
      <section className="mx-auto flex w-full max-w-[1520px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
        <header className="rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <button
                type="button"
                onClick={() => navigate("/products")}
                className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-slate-200 text-slate-600 transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-300"
                aria-label={t(
                  "products.advancedUom.back",
                )}
              >
                <ArrowLeft className="h-4 w-4 rtl:rotate-180" />
              </button>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  {t(
                    "products.advancedUom.eyebrow",
                  )}
                </p>
                <h1
                  ref={pageHeadingRef}
                  tabIndex={-1}
                  className="mt-1 text-2xl font-semibold tracking-tight text-slate-950 outline-none"
                >
                  {t(
                    "products.advancedUom.title",
                  )}
                </h1>
                <p className="mt-1 max-w-3xl text-sm text-slate-600">
                  {t(
                    "products.advancedUom.subtitle",
                  )}
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => {
                void Promise.all([
                  variantsQuery.refetch(),
                  uomsQuery.refetch(),
                  conversionsQuery.refetch(),
                ]);
              }}
              disabled={
                variantsQuery.isFetching ||
                uomsQuery.isFetching ||
                conversionsQuery.isFetching
              }
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${
                  variantsQuery.isFetching ||
                  uomsQuery.isFetching ||
                  conversionsQuery.isFetching
                    ? "animate-spin"
                    : ""
                }`}
              />
              {t(
                "products.advancedUom.refresh",
              )}
            </button>
          </div>
        </header>

        {!canRead ? (
          <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-950">
            {t(
              "products.advancedUom.noAccess",
            )}
          </section>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400 rtl:left-auto rtl:right-3" />
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
                  className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 rtl:pl-3 rtl:pr-9"
                />
              </div>

              <div className="mt-4 space-y-2">
                {variantsQuery.isLoading ? (
                  <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500">
                    {t(
                      "products.advancedUom.loadingVariants",
                    )}
                  </p>
                ) : variantsQuery.isError ? (
                  <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-4 text-sm text-rose-700">
                    {apiErrorMessage(
                      variantsQuery.error,
                      t(
                        "products.advancedUom.loadVariantsFailed",
                      ),
                    )}
                  </p>
                ) : page?.items.length ? (
                  page.items.map((variant) => {
                    const active =
                      variant.id ===
                      selectedVariant?.id;
                    return (
                      <button
                        key={variant.id}
                        type="button"
                        onClick={() => {
                          const next =
                            new URLSearchParams(
                              searchParams,
                            );
                          next.set(
                            "variant",
                            String(variant.id),
                          );
                          setSearchParams(next);
                        }}
                        className={`w-full rounded-xl border px-3 py-3 text-start transition ${
                          active
                            ? "border-slate-900 bg-slate-900 text-white"
                            : "border-slate-200 bg-white hover:bg-slate-50"
                        }`}
                      >
                        <span className="block text-sm font-semibold">
                          {variant.product_name}
                        </span>
                        <span
                          className={`mt-1 block text-xs ${
                            active
                              ? "text-slate-300"
                              : "text-slate-500"
                          }`}
                        >
                          {variant.sku}
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500">
                    {t(
                      "products.advancedUom.noVariants",
                    )}
                  </p>
                )}
              </div>

              <div className="mt-4 flex items-center justify-between gap-3">
                <button
                  type="button"
                  disabled={history.length === 0}
                  onClick={() => {
                    const previous =
                      history.at(-1) ?? null;
                    setHistory((current) =>
                      current.slice(0, -1),
                    );
                    setCursor(previous);
                  }}
                  className="h-9 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {t(
                    "products.advancedUom.previous",
                  )}
                </button>
                <button
                  type="button"
                  disabled={!page?.next_cursor}
                  onClick={() => {
                    setHistory((current) => [
                      ...current,
                      cursor,
                    ]);
                    setCursor(
                      page?.next_cursor ?? null,
                    );
                  }}
                  className="h-9 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {t(
                    "products.advancedUom.next",
                  )}
                </button>
              </div>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              {!selectedVariant ? (
                <p className="text-sm text-slate-500">
                  {t(
                    "products.advancedUom.selectVariant",
                  )}
                </p>
              ) : (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                        {selectedVariant.sku}
                      </p>
                      <h2 className="mt-1 text-lg font-semibold text-slate-950">
                        {selectedVariant.product_name}
                      </h2>
                    </div>
                    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-600">
                      {selectedVariant.lifecycle_status}
                    </span>
                  </div>

                  {pendingBlocked ? (
                    <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
                      {t(
                        "products.advancedUom.pendingCorrupt",
                      )}
                    </div>
                  ) : null}

                  <div className="rounded-xl border border-slate-200 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-950">
                          {editing
                            ? t(
                                "products.advancedUom.editConversion",
                              )
                            : t(
                                "products.advancedUom.newConversion",
                              )}
                        </h3>
                        <p className="mt-1 text-xs text-slate-500">
                          {t(
                            "products.advancedUom.draftOnly",
                          )}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={startCreate}
                        disabled={
                          !canEditVariant ||
                          !pendingCheckReady ||
                          pendingBlocked ||
                          Boolean(
                            pendingCreate ||
                            pendingUpdate,
                          )
                        }
                        className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Plus className="h-4 w-4" />
                        {t(
                          "products.advancedUom.newAction",
                        )}
                      </button>
                    </div>

                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <label className="text-sm font-medium text-slate-700">
                        <span className="mb-1.5 block">
                          {t(
                            "products.advancedUom.fromUom",
                          )}
                        </span>
                        <select
                          ref={fromUomRef}
                          value={draft.from_uom_id}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              from_uom_id:
                                event.target.value,
                            }));
                            setConversionFieldError(null);
                          }}
                          disabled={isSaveDisabled}
                          className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50"
                        >
                          <option value="">
                            {t(
                              "products.advancedUom.chooseUom",
                            )}
                          </option>
                          {(uomsQuery.data ?? []).map(
                            (uom) => (
                              <option
                                key={uom.id}
                                value={uom.id}
                              >
                                {uomLabel(uom)}
                              </option>
                            ),
                          )}
                        </select>
                      </label>

                      <label className="text-sm font-medium text-slate-700">
                        <span className="mb-1.5 block">
                          {t(
                            "products.advancedUom.toUom",
                          )}
                        </span>
                        <select
                          ref={toUomRef}
                          value={draft.to_uom_id}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              to_uom_id:
                                event.target.value,
                            }));
                            setConversionFieldError(null);
                          }}
                          disabled={isSaveDisabled}
                          className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50"
                        >
                          <option value="">
                            {t(
                              "products.advancedUom.chooseUom",
                            )}
                          </option>
                          {(uomsQuery.data ?? []).map(
                            (uom) => (
                              <option
                                key={uom.id}
                                value={uom.id}
                              >
                                {uomLabel(uom)}
                              </option>
                            ),
                          )}
                        </select>
                      </label>

                      <label className="text-sm font-medium text-slate-700">
                        <span className="mb-1.5 block">
                          {t(
                            "products.advancedUom.numerator",
                          )}
                        </span>
                        <input
                          ref={numeratorRef}
                          inputMode="decimal"
                          value={draft.numerator}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              numerator:
                                event.target.value,
                            }));
                            setConversionFieldError(null);
                          }}
                          disabled={isSaveDisabled}
                          className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50"
                        />
                      </label>

                      <label className="text-sm font-medium text-slate-700">
                        <span className="mb-1.5 block">
                          {t(
                            "products.advancedUom.denominator",
                          )}
                        </span>
                        <input
                          ref={denominatorRef}
                          inputMode="decimal"
                          value={draft.denominator}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              denominator:
                                event.target.value,
                            }));
                            setConversionFieldError(null);
                          }}
                          disabled={isSaveDisabled}
                          className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50"
                        />
                      </label>

                      <label className="text-sm font-medium text-slate-700 sm:col-span-2">
                        <span className="mb-1.5 block">
                          {t(
                            "products.advancedUom.quantityScale",
                          )}
                        </span>
                        <input
                          ref={scaleRef}
                          inputMode="numeric"
                          value={draft.quantity_scale}
                          onChange={(event) => {
                            setDraft((current) => ({
                              ...current,
                              quantity_scale:
                                event.target.value,
                            }));
                            setConversionFieldError(null);
                          }}
                          disabled={isSaveDisabled}
                          className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-200 disabled:bg-slate-50"
                        />
                      </label>
                    </div>

                    {conversionFieldError ? (
                      <p className="mt-3 text-sm text-rose-700">
                        {conversionFieldError.message}
                      </p>
                    ) : null}

                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setConversionFieldError(null);
                          if (!draft.from_uom_id) {
                            setConversionFieldError({
                              field: "from",
                              message: t(
                                "products.advancedUom.fromRequired",
                              ),
                            });
                            fromUomRef.current?.focus();
                            return;
                          }
                          if (!draft.to_uom_id) {
                            setConversionFieldError({
                              field: "to",
                              message: t(
                                "products.advancedUom.toRequired",
                              ),
                            });
                            toUomRef.current?.focus();
                            return;
                          }
                          if (!draft.numerator.trim()) {
                            setConversionFieldError({
                              field: "numerator",
                              message: t(
                                "products.advancedUom.numeratorRequired",
                              ),
                            });
                            numeratorRef.current?.focus();
                            return;
                          }
                          if (!draft.denominator.trim()) {
                            setConversionFieldError({
                              field: "denominator",
                              message: t(
                                "products.advancedUom.denominatorRequired",
                              ),
                            });
                            denominatorRef.current?.focus();
                            return;
                          }
                          if (!draft.quantity_scale.trim()) {
                            setConversionFieldError({
                              field: "scale",
                              message: t(
                                "products.advancedUom.scaleRequired",
                              ),
                            });
                            scaleRef.current?.focus();
                            return;
                          }
                          if (editing) {
                            updateMutation.mutate();
                          } else {
                            createMutation.mutate();
                          }
                        }}
                        disabled={isSaveDisabled}
                        className="inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {editing ? (
                          <Pencil className="h-4 w-4" />
                        ) : (
                          <Plus className="h-4 w-4" />
                        )}
                        {t(
                          "products.advancedUom.save",
                        )}
                      </button>
                    </div>
                  </div>

                  <div className="rounded-xl border border-slate-200 p-4">
                    <h3 className="text-sm font-semibold text-slate-950">
                      {t(
                        "products.advancedUom.existingConversions",
                      )}
                    </h3>
                    <div className="mt-3 space-y-2">
                      {conversionsQuery.isLoading ? (
                        <p className="text-sm text-slate-500">
                          {t(
                            "products.advancedUom.loadingConversions",
                          )}
                        </p>
                      ) : conversionsQuery.isError ? (
                        <p className="text-sm text-rose-700">
                          {apiErrorMessage(
                            conversionsQuery.error,
                            t(
                              "products.advancedUom.loadConversionsFailed",
                            ),
                          )}
                        </p>
                      ) : (
                        conversionsQuery.data ?? []
                      ).length ? (
                        (
                          conversionsQuery.data ?? []
                        ).map((conversion) => (
                          <button
                            key={conversion.id}
                            type="button"
                            onClick={() =>
                              startEdit(conversion)
                            }
                            disabled={!canEditVariant}
                            className="w-full rounded-lg border border-slate-200 px-3 py-3 text-start transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            <span className="block text-sm font-semibold text-slate-950">
                              {conversion.from_uom_code} → {conversion.to_uom_code}
                            </span>
                            <span className="mt-1 block text-xs text-slate-500">
                              {conversion.numerator}/{conversion.denominator} · {t(
                                "products.advancedUom.scaleShort",
                                {
                                  scale:
                                    conversion.quantity_scale,
                                },
                              )}
                            </span>
                          </button>
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">
                          {t(
                            "products.advancedUom.noConversions",
                          )}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
      </section>
    </main>
  );
}
