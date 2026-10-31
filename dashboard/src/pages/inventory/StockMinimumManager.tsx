import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Search, Settings2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  parseBulkMinimumStockPlan,
  parseLiveStockFamilies,
  parseLiveStockPage,
  type BulkMinimumStockPlan,
  type LiveStockFamilyOption,
  type MinimumStockScope,
  type WarehouseProduct,
} from "./liveStock/contracts";

interface MinimumStockWarehouseOption {
  id: number;
  name: string;
  code: string;
}

interface Props {
  locations: MinimumStockWarehouseOption[];
  preferredLocationId?: number | null;
  onApplied: () => void;
}

interface PendingApplyCommand {
  payloadKey: string;
  requestId: string;
}

const codedError = (code: string): Error & { code: string } => {
  const error = new Error(code) as Error & { code: string };
  error.code = code;
  return error;
};

const cleanMinimum = (value: string): string | null => {
  const trimmed = value.trim();
  return /^\d+(?:\.\d{1,6})?$/.test(trimmed) ? trimmed : null;
};

const MAX_FAMILY_SELECTION = 100;
const MAX_PRODUCT_SELECTION = 200;

const toggleId = (values: number[], id: number, max: number): number[] => {
  if (values.includes(id)) return values.filter((value) => value !== id);
  if (values.length >= max) return values;
  return [...values, id].sort((a, b) => a - b);
};

export function StockMinimumManager({ locations, preferredLocationId = null, onApplied }: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();

  const preferredLocation =
    preferredLocationId !== null && locations.some((location) => location.id === preferredLocationId)
      ? preferredLocationId
      : locations[0]?.id ?? 0;
  const [open, setOpen] = useState(false);
  const [locationId, setLocationId] = useState(preferredLocation);
  const [scope, setScope] = useState<MinimumStockScope>("ALL");
  const [minimum, setMinimum] = useState("10");
  const [plan, setPlan] = useState<BulkMinimumStockPlan | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const pendingApplyCommand = useRef<PendingApplyCommand | null>(null);

  const [familySearch, setFamilySearch] = useState("");
  const [families, setFamilies] = useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [familyHasMore, setFamilyHasMore] = useState(false);
  const [familyIds, setFamilyIds] = useState<number[]>([]);

  const [productSearch, setProductSearch] = useState("");
  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [productLoading, setProductLoading] = useState(false);
  const [productError, setProductError] = useState<string | null>(null);
  const [productRetry, setProductRetry] = useState(0);
  const [productLoadingMore, setProductLoadingMore] = useState(false);
  const [productNextCursor, setProductNextCursor] = useState<string | null>(null);
  const [productIds, setProductIds] = useState<number[]>([]);
  const productLoadMoreRef = useRef<HTMLDivElement>(null);

  const invalidatePlan = useCallback(() => setPlan(null), []);
  const warehouseReady = locationId > 0 && locations.some((location) => location.id === locationId);

  useEffect(() => {
    if (locations.some((location) => location.id === locationId)) return;
    setLocationId(
      preferredLocationId !== null && locations.some((location) => location.id === preferredLocationId)
        ? preferredLocationId
        : locations[0]?.id ?? 0,
    );
  }, [locationId, locations, preferredLocationId]);

  useEffect(() => {
    invalidatePlan();
  }, [
    locationId,
    scope,
    minimum,
    familyIds,
    productIds,
    invalidatePlan,
  ]);

  useEffect(() => {
    if (!open) return;
    setPlan(null);
    setFamilyIds([]);
    setProductIds([]);
    setFamilySearch("");
    setProductSearch("");
    setFamilyHasMore(false);
    setProductNextCursor(null);
  }, [locationId, open]);

  useEffect(() => {
    if (!open || !warehouseReady || scope !== "FAMILY") return;

    const controller = new AbortController();
    setFamilyLoading(true);
    setFamilies([]);
    setFamilyHasMore(false);
    const timer = window.setTimeout(() => {
      const clean = familySearch.trim();
      if (clean.length === 1) {
        setFamilies([]);
        setFamilyHasMore(false);
        setFamilyLoading(false);
        return;
      }
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "100",
      });
      if (clean.length >= 2) params.set("search", clean);

      void authFetch(
        `/warehouse/inventory/families?${params.toString()}`,
        { signal: controller.signal },
      )
        .then((raw) => {
          if (!controller.signal.aborted) {
            const parsed = parseLiveStockFamilies(raw);
            setFamilies(parsed.items);
            setFamilyHasMore(parsed.has_more);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            setFamilies([]);
            setFamilyHasMore(false);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setFamilyLoading(false);
        });
    }, 250);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [authFetch, familySearch, locationId, open, scope, warehouseReady]);

  useEffect(() => {
    if (!open || !warehouseReady || scope !== "PRODUCT") return;

    const controller = new AbortController();
    setProductLoading(true);
    setProductError(null);
    setProducts([]);
    setProductNextCursor(null);
    const timer = window.setTimeout(() => {
      const clean = productSearch.trim();
      if (clean.length === 1) {
        setProducts([]);
        setProductNextCursor(null);
        setProductLoading(false);
        return;
      }
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
      });
      if (clean.length >= 2) params.set("search", clean);

      void authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`,
        { signal: controller.signal },
      )
        .then((raw) => {
          if (!controller.signal.aborted) {
            const parsed = parseLiveStockPage(raw);
            setProducts(parsed.items);
            setProductNextCursor(parsed.next_cursor);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            setProducts([]);
            setProductNextCursor(null);
            setProductError(apiErrorMessage(error, t("inventoryMinimum.errors.products")));
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setProductLoading(false);
        });
    }, 250);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [authFetch, locationId, open, productSearch, productRetry, scope, t, warehouseReady]);

  const loadMoreProducts = useCallback(async () => {
    if (
      !open ||
      scope !== "PRODUCT" ||
      !warehouseReady ||
      !productNextCursor ||
      productLoading ||
      productLoadingMore
    ) return;

    setProductLoadingMore(true);
    setProductError(null);
    try {
      const clean = productSearch.trim();
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
        cursor: productNextCursor,
      });
      if (clean.length >= 2) params.set("search", clean);
      const parsed = parseLiveStockPage(
        await authFetch(`/warehouse/inventory/cursor?${params.toString()}`),
      );
      setProducts((current) => {
        const merged = new Map(current.map((product) => [product.id, product]));
        parsed.items.forEach((product) => merged.set(product.id, product));
        return Array.from(merged.values());
      });
      setProductNextCursor(parsed.next_cursor);
    } catch (error: unknown) {
      setProductError(apiErrorMessage(error, t("inventoryMinimum.errors.products")));
    } finally {
      setProductLoadingMore(false);
    }
  }, [
    authFetch,
    locationId,
    open,
    productLoading,
    productLoadingMore,
    productNextCursor,
    productSearch,
    scope,
    t,
    warehouseReady,
  ]);

  useEffect(() => {
    if (
      scope !== "PRODUCT" ||
      productError !== null ||
      !productNextCursor ||
      productLoading ||
      productLoadingMore ||
      typeof IntersectionObserver === "undefined"
    ) return;
    const target = productLoadMoreRef.current;
    if (!target) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        void loadMoreProducts();
      }
    }, { rootMargin: "180px 0px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [
    loadMoreProducts,
    productError,
    productLoading,
    productLoadingMore,
    productNextCursor,
    scope,
  ]);

  const payload = useMemo(
    () => ({
      location_id: locationId,
      scope,
      family_ids: scope === "FAMILY" ? familyIds : [],
      product_variant_ids: scope === "PRODUCT" ? productIds : [],
      minimum_quantity: minimum.trim(),
      apply_mode: "OVERWRITE" as const,
    }),
    [familyIds, locationId, minimum, productIds, scope],
  );

  const scopeReady =
    warehouseReady && (
    scope === "ALL" ||
    (scope === "FAMILY" && familyIds.length > 0) ||
    (scope === "PRODUCT" && productIds.length > 0));
  const quantityReady = cleanMinimum(minimum) !== null;

  const preview = useCallback(async () => {
    if (!scopeReady || !quantityReady || previewing) return;
    setPreviewing(true);
    try {
      const raw = await authFetch(
        "/warehouse/inventory/minimum-stock/bulk/preview",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      const parsed = parseBulkMinimumStockPlan(raw);
      if (parsed.location_id !== locationId) {
        throw codedError("STOCK_MINIMUM_BULK_RESPONSE_INVALID");
      }
      setPlan(parsed);
    } catch (error: unknown) {
      setPlan(null);
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryMinimum.errors.preview"),
        ),
      );
    } finally {
      setPreviewing(false);
    }
  }, [
    authFetch,
    locationId,
    payload,
    previewing,
    quantityReady,
    scopeReady,
    t,
  ]);

  const hasConflict =
    plan !== null &&
    (plan.inactive_conflict_count > 0 ||
      plan.target_conflict_count > 0 ||
      plan.invalid_quantity_count > 0);

  const apply = useCallback(async () => {
    if (!scopeReady || !quantityReady || applying || hasConflict) return;
    const payloadKey = JSON.stringify(payload);
    const existingCommand = pendingApplyCommand.current;
    const command =
      existingCommand?.payloadKey === payloadKey
        ? existingCommand
        : {
            payloadKey,
            requestId: crypto.randomUUID(),
          };
    pendingApplyCommand.current = command;

    setApplying(true);
    try {
      const raw = await authFetch(
        "/warehouse/inventory/minimum-stock/bulk",
        {
          method: "PUT",
          body: JSON.stringify({
            ...payload,
            request_id: command.requestId,
          }),
        },
      );
      const applied = parseBulkMinimumStockPlan(raw);
      pendingApplyCommand.current = null;

      if (applied.affected_count === 0) {
        setPlan(applied);
        toast.info(t("inventoryMinimum.noChangesSame"));
        return;
      }

      toast.success(
        t("inventoryMinimum.applied", {
          count: applied.affected_count,
        }),
      );
      setOpen(false);
      setPlan(null);
      onApplied();
    } catch (error: unknown) {
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryMinimum.errors.apply"),
        ),
      );
    } finally {
      setApplying(false);
    }
  }, [
    applying,
    authFetch,
    hasConflict,
    onApplied,
    payload,
    quantityReady,
    scopeReady,
    t,
  ]);

  const scopeLabel =
    scope === "ALL"
      ? t("inventoryMinimum.scopeAll")
      : scope === "FAMILY"
        ? t("inventoryMinimum.selectedFamilies", {
            count: familyIds.length,
          })
        : t("inventoryMinimum.selectedProducts", {
            count: productIds.length,
          });

  const selectedCount =
    scope === "FAMILY"
      ? familyIds.length
      : scope === "PRODUCT"
        ? productIds.length
        : 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className="live-stock-minimum-manager-button"
        >
          <Settings2 className="h-4 w-4" />
          <span>{t("inventoryMinimum.button")}</span>
        </button>
      </DialogTrigger>

      <DialogContent
        dir={i18n.dir()}
        className="inventory-minimum-dialog"
      >
        <DialogHeader className="inventory-minimum-header">
          <DialogTitle>{t("inventoryMinimum.title")}</DialogTitle>
        </DialogHeader>

        <div className="inventory-minimum-body">
          <div className="inventory-minimum-context-row">
            <label className="inventory-minimum-warehouse-field">
              <span>{t("inventoryShell.warehouseSelectLabel")}</span>
              <select
                aria-label={t("inventoryShell.warehouseSelectLabel")}
                value={locationId || ""}
                onChange={(event) => {
                  setLocationId(Number(event.target.value));
                  pendingApplyCommand.current = null;
                }}
              >
                <option value="" disabled>{t("inventoryShell.chooseWarehouse")}</option>
                {locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.name} · {location.code}
                  </option>
                ))}
              </select>
            </label>

            <div className="inventory-minimum-scope" aria-label={t("inventoryMinimum.targetTitle")}>
              {(
                [
                  ["ALL", "scopeAll"],
                  ["FAMILY", "scopeFamily"],
                  ["PRODUCT", "scopeProduct"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  data-active={scope === value}
                  aria-pressed={scope === value}
                  onClick={() => setScope(value)}
                >
                  {scope === value && <Check className="h-3.5 w-3.5" />}
                  {t(`inventoryMinimum.${label}`)}
                </button>
              ))}
            </div>
          </div>

          <div className="inventory-minimum-workspace">
            <section className="inventory-minimum-target-panel" aria-labelledby="inventory-minimum-target-title">
              <div className="inventory-minimum-section-heading">
                <div>
                  <strong id="inventory-minimum-target-title">{t("inventoryMinimum.targetTitle")}</strong>
                  <span>{scopeLabel}</span>
                </div>
                {scope === "FAMILY" ? (
                  <small>{t("inventoryMinimum.selectionLimit", { count: MAX_FAMILY_SELECTION })}</small>
                ) : scope === "PRODUCT" ? (
                  <small>{t("inventoryMinimum.selectionLimit", { count: MAX_PRODUCT_SELECTION })}</small>
                ) : null}
              </div>

              <div className="inventory-minimum-target-area">
                {scope === "ALL" && (
                  <div className="inventory-minimum-all-scope">
                    <strong>{t("inventoryMinimum.scopeAll")}</strong>
                    <span>{t("inventoryMinimum.scopeAllHint")}</span>
                  </div>
                )}

                {scope === "FAMILY" && (
                  <div className="inventory-minimum-picker">
                    <div className="inventory-minimum-picker-head">
                      <div className="inventory-minimum-search">
                        <Search className="h-4 w-4" />
                        <input
                          type="search"
                          value={familySearch}
                          onChange={(event) => setFamilySearch(event.target.value)}
                          placeholder={t("inventoryMinimum.searchFamily")}
                          maxLength={100}
                        />
                      </div>
                      <span className="inventory-minimum-selected-count">
                        {t("inventoryMinimum.selectedCount", { count: familyIds.length })}
                      </span>
                      {familyIds.length > 0 && (
                        <button
                          type="button"
                          className="inventory-minimum-clear-selection"
                          onClick={() => setFamilyIds([])}
                        >
                          {t("inventoryMinimum.clearSelection")}
                        </button>
                      )}
                    </div>
                    <div className="inventory-minimum-options custom-scrollbar">
                      {familyLoading ? (
                        <div className="inventory-minimum-list-state">{t("common.loading")}</div>
                      ) : familySearch.trim().length === 1 ? (
                        <div className="inventory-minimum-list-state">{t("inventoryMinimum.searchMoreHint")}</div>
                      ) : families.length === 0 ? (
                        <div className="inventory-minimum-list-state">{t("inventoryMinimum.noResults")}</div>
                      ) : (
                        <>
                          {families.map((family) => {
                            const selected = familyIds.includes(family.id);
                            const limitReached = !selected && familyIds.length >= MAX_FAMILY_SELECTION;
                            return (
                              <button
                                key={family.id}
                                type="button"
                                data-active={selected}
                                aria-pressed={selected}
                                disabled={limitReached}
                                onClick={() =>
                                  setFamilyIds((current) =>
                                    toggleId(current, family.id, MAX_FAMILY_SELECTION),
                                  )
                                }
                              >
                                <span>
                                  <strong>{family.name}</strong>
                                  <small>{family.code}</small>
                                </span>
                                {selected && <Check className="h-4 w-4" />}
                              </button>
                            );
                          })}
                          {familyHasMore ? (
                            <p className="inventory-minimum-more-hint">{t("inventoryMinimum.familyMoreHint")}</p>
                          ) : null}
                        </>
                      )}
                    </div>
                  </div>
                )}

                {scope === "PRODUCT" && (
                  <div className="inventory-minimum-picker">
                    <div className="inventory-minimum-picker-head">
                      <div className="inventory-minimum-search">
                        <Search className="h-4 w-4" />
                        <input
                          type="search"
                          value={productSearch}
                          onChange={(event) => setProductSearch(event.target.value)}
                          placeholder={t("inventoryMinimum.searchProduct")}
                          maxLength={100}
                        />
                      </div>
                      <span className="inventory-minimum-selected-count">
                        {t("inventoryMinimum.selectedCount", { count: productIds.length })}
                      </span>
                      {productIds.length > 0 && (
                        <button
                          type="button"
                          className="inventory-minimum-clear-selection"
                          onClick={() => setProductIds([])}
                        >
                          {t("inventoryMinimum.clearSelection")}
                        </button>
                      )}
                    </div>
                    {productError ? <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs">
                      <p>{productError}</p>
                      <button type="button" className="mt-2 rounded border px-3 py-1 focus-visible:ring-2"
                        onClick={() => { if (productNextCursor) void loadMoreProducts(); else setProductRetry((value) => value + 1); }}>
                        {t("common.retry")}
                      </button>
                    </div> : null}
                    <div className="inventory-minimum-options inventory-minimum-product-grid custom-scrollbar">
                      {productLoading ? (
                        <div className="inventory-minimum-list-state">{t("common.loading")}</div>
                      ) : productSearch.trim().length === 1 ? (
                        <div className="inventory-minimum-list-state">{t("inventoryMinimum.searchMoreHint")}</div>
                      ) : productError && products.length === 0 ? null : products.length === 0 ? (
                        <div className="inventory-minimum-list-state">{t("inventoryMinimum.noResults")}</div>
                      ) : (
                        <>
                          {products.map((product) => {
                            const selected = productIds.includes(product.id);
                            const limitReached = !selected && productIds.length >= MAX_PRODUCT_SELECTION;
                            return (
                              <button
                                key={product.id}
                                type="button"
                                data-active={selected}
                                aria-pressed={selected}
                                disabled={limitReached}
                                onClick={() =>
                                  setProductIds((current) =>
                                    toggleId(current, product.id, MAX_PRODUCT_SELECTION),
                                  )
                                }
                              >
                                <span className="inventory-minimum-option-main">
                                  <strong>{product.name}</strong>
                                  <small>
                                    {product.sku || "—"} · {product.family_name}
                                  </small>
                                </span>
                                <span className="inventory-minimum-option-meta">
                                  <small>
                                    {t("inventoryMinimum.currentMinimum")}: {product.minimum_quantity} {product.display_uom_code}
                                  </small>
                                  {selected && <Check className="h-4 w-4" />}
                                </span>
                              </button>
                            );
                          })}
                          <div ref={productLoadMoreRef} className="inventory-minimum-load-more" aria-hidden={!productLoadingMore}>
                            {productLoadingMore ? t("inventoryMinimum.loadingMore") : null}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </section>

            <aside className="inventory-minimum-config-panel" aria-labelledby="inventory-minimum-settings-title">
              <div className="inventory-minimum-section-heading inventory-minimum-section-heading--compact">
                <div>
                  <strong id="inventory-minimum-settings-title">{t("inventoryMinimum.settingsTitle")}</strong>
                  {selectedCount > 0 ? <span>{scopeLabel}</span> : null}
                </div>
              </div>

              <div className="inventory-minimum-value-row">
                <label>
                  <span>{t("inventoryMinimum.valueLabel")}</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={minimum}
                    onChange={(event) => setMinimum(event.target.value)}
                    maxLength={24}
                  />
                </label>
                <div className="inventory-minimum-value-hints">
                  <p>{t("inventoryMinimum.unitHint")}</p>
                  <p>{t("inventoryMinimum.zeroHint")}</p>
                </div>
              </div>

              {plan && (
                <div
                  className="inventory-minimum-preview"
                  data-conflict={hasConflict ? "true" : "false"}
                >
                  <div>
                    <strong>{plan.matched_count}</strong>
                    <span>{t("inventoryMinimum.previewMatched", { count: plan.matched_count })}</span>
                  </div>
                  <div>
                    <strong>{plan.affected_count}</strong>
                    <span>{t("inventoryMinimum.previewAffected")}</span>
                  </div>
                  <div>
                    <strong>{plan.skipped_existing_count}</strong>
                    <span>{t("inventoryMinimum.previewSkipped")}</span>
                  </div>
                  <div className="inventory-minimum-conflict-breakdown">
                    <span data-active={plan.inactive_conflict_count > 0 ? "true" : "false"}>
                      {t("inventoryMinimum.conflictInactive")}: {plan.inactive_conflict_count}
                    </span>
                    <span data-active={plan.target_conflict_count > 0 ? "true" : "false"}>
                      {t("inventoryMinimum.conflictTarget")}: {plan.target_conflict_count}
                    </span>
                    <span data-active={plan.invalid_quantity_count > 0 ? "true" : "false"}>
                      {t("inventoryMinimum.conflictQuantity")}: {plan.invalid_quantity_count}
                    </span>
                  </div>
                  {hasConflict && (
                    <p>
                      {t("inventoryMinimum.previewConflict", {
                        count:
                          plan.inactive_conflict_count +
                          plan.target_conflict_count +
                          plan.invalid_quantity_count,
                      })}
                    </p>
                  )}
                </div>
              )}

              <DialogFooter className="inventory-minimum-actions">
                <button
                  type="button"
                  className="inventory-minimum-cancel"
                  onClick={() => setOpen(false)}
                  disabled={applying}
                >
                  <X className="h-3.5 w-3.5" />
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  className="inventory-minimum-preview-button"
                  onClick={() => void preview()}
                  disabled={!scopeReady || !quantityReady || previewing || applying}
                >
                  {previewing
                    ? t("common.loading")
                    : t("inventoryMinimum.previewOptional")}
                </button>
                <button
                  type="button"
                  className="inventory-minimum-apply"
                  onClick={() => void apply()}
                  disabled={
                    !scopeReady ||
                    !quantityReady ||
                    hasConflict ||
                    applying
                  }
                >
                  {applying
                    ? t("common.saving")
                    : t("inventoryMinimum.apply")}
                </button>
              </DialogFooter>
            </aside>
          </div>
        </div>

      </DialogContent>
    </Dialog>
  );
}