import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw } from "lucide-react";
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

interface Props {
  locationId: number;
  focus?: InventoryBatchFocusIntent | null;
  onFocusConsumed: () => void;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
}

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
  focus = null,
  onFocusConsumed,
  onOpenTransfers,
  onOpenReservationOwner,
}: Props) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const canManageDisposition =
    access.isCompanyOwner || access.can("batch.disposition");

  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<BatchIndexFilterState>(
    DEFAULT_BATCH_INDEX_FILTERS,
  );
  const [expiryWarningDays, setExpiryWarningDays] = useState(
    DEFAULT_BATCH_EXPIRY_WARNING_DAYS,
  );
  const [families, setFamilies] = useState<BatchFilterFamilyOption[]>([]);
  const [products, setProducts] = useState<BatchFilterProductOption[]>([]);
  const [selectedBatchContext, setSelectedBatchContext] = useState<{
    batch: BatchActionSnapshot;
    productVariantId: number;
    baseUomCode: string;
  } | null>(null);

  const batchIndex = useBatchIndex({
    locationId,
    filters,
    expiryWarningDays,
  });

  const text = useCallback(
    (key: Parameters<typeof batchIndexText>[2], values: Record<string, unknown> = {}) =>
      batchIndexText(t, language, key, values),
    [language, t],
  );

  useEffect(() => {
    setSearchInput("");
    setFilters(DEFAULT_BATCH_INDEX_FILTERS);
    setFamilies([]);
    setProducts([]);
    setSelectedBatchContext(null);
  }, [locationId]);

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
    setFamilies((current) => mergeFamilies(current, batchIndex.items));
    setProducts((current) => mergeProducts(current, batchIndex.items));
  }, [batchIndex.items]);

  useEffect(() => {
    if (focus?.batchId === null || focus?.batchId === undefined) return;
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
        });
        onFocusConsumed();
      } catch (error: unknown) {
        if (error instanceof Error && error.name === "AbortError") return;
        toast.error(apiErrorMessage(error, t("inventoryBatches.errors.focus")));
      }
    })();
    return () => controller.abort();
  }, [authFetch, focus?.batchId, focus?.variantId, onFocusConsumed, t]);

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
    setSelectedBatchContext({
      batch: toBatchActionSnapshot(item),
      productVariantId: item.product_variant_id,
      baseUomCode: item.base_uom_code,
    });
  }, []);

  return (
    <div
      dir={i18n.dir()}
      className="inventory-batches-view min-h-0 flex-1 overflow-auto bg-slate-50/60 p-2 sm:p-3"
    >
      <div className="mx-auto flex w-full max-w-[1800px] flex-col gap-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-sm font-black text-slate-900">
              {t("inventory.tabs.batches", { defaultValue: language.startsWith("ar") ? "الدفعات" : "Batches" })}
            </h2>
            <p className="text-[10px] font-semibold text-slate-500">
              {text("loadedCount", { count: loadedCount })}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void batchIndex.refresh()}
            disabled={batchIndex.loading || batchIndex.summaryLoading}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-[11px] font-black text-slate-700 shadow-sm outline-none transition hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-slate-300"
          >
            <RefreshCcw
              aria-hidden="true"
              className={`h-3.5 w-3.5 ${batchIndex.loading ? "animate-spin" : ""}`}
            />
            {text("refresh")}
          </button>
        </div>

        {focus ? (
          <div
            role="status"
            className="rounded-xl border border-amber-200 bg-amber-50/80 px-3 py-2 text-[10px] font-bold leading-5 text-amber-950"
          >
            {text("focusHint")}
          </div>
        ) : null}

        <BatchIndexFilters
          t={t}
          language={language}
          filters={filters}
          searchInput={searchInput}
          onSearchInputChange={setSearchInput}
          onFiltersChange={setFilters}
          expiryWarningDays={expiryWarningDays}
          onExpiryWarningDaysChange={updateExpiryWarningDays}
          families={families}
          products={products}
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
          onRetry={() => void batchIndex.retryList()}
          onLoadMore={() => void batchIndex.loadMore()}
          onManage={openBatchAction}
        />
      </div>

      <BatchDispositionManager
        batch={selectedBatchContext?.batch ?? null}
        productVariantId={selectedBatchContext?.productVariantId ?? null}
        baseUomCode={selectedBatchContext?.baseUomCode ?? ""}
        onOpenTransfers={onOpenTransfers}
        onOpenReservationOwner={onOpenReservationOwner}
        onClose={() => setSelectedBatchContext(null)}
        onChanged={async () => {
          await batchIndex.refresh();
        }}
      />
    </div>
  );
}