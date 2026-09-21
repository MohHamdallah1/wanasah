import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Search, Settings2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
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
  type MinimumStockApplyMode,
  type MinimumStockScope,
  type WarehouseProduct,
} from "./liveStock/contracts";

interface Props {
  locationId: number;
  onApplied: () => void;
}

const cleanMinimum = (value: string): string | null => {
  const trimmed = value.trim();
  return /^\d+(?:\.\d{1,6})?$/.test(trimmed) ? trimmed : null;
};

const toggleId = (values: number[], id: number): number[] =>
  values.includes(id)
    ? values.filter((value) => value !== id)
    : [...values, id].sort((a, b) => a - b);

export function StockMinimumManager({ locationId, onApplied }: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();

  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<MinimumStockScope>("ALL");
  const [applyMode, setApplyMode] =
    useState<MinimumStockApplyMode>("OVERWRITE");
  const [minimum, setMinimum] = useState("10");
  const [plan, setPlan] = useState<BulkMinimumStockPlan | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);

  const [familySearch, setFamilySearch] = useState("");
  const [families, setFamilies] = useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [familyIds, setFamilyIds] = useState<number[]>([]);

  const [productSearch, setProductSearch] = useState("");
  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [productLoading, setProductLoading] = useState(false);
  const [productIds, setProductIds] = useState<number[]>([]);

  const invalidatePlan = useCallback(() => setPlan(null), []);

  useEffect(() => {
    invalidatePlan();
  }, [
    scope,
    applyMode,
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
  }, [locationId, open]);

  useEffect(() => {
    if (!open || scope !== "FAMILY") return;

    const controller = new AbortController();
    setFamilyLoading(true);
    const timer = window.setTimeout(() => {
      const clean = familySearch.trim();
      if (clean.length === 1) {
        setFamilies([]);
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
            setFamilies(parseLiveStockFamilies(raw).items);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            setFamilies([]);
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
  }, [authFetch, familySearch, locationId, open, scope]);

  useEffect(() => {
    if (!open || scope !== "PRODUCT") return;

    const controller = new AbortController();
    setProductLoading(true);
    const timer = window.setTimeout(() => {
      const clean = productSearch.trim();
      if (clean.length === 1) {
        setProducts([]);
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
            setProducts(parseLiveStockPage(raw).items);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            setProducts([]);
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
  }, [authFetch, locationId, open, productSearch, scope]);

  const payload = useMemo(
    () => ({
      location_id: locationId,
      scope,
      family_ids: scope === "FAMILY" ? familyIds : [],
      product_variant_ids: scope === "PRODUCT" ? productIds : [],
      minimum_quantity: minimum.trim(),
      apply_mode: applyMode,
    }),
    [applyMode, familyIds, locationId, minimum, productIds, scope],
  );

  const scopeReady =
    scope === "ALL" ||
    (scope === "FAMILY" && familyIds.length > 0) ||
    (scope === "PRODUCT" && productIds.length > 0);
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
        throw new Error("STOCK_MINIMUM_BULK_RESPONSE_INVALID");
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
    setApplying(true);
    try {
      const raw = await authFetch(
        "/warehouse/inventory/minimum-stock/bulk",
        {
          method: "PUT",
          body: JSON.stringify({
            ...payload,
            request_id: crypto.randomUUID(),
          }),
        },
      );
      const applied = parseBulkMinimumStockPlan(raw);

      if (applied.affected_count === 0) {
        setPlan(applied);
        if (
          applyMode === "ONLY_UNSET" &&
          applied.skipped_existing_count > 0
        ) {
          toast.info(
            t("inventoryMinimum.noChangesExisting", {
              count: applied.skipped_existing_count,
            }),
          );
        } else {
          toast.info(t("inventoryMinimum.noChangesSame"));
        }
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
    applyMode,
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
          <DialogDescription>
            {t("inventoryMinimum.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="inventory-minimum-body">
          <div className="inventory-minimum-scope">
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
                onClick={() => setScope(value)}
              >
                {scope === value && <Check className="h-3.5 w-3.5" />}
                {t(`inventoryMinimum.${label}`)}
              </button>
            ))}
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
                  <Search className="h-3.5 w-3.5" />
                  <input
                    type="search"
                    value={familySearch}
                    onChange={(event) => setFamilySearch(event.target.value)}
                    placeholder={t("inventoryMinimum.searchFamily")}
                  />
                </div>
                <span className="inventory-minimum-selected-count">
                  {t("inventoryMinimum.selectedCount", {
                    count: familyIds.length,
                  })}
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
                  <span>{t("common.loading")}</span>
                ) : (
                  families.map((family) => {
                    const selected = familyIds.includes(family.id);
                    return (
                      <button
                        key={family.id}
                        type="button"
                        data-active={selected}
                        onClick={() =>
                          setFamilyIds((current) =>
                            toggleId(current, family.id),
                          )
                        }
                      >
                        <span>
                          <strong>{family.name}</strong>
                          <small>{family.code}</small>
                        </span>
                        {selected && <Check className="h-3.5 w-3.5" />}
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {scope === "PRODUCT" && (
            <div className="inventory-minimum-picker">
              <div className="inventory-minimum-picker-head">
                <div className="inventory-minimum-search">
                  <Search className="h-3.5 w-3.5" />
                  <input
                    type="search"
                    value={productSearch}
                    onChange={(event) => setProductSearch(event.target.value)}
                    placeholder={t("inventoryMinimum.searchProduct")}
                  />
                </div>
                <span className="inventory-minimum-selected-count">
                  {t("inventoryMinimum.selectedCount", {
                    count: productIds.length,
                  })}
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
              <div className="inventory-minimum-options custom-scrollbar">
                {productLoading ? (
                  <span>{t("common.loading")}</span>
                ) : (
                  products.map((product) => {
                    const selected = productIds.includes(product.id);
                    return (
                      <button
                        key={product.id}
                        type="button"
                        data-active={selected}
                        onClick={() =>
                          setProductIds((current) =>
                            toggleId(current, product.id),
                          )
                        }
                      >
                        <span>
                          <strong>{product.name}</strong>
                          <small>
                            {product.sku} · {product.family_name}
                          </small>
                        </span>
                        {selected && <Check className="h-3.5 w-3.5" />}
                      </button>
                    );
                  })
                )}
              </div>
            </div>
          )}
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
            <p>{t("inventoryMinimum.unitHint")}</p>
          </div>

          <div className="inventory-minimum-mode">
            <button
              type="button"
              data-active={applyMode === "OVERWRITE"}
              onClick={() => setApplyMode("OVERWRITE")}
            >
              {applyMode === "OVERWRITE" && <Check className="h-3.5 w-3.5" />}
              <span>
                <strong>{t("inventoryMinimum.applyToSelection")}</strong>
                <small>{t("inventoryMinimum.applyToSelectionHint")}</small>
              </span>
            </button>
            <button
              type="button"
              data-active={applyMode === "ONLY_UNSET"}
              onClick={() => setApplyMode("ONLY_UNSET")}
            >
              {applyMode === "ONLY_UNSET" && <Check className="h-3.5 w-3.5" />}
              <span>
                <strong>{t("inventoryMinimum.fillMissingOnly")}</strong>
                <small>{t("inventoryMinimum.fillMissingOnlyHint")}</small>
              </span>
            </button>
          </div>

          {selectedCount > 0 && (
            <div className="inventory-minimum-selection-summary">
              {scopeLabel}
            </div>
          )}

          {plan && (
            <div
              className="inventory-minimum-preview"
              data-conflict={hasConflict ? "true" : "false"}
            >
              <div>
                <strong>{scopeLabel}</strong>
                <span>
                  {t("inventoryMinimum.previewMatched", {
                    count: plan.matched_count,
                  })}
                </span>
              </div>
              <div>
                <strong>{plan.affected_count}</strong>
                <span>{t("inventoryMinimum.previewAffected")}</span>
              </div>
              {plan.skipped_existing_count > 0 && (
                <div>
                  <strong>{plan.skipped_existing_count}</strong>
                  <span>{t("inventoryMinimum.previewSkipped")}</span>
                </div>
              )}
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
        </div>

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
      </DialogContent>
    </Dialog>
  );
}
