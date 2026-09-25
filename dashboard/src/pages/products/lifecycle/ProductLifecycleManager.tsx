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
      maxWidth="max-w-4xl"
    >
      <div className="space-y-4">
        {loading ? (
          <div className="rounded-xl bg-slate-50 p-4 text-sm font-bold text-slate-500">
            {t(
              "common.loading",
            )}
          </div>
        ) : null}

        {loadError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-rose-50 p-4"
          >
            <span className="text-xs font-bold leading-6 text-rose-800">
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
              className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
            >
              {t(
                "common.retry",
              )}
            </button>
          </div>
        ) : null}

        {variant ? (
          <CatalogLifecycleActions
            variant={variant}
            onVariantChanged={async (
              updated,
            ) => {
              setVariant(updated);
              await onChanged();
            }}
          />
        ) : null}
      </div>
    </Modal>
  );
}
