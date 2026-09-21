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

export function StockMinimumManager({ locationId, onApplied }: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();

  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<MinimumStockScope>("ALL");
  const [applyMode, setApplyMode] =
    useState<MinimumStockApplyMode>("ONLY_UNSET");
  const [minimum, setMinimum] = useState("10");
  const [plan, setPlan] = useState<BulkMinimumStockPlan | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);

  const [familySearch, setFamilySearch] = useState("");
  const [families, setFamilies] = useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [familyId, setFamilyId] = useState<number | null>(null);

  const [productSearch, setProductSearch] = useState("");
  const [products, setProducts] = useState<WarehouseProduct[]>([]);
  const [productLoading, setProductLoading] = useState(false);
  const [productId, setProductId] = useState<number | null>(null);

  const selectedFamily = useMemo(
    () => families.find((item) => item.id === familyId) ?? null,
    [families, familyId],
  );
  const selectedProduct = useMemo(
    () => products.find((item) => item.id === productId) ?? null,
    [products, productId],
  );

  const invalidatePlan = useCallback(() => setPlan(null), []);

  useEffect(() => {
    invalidatePlan();
  }, [scope, applyMode, minimum, familyId, productId, invalidatePlan]);

  useEffect(() => {
    if (!open) return;
    setPlan(null);
  }, [locationId, open]);

  useEffect(() => {
    if (!open || scope !== "FAMILY") return;

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const clean = familySearch.trim();
      if (clean.length === 1) {
        setFamilies([]);
        return;
      }

      setFamilyLoading(true);
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
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
    const timer = window.setTimeout(() => {
      const clean = productSearch.trim();
      if (clean.length === 1) {
        setProducts([]);
        return;
      }

      setProductLoading(true);
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
      family_id: scope === "FAMILY" ? familyId : null,
      product_variant_id: scope === "PRODUCT" ? productId : null,
      minimum_quantity: minimum.trim(),
      apply_mode: applyMode,
    }),
    [applyMode, familyId, locationId, minimum, productId, scope],
  );

  const scopeReady =
    scope === "ALL" ||
    (scope === "FAMILY" && familyId !== null) ||
    (scope === "PRODUCT" && productId !== null);
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
    if (!plan || hasConflict || applying) return;
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
  }, [applying, authFetch, hasConflict, onApplied, payload, plan, t]);

  const scopeLabel =
    scope === "ALL"
      ? t("inventoryMinimum.scopeAll")
      : scope === "FAMILY"
        ? selectedFamily?.name ?? t("inventoryMinimum.scopeFamily")
        : selectedProduct?.name ?? t("inventoryMinimum.scopeProduct");

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
        className="inventory-minimum-dialog sm:max-w-lg"
      >
        <DialogHeader>
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
                onClick={() => {
                  setScope(value);
                  if (value !== "FAMILY") setFamilyId(null);
                  if (value !== "PRODUCT") setProductId(null);
                }}
              >
                {scope === value && <Check className="h-3.5 w-3.5" />}
                {t(`inventoryMinimum.${label}`)}
              </button>
            ))}
          </div>

          {scope === "FAMILY" && (
            <div className="inventory-minimum-picker">
              <div className="inventory-minimum-search">
                <Search className="h-3.5 w-3.5" />
                <input
                  type="search"
                  value={familySearch}
                  onChange={(event) => setFamilySearch(event.target.value)}
                  placeholder={t("inventoryMinimum.searchFamily")}
                />
              </div>
              <div className="inventory-minimum-options custom-scrollbar">
                {familyLoading ? (
                  <span>{t("common.loading")}</span>
                ) : (
                  families.map((family) => (
                    <button
                      key={family.id}
                      type="button"
                      data-active={family.id === familyId}
                      onClick={() => setFamilyId(family.id)}
                    >
                      <span>
                        <strong>{family.name}</strong>
                        <small>{family.code}</small>
                      </span>
                      {family.id === familyId && (
                        <Check className="h-3.5 w-3.5" />
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}

          {scope === "PRODUCT" && (
            <div className="inventory-minimum-picker">
              <div className="inventory-minimum-search">
                <Search className="h-3.5 w-3.5" />
                <input
                  type="search"
                  value={productSearch}
                  onChange={(event) => setProductSearch(event.target.value)}
                  placeholder={t("inventoryMinimum.searchProduct")}
                />
              </div>
              <div className="inventory-minimum-options custom-scrollbar">
                {productLoading ? (
                  <span>{t("common.loading")}</span>
                ) : (
                  products.map((product) => (
                    <button
                      key={product.id}
                      type="button"
                      data-active={product.id === productId}
                      onClick={() => setProductId(product.id)}
                    >
                      <span>
                        <strong>{product.name}</strong>
                        <small>
                          {product.sku} · {product.family_name}
                        </small>
                      </span>
                      {product.id === productId && (
                        <Check className="h-3.5 w-3.5" />
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}

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
              data-active={applyMode === "ONLY_UNSET"}
              onClick={() => setApplyMode("ONLY_UNSET")}
            >
              {applyMode === "ONLY_UNSET" && <Check className="h-3.5 w-3.5" />}
              <span>
                <strong>{t("inventoryMinimum.onlyUnset")}</strong>
                <small>{t("inventoryMinimum.onlyUnsetHint")}</small>
              </span>
            </button>
            <button
              type="button"
              data-active={applyMode === "OVERWRITE"}
              onClick={() => setApplyMode("OVERWRITE")}
            >
              {applyMode === "OVERWRITE" && <Check className="h-3.5 w-3.5" />}
              <span>
                <strong>{t("inventoryMinimum.overwrite")}</strong>
                <small>{t("inventoryMinimum.overwriteHint")}</small>
              </span>
            </button>
          </div>

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
              : t("inventoryMinimum.preview")}
          </button>
          <button
            type="button"
            className="inventory-minimum-apply"
            onClick={() => void apply()}
            disabled={
              !plan ||
              hasConflict ||
              applying ||
              plan.affected_count === 0
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
