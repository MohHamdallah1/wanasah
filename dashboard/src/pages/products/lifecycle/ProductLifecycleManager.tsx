import {
  RefreshCw,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  apiErrorMessage,
} from "@/lib/apiErrors";
import { CatalogLifecycleActions } from "@/pages/inventory/catalog/CatalogLifecycleActions";
import {
  parseCatalogPage,
  type CatalogVariant,
} from "@/pages/inventory/catalog/contracts";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductLifecycleStatusRail } from "@/pages/products/lifecycle/ProductLifecycleStatusRail";

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
  const authFetch = useAuthFetch();
  const sequenceRef =
    useRef(0);
  const [
    variant,
    setVariant,
  ] =
    useState<CatalogVariant | null>(
      null,
    );
  const [
    loading,
    setLoading,
  ] = useState(false);
  const [
    loadError,
    setLoadError,
  ] = useState<string | null>(
    null,
  );
  const [
    reloadToken,
    setReloadToken,
  ] = useState(0);

  const productId =
    product?.id ?? null;

  useEffect(() => {
    const sequence =
      ++sequenceRef.current;
    const controller =
      new AbortController();

    setVariant(null);
    setLoadError(null);

    if (productId === null) {
      setLoading(false);
      return () =>
        controller.abort();
    }

    setLoading(true);
    void (async () => {
      try {
        const page =
          parseCatalogPage(
            await authFetch(
              "/catalog/variants/resolve",
              {
                method: "POST",
                signal:
                  controller.signal,
                body: JSON.stringify({
                  ids: [
                    productId,
                  ],
                }),
              },
            ),
          );

        if (
          page.items.length !== 1 ||
          page.has_more ||
          page.next_cursor !== null ||
          page.items[0].id !==
            productId
        ) {
          throw new Error(
            "CATALOG_LIFECYCLE_SCOPE_MISMATCH",
          );
        }

        if (
          controller.signal.aborted ||
          sequence !==
            sequenceRef.current
        ) {
          return;
        }

        setVariant(
          page.items[0],
        );
      } catch (error) {
        if (
          controller.signal.aborted ||
          sequence !==
            sequenceRef.current
        ) {
          return;
        }
        setVariant(null);
        setLoadError(
          apiErrorMessage(
            error,
            t(
              "products.lifecycleManager.loadFailed",
            ),
          ),
        );
      } finally {
        if (
          !controller.signal.aborted &&
          sequence ===
            sequenceRef.current
        ) {
          setLoading(false);
        }
      }
    })();

    return () =>
      controller.abort();
  }, [
    authFetch,
    productId,
    reloadToken,
    t,
  ]);

  if (!product) {
    return null;
  }

  return (
    <Modal
      isOpen={product !== null}
      onClose={onClose}
      title={t(
        "products.lifecycleManager.title",
        {
          name:
            product.name,
        },
      )}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-3">
        {loading ? (
          <div
            aria-live="polite"
            className="grid gap-2 sm:grid-cols-3"
          >
            {[0, 1, 2].map((item) => (
              <div
                key={item}
                className="h-14 animate-pulse rounded-xl border border-slate-200 bg-slate-50"
              />
            ))}
            <span className="sr-only">
              {t(
                "common.loading",
              )}
            </span>
          </div>
        ) : null}

        {loadError ? (
          <div
            role="alert"
            className="flex flex-col gap-2 rounded-xl border border-rose-200 bg-rose-50/70 p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="text-[11px] font-bold leading-5 text-rose-800">
              {loadError}
            </span>
            <button
              type="button"
              onClick={() =>
                setReloadToken(
                  (current) =>
                    current + 1,
                )
              }
              className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-rose-200 bg-white px-3 text-xs font-black text-rose-800 transition hover:bg-rose-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t(
                "common.retry",
              )}
            </button>
          </div>
        ) : null}

        {variant ? (
          <>
            <ProductLifecycleStatusRail
              variant={variant}
            />

            <div className="products-lifecycle-actions-scope rounded-xl border border-slate-200 bg-white p-3 [&>section]:border-0 [&>section]:p-0 [&>section>div:first-child]:justify-start [&>section>div:first-child>div:first-child]:hidden [&_button]:min-h-9 [&_input]:bg-slate-50 [&_input]:transition [&_input:focus]:bg-white">
              <CatalogLifecycleActions
                variant={variant}
                onVariantChanged={async (
                  updated,
                ) => {
                  setVariant(updated);
                  await onChanged();
                }}
              />
            </div>
          </>
        ) : null}
      </div>
    </Modal>
  );
}
