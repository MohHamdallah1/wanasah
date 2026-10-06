import {
  RefreshCw,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Modal } from "@/components/ui/modal";
import { WholeProductQualityActionsPanel } from "@/features/inventory/quality/WholeProductQualityActionsPanel";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import {
  createInventoryBatchFocusNavigationState,
  createInventoryTabNavigationState,
} from "@/features/inventory/navigation";
import { CatalogLifecycleActions } from "@/features/catalog/lifecycle/CatalogLifecycleActions";
import { productCommercialStatus } from "@/features/catalog/status/productCommercialStatus";
import {
  parseCatalogPage,
  type CatalogVariant,
} from "@/features/catalog/contracts";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

export function ProductLifecycleManager({
  product,
  onClose,
  onChanged,
}: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const authFetch = useAuthFetch();
  const sequenceRef = useRef(0);
  const [variant, setVariant] = useState<CatalogVariant | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [qualityOpen, setQualityOpen] = useState(false);
  const productId = product?.id ?? null;

  const close = () => {
    setQualityOpen(false);
    onClose();
  };

  const openBlocker = (code: string) => {
    if (code === "OPEN_TRANSFER") {
      close();
      navigate("/inventory", {
        state: createInventoryTabNavigationState("transfers"),
      });
      return;
    }

    if (
      code === "ACTIVE_ROUTE_LOAD" ||
      code === "OPEN_CUSTODY" ||
      code === "OPEN_SHORTAGE"
    ) {
      close();
      navigate("/dispatch");
    }
  };

  useEffect(() => {
    setQualityOpen(false);
    const sequence = ++sequenceRef.current;
    const controller = new AbortController();

    setVariant(null);
    setLoadError(null);

    if (productId === null) {
      setLoading(false);
      return () => controller.abort();
    }

    setLoading(true);
    void (async () => {
      try {
        const page = parseCatalogPage(
          await authFetch(
            "/catalog/variants/resolve",
            {
              method: "POST",
              signal: controller.signal,
              body: JSON.stringify({ ids: [productId] }),
            },
          ),
        );

        if (
          page.items.length !== 1 ||
          page.has_more ||
          page.next_cursor !== null ||
          page.items[0].id !== productId
        ) {
          throw new Error("CATALOG_LIFECYCLE_SCOPE_MISMATCH");
        }

        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setVariant(page.items[0]);
      } catch (error) {
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setVariant(null);
        setLoadError(
          apiErrorMessage(
            error,
            t("products.lifecycleManager.loadFailed"),
          ),
        );
      } finally {
        if (!controller.signal.aborted && sequence === sequenceRef.current) {
          setLoading(false);
        }
      }
    })();

    return () => controller.abort();
  }, [authFetch, productId, reloadToken, t]);

  if (!product) return null;

  const commercial = variant ? productCommercialStatus(variant) : null;
  const statusDotClass = commercial?.tone === "good"
    ? "bg-emerald-500"
    : commercial?.tone === "warning"
      ? "bg-amber-500"
      : commercial?.tone === "blocked"
        ? "bg-rose-500"
        : "bg-slate-400";

  return (
    <Modal
      isOpen={product !== null}
      onClose={close}
      title={t("products.lifecycleManager.title", { name: product.name })}
      subtitle={commercial ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass}`} />
          <span className="font-black text-slate-700">{t(commercial.stateKey)}</span>
          <span aria-hidden="true" className="text-slate-300">•</span>
          <span className="font-semibold text-slate-500">{t(commercial.hintKey)}</span>
          {commercial.reasonKey ? (
            <>
              <span aria-hidden="true" className="text-slate-300">•</span>
              <span className="font-semibold text-slate-500">{t(commercial.reasonKey)}</span>
            </>
          ) : null}
          {commercial.secondaryReasonKey ? (
            <>
              <span aria-hidden="true" className="text-slate-300">•</span>
              <span className="font-semibold text-amber-700">{t(commercial.secondaryReasonKey)}</span>
            </>
          ) : null}
        </div>
      ) : undefined}
      maxWidth={qualityOpen ? "max-w-4xl" : "max-w-2xl"}
      bodyClassName="p-3 sm:p-4"
    >
      <div className="space-y-3">
        {loading ? (
          <div aria-live="polite" className="space-y-2">
            {[0, 1].map((item) => (
              <div key={item} className="h-24 animate-pulse rounded-2xl border border-slate-200 bg-slate-50" />
            ))}
            <span className="sr-only">{t("common.loading")}</span>
          </div>
        ) : null}

        {loadError ? (
          <div role="alert" className="flex flex-col gap-2 rounded-xl border border-rose-200 bg-rose-50/70 p-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-[11px] font-bold leading-5 text-rose-800">{loadError}</span>
            <button
              type="button"
              onClick={() => setReloadToken((current) => current + 1)}
              className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-rose-200 bg-white px-3 text-xs font-black text-rose-800 transition hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        {variant && qualityOpen ? (
          <WholeProductQualityActionsPanel
            productVariantId={variant.id}
            baseUomId={variant.base_uom.id}
            baseUomName={variant.base_uom.name}
            onBack={() => setQualityOpen(false)}
          />
        ) : null}

        {variant && !qualityOpen ? (
          <CatalogLifecycleActions
            variant={variant}
            simpleMode
            onManageBatchIssue={() => {
              close();
              navigate("/inventory", {
                state: createInventoryBatchFocusNavigationState({
                  variantId: variant.id,
                  productName: product.name,
                }),
              });
            }}
            onManageWholeProductIssue={() => setQualityOpen(true)}
            onOpenBlocker={openBlocker}
            onVariantChanged={async (updated) => {
              setVariant(updated);
              if (updated.operational_hold !== "RECALL") setQualityOpen(false);
              await onChanged();
            }}
          />
        ) : null}
      </div>
    </Modal>
  );
}
