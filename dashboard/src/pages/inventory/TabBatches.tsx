import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCcw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import type { InventoryBatchFocusIntent } from "@/features/inventory/navigation";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { BatchDispositionManager } from "./batches/BatchDispositionManager";
import { BatchIndexFilters, type BatchFilterFamilyOption, type BatchFilterProductOption } from "./batches/BatchIndexFilters";
import { BatchIndexSummary } from "./batches/BatchIndexSummary";
import { BatchIndexTable } from "./batches/BatchIndexTable";
import {
  DEFAULT_BATCH_EXPIRY_WARNING_DAYS,
  normalizeBatchExpiryWarningDays,
  readBatchDisplayPreferences,
  writeBatchDisplayPreferences,
} from "./batches/batchDisplayPreferences";
import {
  DEFAULT_BATCH_INDEX_FILTERS,
  parseBatchIndexCursorPage,
  toBatchActionSnapshot,
  type BatchIndexFilters as BatchIndexFilterState,
  type WarehouseBatchIndexItem,
} from "./batches/batchIndexContracts";
import { batchIndexText } from "./batches/batchIndexI18n";
import type { BatchActionSnapshot } from "./batches/contracts";
import type { BatchSpecialTransferResult } from "./batches/batchSpecialTransferContract";
import {
  parseBatchStockSources,
  type ReservationOwner,
} from "./batches/batchStockSourcesContract";
import { useBatchIndex } from "./batches/useBatchIndex";
import { useBatchSelectorDiscovery } from "./batches/useBatchSelectorDiscovery";

interface Props {
  locationId: number;
  warehouses?: { id: number; name: string }[];
  onWarehouseChange?: (id: string) => void;
  active?: boolean;
  focus?: InventoryBatchFocusIntent | null;
  onFocusConsumed: () => void;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onInventoryChanged: () => void | Promise<void>;
}

type SelectedBatchContext = {
  batch: BatchActionSnapshot;
  productVariantId: number;
  baseUomCode: string;
  detail: WarehouseBatchIndexItem | null;
};

const mergeFamilies = (
  current: BatchFilterFamilyOption[],
  items: WarehouseBatchIndexItem[],
): BatchFilterFamilyOption[] => {
  const values = new Map(current.map((item) => [item.id, item]));
  for (const item of items) {
    values.set(item.product_id, { id: item.product_id, name: item.family_name });
  }
  return [...values.values()].sort((left, right) => left.name.localeCompare(right.name));
};

const mergeProducts = (
  current: BatchFilterProductOption[],
  items: WarehouseBatchIndexItem[],
): BatchFilterProductOption[] => {
  const values = new Map(current.map((item) => [item.id, item]));
  for (const item of items) {
    values.set(item.product_variant_id, {
      id: item.product_variant_id,
      name: item.product_name,
      sku: item.sku,
    });
  }
  return [...values.values()].sort((left, right) => left.name.localeCompare(right.name));
};

export function TabBatches({
  locationId,
  warehouses,
  onWarehouseChange,
  active = true,
  focus = null,
  onFocusConsumed,
  onOpenTransfers,
  onOpenReservationOwner,
  onInventoryChanged,
}: Props) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const canManageDisposition = access.can("batch.disposition");

  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<BatchIndexFilterState>(
    DEFAULT_BATCH_INDEX_FILTERS,
  );
  const [expiryWarningDays, setExpiryWarningDays] = useState(
    DEFAULT_BATCH_EXPIRY_WARNING_DAYS,
  );
  const [choices, setChoices] = useState<{
    scope: string; families: BatchFilterFamilyOption[]; products: BatchFilterProductOption[];
  }>({ scope: "", families: [], products: [] });
  const selectorScope = [access.data?.company_id, access.data?.principal_id, locationId].join(":");
  const [pinned, setPinned] = useState<{
    scope: string; family: BatchFilterFamilyOption | null; product: BatchFilterProductOption | null;
  }>({ scope: "", family: null, product: null });
  const discovery = useBatchSelectorDiscovery({
    locationId,
    companyId: access.data?.company_id ?? null,
    principalId: access.data?.principal_id ?? null,
    active,
  });
  const families = useMemo(() => {
    const values = new Map((choices.scope === selectorScope ? choices.families : []).map(item => [item.id, item]));
    for (const item of discovery.families) values.set(item.id, item);
    if (pinned.scope === selectorScope && pinned.family) values.set(pinned.family.id, pinned.family);
    return [...values.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [choices, discovery.families, pinned, selectorScope]);
  const products = useMemo(() => {
    const values = new Map((choices.scope === selectorScope ? choices.products : []).map(item => [item.id, item]));
    for (const item of discovery.products) values.set(item.id, item);
    if (pinned.scope === selectorScope && pinned.product) values.set(pinned.product.id, pinned.product);
    return [...values.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [choices, discovery.products, pinned, selectorScope]);
  const [selectedBatchContext, setSelectedBatchContext] =
    useState<SelectedBatchContext | null>(null);
  const selectedRefreshSeq = useRef(0);
  const selectionRef = useRef(filters);
  selectionRef.current = filters;
  const activeRef = useRef(active);
  activeRef.current = active;
  const validationSeq = useRef(0);
  const previousSelectorIdentity = useRef<string | null>(null);
  const selectedRefreshAbort = useRef<AbortController | null>(null);

  const batchIndex = useBatchIndex({
    locationId,
    filters,
    expiryWarningDays,
    active,
  });

  const text = useCallback(
    (key: Parameters<typeof batchIndexText>[2], values: Record<string, unknown> = {}) =>
      batchIndexText(t, language, key, values),
    [language, t],
  );

  const closeSelectedBatch = useCallback(() => {
    selectedRefreshSeq.current += 1;
    selectedRefreshAbort.current?.abort();
    selectedRefreshAbort.current = null;
    setSelectedBatchContext(null);
  }, []);

  // A hidden Batches tab must not leave a portalled action dialog active.
  useEffect(() => {
    if (!active) closeSelectedBatch();
  }, [active, closeSelectedBatch]);

  // Retain a selected value when changing warehouses ONLY if the new
  // warehouse's own authorized batch cursor independently confirms it.
  // Old company/principal labels are never carried into a new identity.
  useEffect(() => {
    const identity = [access.data?.company_id, access.data?.principal_id].join(":");
    const samePrincipal = previousSelectorIdentity.current === null ||
      previousSelectorIdentity.current === identity;
    previousSelectorIdentity.current = identity;
    const { familyId, productVariantId } = samePrincipal ? selectionRef.current :
      DEFAULT_BATCH_INDEX_FILTERS;
    const seq = ++validationSeq.current;
    const controller = new AbortController();
    setSearchInput("");
    setChoices({ scope: "", families: [], products: [] });
    setPinned({ scope: "", family: null, product: null });
    // Preserve the exact filter object when the values did not change.
    // Reconstructing an identical object triggers a second first-page request
    // (and can cancel the first real batch cursor before it settles).
    setFilters(current => {
      const next: BatchIndexFilterState = {
        ...DEFAULT_BATCH_INDEX_FILTERS,
        familyId: null,
        productVariantId: null,
      };
      return (Object.keys(next) as (keyof BatchIndexFilterState)[]).every(
        key => current[key] === next[key],
      ) ? current : next;
    });
    closeSelectedBatch();
    if (!activeRef.current || !access.data || (familyId === null && productVariantId === null)) {
      if (!activeRef.current || !access.data) {
        setFilters(DEFAULT_BATCH_INDEX_FILTERS);
      }
      return () => controller.abort();
    }
    const validate = async (key: "family_id" | "product_variant_id", id: number) => {
      const params = new URLSearchParams({
        location_id: String(locationId), limit: "1", sort: "PRODUCT_ASC", [key]: String(id),
      });
      const response = parseBatchIndexCursorPage(await authFetch(
        "/warehouse/inventory/batches/cursor?" + params.toString(),
        { signal: controller.signal },
      ));
      if (response.location_id !== locationId) throw new Error("BATCH_SELECTOR_SCOPE_MISMATCH");
      const match = response.items[0];
      return match && (key === "family_id" ? match.product_id : match.product_variant_id) === id
        ? match : null;
    };
    void Promise.all([
      familyId === null ? Promise.resolve(null) : validate("family_id", familyId),
      productVariantId === null ? Promise.resolve(null) : validate("product_variant_id", productVariantId),
    ]).then(([family, product]) => {
      if (controller.signal.aborted || seq !== validationSeq.current) return;
      setFilters(current => {
        const nextFamily = family ? family.product_id : null;
        const nextProduct = product ? product.product_variant_id : null;
        return current.familyId === nextFamily && current.productVariantId === nextProduct
          ? current
          : { ...current, familyId: nextFamily, productVariantId: nextProduct };
      });
      setChoices({
        scope: selectorScope,
        families: family ? mergeFamilies([], [family]) : [],
        products: product ? mergeProducts([], [product]) : [],
      });
      setPinned({
        scope: selectorScope,
        family: family ? { id: family.product_id, name: family.family_name } : null,
        product: product ? { id: product.product_variant_id, name: product.product_name, sku: product.sku } : null,
      });
    }).catch(() => {
      if (controller.signal.aborted || seq !== validationSeq.current) return;
      // A denied/failed validation cannot leave unverified selections active.
      setFilters(current => current.familyId === null && current.productVariantId === null
        ? current : { ...current, familyId: null, productVariantId: null });
      setChoices({ scope: "", families: [], products: [] });
      setPinned({ scope: "", family: null, product: null });
    });
    return () => {
      controller.abort();
      validationSeq.current += 1;
    };
  }, [access.data?.company_id, access.data?.principal_id, authFetch, closeSelectedBatch, locationId, selectorScope]);

  useEffect(() => {
    const revoke = () => {
      validationSeq.current += 1;
      setChoices({ scope: "", families: [], products: [] });
      setPinned({ scope: "", family: null, product: null });
      setFilters(DEFAULT_BATCH_INDEX_FILTERS);
    };
    window.addEventListener("inventory-permission-denied", revoke);
    return () => window.removeEventListener("inventory-permission-denied", revoke);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setFilters((current) =>
        current.search === clean ? current : { ...current, search: clean },
      );
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    if (!access.data) return;
    const preferences = readBatchDisplayPreferences(
      access.data.company_id,
      access.data.principal_id,
    );
    setExpiryWarningDays(preferences.expiryWarningDays);
  }, [access.data?.company_id, access.data?.principal_id]);

  useEffect(() => {
    if (batchIndex.items.length === 0) return;
    setChoices(current => ({
      scope: selectorScope,
      families: mergeFamilies(current.scope === selectorScope ? current.families : [], batchIndex.items),
      products: mergeProducts(current.scope === selectorScope ? current.products : [], batchIndex.items),
    }));
    setSelectedBatchContext((current) => {
      if (!current) return current;
      const detail = batchIndex.items.find(
        (item) =>
          item.batch_id === current.batch.batch_id &&
          item.product_variant_id === current.productVariantId,
      );
      return detail
        ? {
            batch: toBatchActionSnapshot(detail),
            productVariantId: detail.product_variant_id,
            baseUomCode: detail.base_uom_code,
            detail,
          }
        : current;
    });
  }, [batchIndex.items, selectorScope]);

  const refreshSelectedBatch = useCallback(async () => {
    const current = selectedBatchContext;
    if (!current) return;
    const expectedBatchId = current.batch.batch_id;
    const expectedVariantId = current.productVariantId;
    const requestSeq = ++selectedRefreshSeq.current;
    selectedRefreshAbort.current?.abort();
    const controller = new AbortController();
    selectedRefreshAbort.current = controller;
    try {
      const sources = parseBatchStockSources(
        await authFetch(
          `/warehouse/batches/${expectedBatchId}/stock-sources`,
          { signal: controller.signal },
        ),
      );
      if (requestSeq !== selectedRefreshSeq.current) return;
      if (
        sources.batch_id !== expectedBatchId ||
        sources.product_variant_id !== expectedVariantId
      ) {
        const error = new Error("BATCH_STOCK_SOURCES_SCOPE_MISMATCH") as Error & { code: string };
        error.code = "BATCH_STOCK_SOURCES_SCOPE_MISMATCH";
        throw error;
      }
      setSelectedBatchContext((latest) => {
        if (
          !latest ||
          latest.batch.batch_id !== expectedBatchId ||
          latest.productVariantId !== expectedVariantId
        ) {
          return latest;
        }
        return {
          ...latest,
          batch: sources.batch,
          baseUomCode: sources.base_uom_code,
        };
      });
    } catch (error: unknown) {
      if (requestSeq !== selectedRefreshSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      toast.error(apiErrorMessage(error, t("inventoryBatches.errors.focus")));
    } finally {
      if (selectedRefreshAbort.current === controller) {
        selectedRefreshAbort.current = null;
      }
    }
  }, [authFetch, selectedBatchContext, t]);

  useEffect(() => {
    if (!active || focus?.batchId === null || focus?.batchId === undefined) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const sources = parseBatchStockSources(
          await authFetch(
            `/warehouse/batches/${focus.batchId}/stock-sources`,
            { signal: controller.signal },
          ),
        );
        if (
          sources.batch_id !== focus.batchId ||
          sources.product_variant_id !== focus.variantId
        ) {
          const error = new Error("BATCH_STOCK_SOURCES_SCOPE_MISMATCH") as Error & { code: string };
          error.code = "BATCH_STOCK_SOURCES_SCOPE_MISMATCH";
          throw error;
        }
        setSelectedBatchContext({
          batch: sources.batch,
          productVariantId: sources.product_variant_id,
          baseUomCode: sources.base_uom_code,
          detail: null,
        });
        onFocusConsumed();
      } catch (error: unknown) {
        if (error instanceof Error && error.name === "AbortError") return;
        toast.error(apiErrorMessage(error, t("inventoryBatches.errors.focus")));
      }
    })();
    return () => controller.abort();
  }, [active, authFetch, focus?.batchId, focus?.variantId, onFocusConsumed, t]);

  const updateExpiryWarningDays = useCallback(
    (value: number) => {
      const next = normalizeBatchExpiryWarningDays(value);
      setExpiryWarningDays(next);
      if (access.data) {
        writeBatchDisplayPreferences(
          access.data.company_id,
          access.data.principal_id,
          { version: 1, expiryWarningDays: next },
        );
      }
    },
    [access.data],
  );

  const loadedCount = useMemo(
    () =>
      new Intl.NumberFormat(locale, {
        numberingSystem: "latn",
        maximumFractionDigits: 0,
      }).format(batchIndex.items.length),
    [batchIndex.items.length, locale],
  );

  const openBatchAction = useCallback((item: WarehouseBatchIndexItem) => {
    selectedRefreshSeq.current += 1;
    selectedRefreshAbort.current?.abort();
    selectedRefreshAbort.current = null;
    setSelectedBatchContext({
      batch: toBatchActionSnapshot(item),
      productVariantId: item.product_variant_id,
      baseUomCode: item.base_uom_code,
      detail: item,
    });
  }, []);

  return (
    <div
      dir={i18n.dir()}
      className="inventory-batches-view min-h-0 flex-1 overflow-auto bg-slate-50/60 p-2 sm:p-3"
    >
      <div className="mx-auto flex w-full min-w-0 max-w-[1800px] flex-col gap-2.5">
        {focus ? (
          <div
            role="status"
            className="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2 text-[10px] font-bold leading-5 text-amber-950"
          >
            {text("focusHint")}
          </div>
        ) : null}

        <section aria-label={text("title")} className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-2.5 py-2.5" data-batches-compact-toolbar="true">
            <div className="relative min-w-[11rem] flex-[1_1_13rem] sm:max-w-[25rem]">
              <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={searchInput}
                onChange={event => setSearchInput(event.target.value)}
                aria-label={text("searchPlaceholder")}
                placeholder={text("searchPlaceholder")}
                maxLength={200}
                className="h-9 w-full rounded-lg border border-slate-200 bg-white ps-9 pe-3 text-sm font-semibold text-slate-800 outline-none placeholder:font-medium placeholder:text-slate-400 focus-visible:ring-2 focus-visible:ring-slate-300"
              />
            </div>
            {warehouses && onWarehouseChange ? <select
              aria-label={text("warehouseLabel")}
              value={locationId}
              onChange={event => onWarehouseChange(event.target.value)}
              className="h-9 min-w-0 flex-[0_1_11rem] rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold text-slate-800 outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
            >
              {warehouses.map(warehouse => (
                <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
              ))}
            </select> : null}
            <span
              className="inline-flex h-9 shrink-0 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 text-xs font-bold tabular-nums text-slate-700"
              title={text("loadedCount", { count: loadedCount })}
              aria-live="polite"
              data-batches-loaded-count="true"
            >
              {text("loadedCount", { count: loadedCount })}
            </span>
            <button
              type="button"
              onClick={() => void batchIndex.refresh()}
              disabled={batchIndex.loading || batchIndex.summaryLoading}
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 outline-none hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-slate-300"
            >
              <RefreshCcw aria-hidden="true" className={`h-3.5 w-3.5 ${batchIndex.loading ? "animate-spin" : ""}`} />
              {text("refresh")}
            </button>
          </div>
          <BatchIndexFilters
            t={t}
            language={language}
            filters={filters}
            onFiltersChange={next => {
              setPinned(current => ({
                scope: selectorScope,
                family: next.familyId === null ? null : families.find(item => item.id === next.familyId) ??
                  (current.scope === selectorScope && current.family?.id === next.familyId ? current.family : null),
                product: next.productVariantId === null ? null : products.find(item => item.id === next.productVariantId) ??
                  (current.scope === selectorScope && current.product?.id === next.productVariantId ? current.product : null),
              }));
              setFilters(next);
            }}
            expiryWarningDays={expiryWarningDays}
            onExpiryWarningDaysChange={updateExpiryWarningDays}
            families={families}
            products={products}
            familySearch={discovery.familySearch}
            productSearch={discovery.productSearch}
            onFamilySearchChange={discovery.setFamilySearch}
            onProductSearchChange={discovery.setProductSearch}
            onOpenSelector={discovery.open}
            onCloseSelector={discovery.close}
            onMoreSelector={discovery.loadMore}
            onRetrySelector={discovery.retry}
            familyDiscovery={discovery.family}
            productDiscovery={discovery.product}
          />

          <BatchIndexSummary
            t={t}
            language={language}
            locale={locale}
            summary={batchIndex.summary}
            loading={batchIndex.summaryLoading}
            error={batchIndex.summaryError}
            onRetry={() => void batchIndex.retrySummary()}
          />

          <BatchIndexTable
            t={t}
            language={language}
            locale={locale}
            items={batchIndex.items}
            loading={batchIndex.loading}
            error={batchIndex.listError}
            hasMore={batchIndex.hasMore}
            loadingMore={batchIndex.loadingMore}
            continuationError={batchIndex.continuationError}
            canManageDisposition={canManageDisposition}
            expiryWarningDays={expiryWarningDays}
            onRetry={() => void batchIndex.retryList()}
            onLoadMore={() => void batchIndex.loadMore()}
            onManage={openBatchAction}
          />
        </section>
      </div>

      <BatchDispositionManager
        batch={active ? selectedBatchContext?.batch ?? null : null}
        productVariantId={selectedBatchContext?.productVariantId ?? null}
        baseUomCode={selectedBatchContext?.baseUomCode ?? ""}
        selectedWarehouseId={locationId}
        batchDetail={selectedBatchContext?.detail ?? null}
        onOpenTransfers={onOpenTransfers}
        onOpenReservationOwner={onOpenReservationOwner}
        onClose={closeSelectedBatch}
        onRefreshBatch={async () => {
          await Promise.all([
            refreshSelectedBatch(),
            batchIndex.refresh(),
          ]);
        }}
        onChanged={async () => {
          await batchIndex.refresh();
          await onInventoryChanged();
        }}
      />
    </div>
  );
}
