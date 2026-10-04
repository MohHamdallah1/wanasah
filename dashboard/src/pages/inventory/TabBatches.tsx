import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  PackageOpen,
  RefreshCcw,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { formatMoneyExact } from "@/lib/money";
import type { InventoryBatchFocusIntent } from "@/features/inventory/navigation";
import { BatchDispositionManager } from "./batches/BatchDispositionManager";
import type { BatchActionSnapshot } from "./batches/contracts";
import type { BatchSpecialTransferResult } from "./batches/batchSpecialTransferContract";
import { parseBatchStockSources } from "./batches/batchStockSourcesContract";
import {
  parseBatchDetailResponse,
  parseBatchProductPage,
  type WarehouseBatchDetailResponse,
  type WarehouseBatchInventoryItem,
  type WarehouseBatchProductOption,
} from "./liveStock/contracts";
import {
  compareQuantity,
  formatCommercialQuantity,
  subtractQuantity,
} from "@/lib/quantity";

interface Props {
  locationId: number;
  focus?: InventoryBatchFocusIntent | null;
  onFocusConsumed: () => void;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
}

const PAGE_SIZE = 50;
const BATCH_PAGE_SIZE = 100;

const codedError = (code: string): Error & { code: string } => {
  const error = new Error(code) as Error & { code: string };
  error.code = code;
  return error;
};

const dispositionTone = (
  value: WarehouseBatchInventoryItem["disposition"],
): string => {
  switch (value) {
    case "RECALLED":
      return "border-red-200 bg-red-50 text-red-700";
    case "BLOCKED":
      return "border-orange-200 bg-orange-50 text-orange-700";
    case "QUARANTINED":
      return "border-amber-200 bg-amber-50 text-amber-700";
    default:
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
};

export function TabBatches({
  locationId,
  focus = null,
  onFocusConsumed,
  onOpenTransfers,
}: Props) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const canManageDisposition =
    access.isCompanyAdmin || access.can("batch.disposition");
  const [focusVariantId, setFocusVariantId] = useState<number | null>(
    focus?.variantId ?? null,
  );
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [products, setProducts] = useState<WarehouseBatchProductOption[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [details, setDetails] = useState<WarehouseBatchDetailResponse | null>(null);
  const [selectedBatchContext, setSelectedBatchContext] = useState<{
    batch: BatchActionSnapshot;
    productVariantId: number;
    baseUomCode: string;
  } | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [loadingMoreDetails, setLoadingMoreDetails] = useState(false);
  const [detailsFailed, setDetailsFailed] = useState(false);

  const productRequestSeq = useRef(0);
  const productAbortRef = useRef<AbortController | null>(null);
  const detailRequestSeq = useRef(0);
  const detailAbortRef = useRef<AbortController | null>(null);

  const selectedProduct = useMemo(
    () => products.find((product) => product.id === selectedProductId) ?? null,
    [products, selectedProductId],
  );

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
          throw codedError("BATCH_STOCK_SOURCES_SCOPE_MISMATCH");
        }
        setSelectedBatchContext({
          batch: sources.batch,
          productVariantId: sources.product_variant_id,
          baseUomCode: sources.base_uom_code,
        });
        setFocusVariantId(null);
        onFocusConsumed();
      } catch (error: unknown) {
        if (error instanceof Error && error.name === "AbortError") return;
        toast.error(
          apiErrorMessage(error, t("inventoryBatches.errors.focus")),
        );
      }
    })();
    return () => controller.abort();
  }, [authFetch, focus?.batchId, focus?.variantId, onFocusConsumed, t]);

  useEffect(() => {
    setSearchInput("");
    setSearch("");
    setProducts([]);
    setCursor(null);
    setNextCursor(null);
    setSelectedProductId(null);
    setDetails(null);
    setSelectedBatchContext(null);
    setLoadingMoreDetails(false);
    setDetailsFailed(false);

    productRequestSeq.current += 1;
    productAbortRef.current?.abort();
    productAbortRef.current = null;
    detailRequestSeq.current += 1;
    detailAbortRef.current?.abort();
    detailAbortRef.current = null;
  }, [locationId]);

  useEffect(() => {
    if (!focus || focusVariantId === null) return;
    setSearchInput(focus.productName);
  }, [focus, focusVariantId, locationId]);

  useEffect(() => {
    if (
      focusVariantId === null ||
      !products.some((product) => product.id === focusVariantId)
    ) {
      return;
    }
    setSelectedProductId(focusVariantId);
    setFocusVariantId(null);
    onFocusConsumed();
  }, [focusVariantId, onFocusConsumed, products]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      const next = clean.length >= 2 ? clean : "";
      if (next === search) return;
      setProducts([]);
      setCursor(null);
      setNextCursor(null);
      setSelectedProductId(null);
      setDetails(null);
      setSelectedBatchContext(null);
      setLoadingMoreDetails(false);
      setDetailsFailed(false);
      setSearch(next);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search, searchInput]);

  const fetchProducts = useCallback(async () => {
    const requestSeq = ++productRequestSeq.current;
    productAbortRef.current?.abort();
    const controller = new AbortController();
    productAbortRef.current = controller;
    setLoadingProducts(true);

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: String(PAGE_SIZE),
      });
      if (cursor) params.set("cursor", cursor);
      if (search) params.set("search", search);

      const raw = await authFetch(
        `/warehouse/inventory/batch-products?${params.toString()}`,
        { signal: controller.signal },
      );
      if (requestSeq !== productRequestSeq.current) return;

      const page = parseBatchProductPage(raw);
      setProducts((current) => {
        if (!cursor) return page.items;
        const seen = new Set(current.map((item) => item.id));
        return [
          ...current,
          ...page.items.filter((item) => !seen.has(item.id)),
        ];
      });
      setNextCursor(page.next_cursor);

      if (!cursor && page.items.length > 0) {
        setSelectedProductId((current) => current ?? page.items[0].id);
      }
    } catch (error: unknown) {
      if (requestSeq !== productRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setProducts([]);
      setNextCursor(null);
      toast.error(
        apiErrorMessage(error, t("inventoryBatches.errors.products")),
      );
    } finally {
      if (productAbortRef.current === controller) {
        productAbortRef.current = null;
      }
      if (requestSeq === productRequestSeq.current) {
        setLoadingProducts(false);
      }
    }
  }, [authFetch, cursor, locationId, search, t]);

  useEffect(() => {
    void fetchProducts();
  }, [fetchProducts]);

  const fetchDetails = useCallback(async (
    pageCursor: string | null = null,
  ) => {
    if (!selectedProduct) {
      setDetails(null);
      setLoadingMoreDetails(false);
      setDetailsFailed(false);
      return;
    }

    const requestSeq = ++detailRequestSeq.current;
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;
    if (pageCursor) {
      setLoadingMoreDetails(true);
    } else {
      setLoadingMoreDetails(false);
      setLoadingDetails(true);
      setDetailsFailed(false);
    }

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: String(BATCH_PAGE_SIZE),
      });
      if (pageCursor) params.set("cursor", pageCursor);

      const raw = await authFetch(
        `/warehouse/inventory/${encodeURIComponent(
          String(selectedProduct.id),
        )}/batches?${params.toString()}`,
        { signal: controller.signal },
      );
      if (requestSeq !== detailRequestSeq.current) return;

      const parsed = parseBatchDetailResponse(raw);
      if (
        parsed.location_id !== locationId ||
        parsed.product_variant_id !== selectedProduct.id ||
        parsed.currency_code.toUpperCase() !==
          selectedProduct.currency_code.toUpperCase()
      ) {
        throw codedError("LIVE_STOCK_BATCH_SCOPE_MISMATCH");
      }

      setDetails((current) => {
        if (!pageCursor || current === null) return parsed;

        const seen = new Set(
          current.batches.map((batch) => batch.batch_id),
        );
        const appended = parsed.batches.filter(
          (batch) => !seen.has(batch.batch_id),
        );
        return {
          ...parsed,
          batches: [...current.batches, ...appended],
        };
      });
    } catch (error: unknown) {
      if (requestSeq !== detailRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (!pageCursor) {
        setDetails(null);
        setDetailsFailed(true);
      }
      toast.error(
        apiErrorMessage(error, t("inventoryBatches.errors.details")),
      );
    } finally {
      if (detailAbortRef.current === controller) {
        detailAbortRef.current = null;
      }
      if (requestSeq === detailRequestSeq.current) {
        if (pageCursor) {
          setLoadingMoreDetails(false);
        } else {
          setLoadingDetails(false);
        }
      }
    }
  }, [authFetch, locationId, selectedProduct, t]);

  useEffect(() => {
    void fetchDetails(null);
  }, [fetchDetails]);

  const formatDate = useCallback(
    (value: string | null): string => {
      if (!value) return "—";
      try {
        return new Intl.DateTimeFormat(locale, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          numberingSystem: "latn",
          timeZone: "UTC",
        }).format(new Date(`${value}T00:00:00Z`));
      } catch {
        return value;
      }
    },
    [locale],
  );

  const renderQuantity = useCallback(
    (value: string) => {
      if (!selectedProduct) return { primary: value, secondary: null };
      const displayName = t(
        `uom.${selectedProduct.display_uom_code}`,
        { defaultValue: selectedProduct.display_uom_code },
      );
      const baseName = t(
        `uom.${selectedProduct.base_uom_code}`,
        { defaultValue: selectedProduct.base_uom_code },
      );
      return formatCommercialQuantity(
        value,
        displayName,
        baseName,
        selectedProduct.display_factor_to_base,
      );
    },
    [selectedProduct, t],
  );

  return (
    <div className="inventory-batches-view min-h-0 flex-1">
      <aside className="inventory-batches-products">
        <div className="inventory-batches-search">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            type="search"
            value={searchInput}
            onChange={(event) => {
              setFocusVariantId(null);
              setSearchInput(event.target.value);
            }}
            placeholder={t("inventoryBatches.searchPlaceholder")}
            maxLength={100}
          />
        </div>

        <div className="inventory-batches-product-list custom-scrollbar">
          {loadingProducts && products.length === 0 && (
            <div className="inventory-batches-muted">
              <RefreshCcw className="h-4 w-4 animate-spin" />
              {t("common.loading")}
            </div>
          )}

          {!loadingProducts && products.length === 0 && (
            <div className="inventory-batches-muted">
              {t("inventoryBatches.noProducts")}
            </div>
          )}

          {products.map((product) => (
            <button
              key={product.id}
              type="button"
              className="inventory-batches-product"
              data-active={selectedProductId === product.id}
              onClick={() => {
                setSelectedBatchContext(null);
                setSelectedProductId(product.id);
              }}
            >
              <span className="inventory-batches-product-name">
                {product.name}
              </span>
              <span className="inventory-batches-product-meta">
                {product.sku ?? "—"} · {product.family_name}
              </span>
            </button>
          ))}

          {nextCursor && (
            <button
              type="button"
              className="inventory-batches-load-more"
              disabled={loadingProducts}
              onClick={() => setCursor(nextCursor)}
            >
              {loadingProducts
                ? t("common.loading")
                : t("inventoryBatches.loadMoreProducts")}
            </button>
          )}
        </div>
      </aside>

      <section className="inventory-batches-details">
        {focus ? (
          <div
            role="status"
            className="mx-3 mt-3 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2 text-[10px] font-bold leading-5 text-amber-950"
          >
            {t("inventoryBatches.issueFocusHint", {
              product: focus.productName,
            })}
          </div>
        ) : null}

        {!selectedProduct && (
          <div className="inventory-batches-empty">
            <PackageOpen className="h-7 w-7" />
            <span>{t("inventoryBatches.chooseProduct")}</span>
          </div>
        )}

        {selectedProduct && (
          <>
            <header className="inventory-batches-detail-header">
              <div>
                <h2>{selectedProduct.name}</h2>
                <p>
                  {selectedProduct.family_name}
                  {selectedProduct.sku ? ` · ${selectedProduct.sku}` : ""}
                </p>
              </div>
              {details && (
                <span className="inventory-batches-count">
                  {t(
                    details.has_more
                      ? "inventoryBatches.loadedBatchCount"
                      : "inventoryBatches.batchCount",
                    { count: details.batches.length },
                  )}
                </span>
              )}
            </header>

            {loadingDetails && (
              <div className="inventory-batches-empty">
                <RefreshCcw className="h-5 w-5 animate-spin" />
                <span>{t("inventoryLive.loadingBatches")}</span>
              </div>
            )}

            {!loadingDetails && detailsFailed && (
              <div className="inventory-batches-empty">
                <AlertTriangle className="h-6 w-6 text-red-500" />
                <span>{t("inventoryBatches.errors.details")}</span>
                <button type="button" onClick={() => void fetchDetails()}>
                  {t("common.retry")}
                </button>
              </div>
            )}

            {!loadingDetails &&
              !detailsFailed &&
              details &&
              details.batches.length === 0 && (
                <div className="inventory-batches-empty">
                  {t("inventoryLive.noBatchesInWarehouse")}
                </div>
              )}

            {!loadingDetails &&
              !detailsFailed &&
              details &&
              details.batches.length > 0 && (
                <div className="inventory-batches-table-wrap custom-scrollbar">
                  <table className="inventory-batches-table">
                    <thead>
                      <tr>
                        <th>{t("inventoryLive.batchNumber")}</th>
                        <th>{t("inventoryBatches.status")}</th>
                        <th>{t("inventoryLive.productionDate")}</th>
                        <th>{t("inventoryLive.expiryDate")}</th>
                        <th>{t("inventoryLive.onHand")}</th>
                        <th>{t("inventoryLive.reserved")}</th>
                        <th>{t("inventoryLive.availableForSale")}</th>
                        <th>{t("inventoryLive.unavailable")}</th>
                        <th>{t("inventoryBatches.restrictions")}</th>
                        <th>{t("inventoryLive.latestBatchPurchase")}</th>
                        {canManageDisposition ? (
                          <th>{t("inventoryBatches.action")}</th>
                        ) : null}
                      </tr>
                    </thead>
                    <tbody>
                      {details.batches.map((batch) => {
                        const otherRestricted = subtractQuantity(
                          batch.restricted_quantity,
                          batch.expiry_unavailable_quantity,
                        );
                        const dispositionRestrictionLabel =
                          batch.disposition === "RELEASED"
                            ? t("inventoryLive.restricted")
                            : t(
                                `inventoryBatches.disposition.restrictionLabels.${batch.disposition}`,
                              );
                        const restricted = [
                          ["expiry", batch.expiry_unavailable_quantity, t("inventoryLive.expiryUnavailable")],
                          ["restricted", otherRestricted, dispositionRestrictionLabel],
                          ["quarantine", batch.quarantined_quantity, t("inventoryLive.quarantined")],
                          ["blocked", batch.blocked_quantity, t("inventoryLive.blocked")],
                          ["recalled", batch.recalled_quantity, t("inventoryLive.recalled")],
                          ["damaged", batch.damaged_quantity, t("inventoryLive.damaged")],
                          ["disposal", batch.disposal_pending_quantity, t("inventoryLive.disposalPending")],
                        ].filter(([, value]) =>
                          compareQuantity(String(value), "0") > 0,
                        );

                        const purchaseUom = batch.latest_purchase_uom_code
                          ? t(`uom.${batch.latest_purchase_uom_code}`, {
                              defaultValue: batch.latest_purchase_uom_code,
                            })
                          : null;

                        return (
                          <tr key={batch.batch_id}>
                            <td>
                              <strong>{batch.batch_number}</strong>
                            </td>
                            <td>
                              <span
                                className={`inventory-batch-status ${dispositionTone(
                                  batch.disposition,
                                )}`}
                              >
                                {t(
                                  `inventoryLive.batchDisposition.${batch.disposition}`,
                                )}
                              </span>
                            </td>
                            <td>{formatDate(batch.production_date)}</td>
                            <td>
                              <div className="inventory-batches-expiry">
                                <span>{formatDate(batch.expiry_date)}</span>
                                {batch.days_to_expiry !== null && (
                                  <small
                                    data-expired={
                                      batch.days_to_expiry < 0
                                        ? "true"
                                        : "false"
                                    }
                                  >
                                    <CalendarDays className="h-3 w-3" />
                                    {batch.days_to_expiry < 0
                                      ? t("inventoryLive.expiredSince", {
                                          count: Math.abs(batch.days_to_expiry),
                                        })
                                      : batch.days_to_expiry === 0
                                        ? t("inventoryLive.expiresToday")
                                        : t("inventoryLive.daysRemaining", {
                                            count: batch.days_to_expiry,
                                          })}
                                  </small>
                                )}
                              </div>
                            </td>
                            <td>{renderQuantity(batch.on_hand_quantity).primary}</td>
                            <td>{renderQuantity(batch.reserved_quantity).primary}</td>
                            <td className="inventory-batches-sellable">
                              {renderQuantity(batch.available_for_sale_quantity).primary}
                            </td>
                            <td>
                              {compareQuantity(batch.unavailable_quantity, "0") > 0
                                ? renderQuantity(batch.unavailable_quantity).primary
                                : "—"}
                            </td>
                            <td>
                              {restricted.length > 0 ? (
                                <div className="inventory-batches-restrictions">
                                  {restricted.map(([key, value, label]) => (
                                    <span key={String(key)}>
                                      {label}: {renderQuantity(String(value)).primary}
                                    </span>
                                  ))}
                                  {batch.disposition !== "RELEASED" &&
                                  batch.disposition_reason ? (
                                    <small className="mt-0.5 block text-[9px] font-semibold text-slate-500">
                                      {t("inventoryBatches.disposition.reasonDisplay", {
                                        reason: batch.disposition_reason,
                                      })}
                                    </small>
                                  ) : null}
                                </div>
                              ) : (
                                <span className="inventory-batches-ok">
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  {t("inventoryLive.noRestrictedStock")}
                                </span>
                              )}
                            </td>
                            <td>
                              {batch.latest_purchase_cost && purchaseUom ? (
                                <div className="inventory-batches-cost">
                                  <strong>
                                    {formatMoneyExact(
                                      batch.latest_purchase_cost,
                                      details.currency_code,
                                      locale,
                                    )}
                                  </strong>
                                  <small>
                                    {t("inventoryLive.perUnit", {
                                      unit: purchaseUom,
                                    })}
                                    {batch.latest_purchase_date
                                      ? ` · ${formatDate(batch.latest_purchase_date)}`
                                      : ""}
                                  </small>
                                  <small>
                                    {t("inventoryLive.batchPurchaseEvents", {
                                      count: batch.purchase_event_count,
                                    })}
                                  </small>
                                </div>
                              ) : (
                                "—"
                              )}
                            </td>
                            {canManageDisposition ? (
                              <td>
                                <button
                                  type="button"
                                  onClick={() => {
                                    if (!selectedProduct) return;
                                    setSelectedBatchContext({
                                      batch,
                                      productVariantId: selectedProduct.id,
                                      baseUomCode: selectedProduct.base_uom_code,
                                    });
                                  }}
                                  className="whitespace-nowrap rounded-lg border border-slate-200 bg-white px-3 py-2 text-[10px] font-black text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300"
                                >
                                  {t("inventoryBatches.manageStatus")}
                                </button>
                              </td>
                            ) : null}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {details.has_more && details.next_cursor && (
                    <div className="inventory-batches-page-more">
                      <button
                        type="button"
                        className="inventory-batches-load-more"
                        disabled={loadingMoreDetails}
                        onClick={() => {
                          const next = details.next_cursor;
                          if (next) void fetchDetails(next);
                        }}
                      >
                        {loadingMoreDetails
                          ? t("common.loading")
                          : t("inventoryBatches.loadMoreBatches")}
                      </button>
                    </div>
                  )}
                </div>
              )}
          </>
        )}
      </section>

      <BatchDispositionManager
        batch={selectedBatchContext?.batch ?? null}
        productVariantId={
          selectedBatchContext?.productVariantId ?? null
        }
        baseUomCode={selectedBatchContext?.baseUomCode ?? ""}
        onOpenTransfers={onOpenTransfers}
        onClose={() => setSelectedBatchContext(null)}
        onChanged={async () => {
          if (selectedProduct) {
            await fetchDetails(null);
          }
        }}
      />
    </div>
  );
}
