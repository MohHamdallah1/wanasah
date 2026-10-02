import {
  History,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
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
} from "@/lib/durableOperations";
import { ProductBarcodeHistoryPanel } from "@/pages/products/barcode/ProductBarcodeHistoryPanel";
import { ProductBarcodeSimplePanel } from "@/pages/products/barcode/ProductBarcodeSimplePanel";
import { useIndependentPackageBarcode } from "@/pages/products/barcode/useIndependentPackageBarcode";
import { usePrimaryBarcodeReplacement } from "@/pages/products/barcode/usePrimaryBarcodeReplacement";
import {
  parseProductBarcodeMutation,
  parseProductBarcodes,
  type ProductBarcodeRecord,
  type SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  companyId: number | null;
  driverId: number | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

type BarcodeDeactivateBody = {
  expected_version: number;
  is_primary: false;
  valid_to: null;
  is_active: false;
};

export function ProductBarcodeManager({
  product,
  companyId,
  driverId,
  onClose,
  onChanged,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const isOnline = useNetworkStatus();
  const requestSequence =
    useRef(0);

  const [items, setItems] =
    useState<
      ProductBarcodeRecord[]
    >([]);
  const [loading, setLoading] =
    useState(false);
  const [
    loadingMore,
    setLoadingMore,
  ] = useState(false);
  const [
    loadReady,
    setLoadReady,
  ] = useState(false);
  const [
    loadError,
    setLoadError,
  ] = useState(false);
  const [
    nextCursor,
    setNextCursor,
  ] = useState<string | null>(
    null,
  );
  const [hasMore, setHasMore] =
    useState(false);
  const [
    reloadToken,
    setReloadToken,
  ] = useState(0);
  const [busy, setBusy] =
    useState(false);
  const [
    historyOpen,
    setHistoryOpen,
  ] = useState(false);

  const productId =
    product?.id ?? null;

  const updateScope =
    useCallback(
      (barcodeId: number) =>
        companyId !== null &&
        driverId !== null
          ? durableScope(
              companyId,
              driverId,
              "catalog-barcode-update",
              barcodeId,
            )
          : null,
      [companyId, driverId],
    );

  const reconcileDeactivation =
    useCallback(
      async (
        loaded:
          ProductBarcodeRecord[],
      ) => {
        for (const item of loaded) {
          const scope =
            updateScope(item.id);
          if (!scope) {
            continue;
          }

          const pending =
            await readDurableCommand<
              BarcodeDeactivateBody
            >(scope);
          if (
            pending &&
            !item.is_active &&
            pending.payload
              .is_active === false
          ) {
            completeDurableOperation(
              scope,
              pending.requestId,
            );
          }
        }
      },
      [updateScope],
    );

  useEffect(() => {
    const sequence =
      ++requestSequence.current;
    const controller =
      new AbortController();

    setHistoryOpen(false);

    if (productId === null) {
      setItems([]);
      setLoading(false);
      setLoadingMore(false);
      setLoadReady(false);
      setLoadError(false);
      setNextCursor(null);
      setHasMore(false);
      return () =>
        controller.abort();
    }

    setItems([]);
    setLoading(true);
    setLoadingMore(false);
    setLoadReady(false);
    setLoadError(false);
    setNextCursor(null);
    setHasMore(false);

    void (async () => {
      try {
        const parsed =
          parseProductBarcodes(
            await authFetch(
              "/catalog/variants/" +
                productId +
                "/barcodes?limit=100",
              {
                signal:
                  controller.signal,
              },
            ),
          );

        if (
          parsed.items.some(
            (item) =>
              item.product_variant_id !==
              productId,
          )
        ) {
          throw new Error(
            "PRODUCT_BARCODES_SCOPE_MISMATCH",
          );
        }

        if (
          controller.signal.aborted ||
          sequence !==
            requestSequence.current
        ) {
          return;
        }

        await reconcileDeactivation(
          parsed.items,
        );

        if (
          controller.signal.aborted ||
          sequence !==
            requestSequence.current
        ) {
          return;
        }

        setItems(parsed.items);
        setNextCursor(
          parsed.next_cursor,
        );
        setHasMore(
          parsed.has_more,
        );
        setLoadReady(true);
      } catch (error) {
        if (
          controller.signal.aborted ||
          sequence !==
            requestSequence.current
        ) {
          return;
        }

        setItems([]);
        setLoadReady(false);
        setLoadError(true);
        setNextCursor(null);
        setHasMore(false);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.barcodeManager.loadFailed",
            ),
          ),
        );
      } finally {
        if (
          !controller.signal
            .aborted &&
          sequence ===
            requestSequence.current
        ) {
          setLoading(false);
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [
    authFetch,
    productId,
    reloadToken,
    reconcileDeactivation,
    t,
  ]);

  const refreshBarcodes =
    useCallback(() => {
      setLoadReady(false);
      setReloadToken(
        (current) =>
          current + 1,
      );
    }, []);

  const baseCanMutate =
    loadReady &&
    !loadError &&
    !loading &&
    !busy &&
    isOnline &&
    companyId !== null &&
    driverId !== null;

  const {
    replacing,
    replacePrimaryBarcode,
  } =
    usePrimaryBarcodeReplacement({
      product,
      items,
      companyId,
      driverId,
      canMutate:
        baseCanMutate,
      refreshBarcodes,
      onChanged,
    });

  const {
    assigning,
    assignIndependent,
  } =
    useIndependentPackageBarcode({
      product,
      companyId,
      driverId,
      canMutate:
        baseCanMutate,
      refreshBarcodes,
      onChanged,
    });

  if (!product) {
    return null;
  }

  const canMutate =
    baseCanMutate &&
    !replacing &&
    !assigning;

  const loadMore =
    async () => {
      if (
        !nextCursor ||
        !hasMore ||
        loadingMore
      ) {
        return;
      }

      const sequence =
        requestSequence.current;
      setLoadingMore(true);
      try {
        const parsed =
          parseProductBarcodes(
            await authFetch(
              "/catalog/variants/" +
                product.id +
                "/barcodes?limit=100&cursor=" +
                encodeURIComponent(
                  nextCursor,
                ),
            ),
          );

        if (
          parsed.items.some(
            (item) =>
              item.product_variant_id !==
              product.id,
          ) ||
          sequence !==
            requestSequence.current
        ) {
          return;
        }

        const existingIds =
          new Set(
            items.map(
              (item) =>
                item.id,
            ),
          );
        if (
          parsed.items.some(
            (item) =>
              existingIds.has(
                item.id,
              ),
          )
        ) {
          throw new Error(
            "PRODUCT_BARCODES_CURSOR_DUPLICATE",
          );
        }

        await reconcileDeactivation(
          parsed.items,
        );

        if (
          sequence !==
          requestSequence.current
        ) {
          return;
        }

        setItems(
          (current) => [
            ...current,
            ...parsed.items,
          ],
        );
        setNextCursor(
          parsed.next_cursor,
        );
        setHasMore(
          parsed.has_more,
        );
      } catch (error) {
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.barcodeManager.loadFailed",
            ),
          ),
        );
      } finally {
        if (
          sequence ===
          requestSequence.current
        ) {
          setLoadingMore(false);
        }
      }
    };

  const removeBarcode =
    async (
      item: ProductBarcodeRecord,
    ): Promise<boolean> => {
      const scope =
        updateScope(item.id);
      if (
        !canMutate ||
        !item.is_active ||
        !scope
      ) {
        return false;
      }

      const body:
        BarcodeDeactivateBody = {
          expected_version:
            item.version,
          is_primary: false,
          valid_to: null,
          is_active: false,
        };

      setBusy(true);
      try {
        const existing =
          await readDurableCommand<
            BarcodeDeactivateBody
          >(scope);
        const command =
          existing ??
          (await getOrCreateDurableCommand(
            scope,
            body,
          ));

        parseProductBarcodeMutation(
          await authFetch(
            "/catalog/barcodes/" +
              item.id,
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
        toast.success(
          t(
            "products.barcodeManager.removed",
          ),
        );
        refreshBarcodes();
        await onChanged();
        return true;
      } catch (error) {
        const code =
          apiErrorCode(error);
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
        }

        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.barcodeManager.saveFailed",
            ),
          ),
        );
        return false;
      } finally {
        setBusy(false);
      }
    };

  const interfaceBusy =
    busy ||
    replacing ||
    assigning;

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => {
        if (!interfaceBusy) {
          onClose();
        }
      }}
      title={t(
        "products.barcodeManager.title",
        {
          name: product.name,
        },
      )}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-3">
        {loading ? (
          <div className="flex min-h-[180px] items-center justify-center rounded-2xl border border-slate-200 bg-white text-xs font-bold text-slate-400">
            {t("common.loading")}
          </div>
        ) : loadError ? (
          <div className="flex min-h-[180px] flex-col items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 px-6 text-center">
            <p className="text-xs font-black text-rose-800">
              {t(
                "products.barcodeManager.loadFailed",
              )}
            </p>
            <button
              type="button"
              onClick={
                refreshBarcodes
              }
              className="mt-3 rounded-lg border border-rose-200 bg-white px-3 py-2 text-[10px] font-black text-rose-700"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : loadReady ? (
          <>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() =>
                  setHistoryOpen(
                    (current) =>
                      !current,
                  )
                }
                aria-expanded={
                  historyOpen
                }
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-[10px] font-black text-slate-600 transition hover:bg-slate-50 hover:text-slate-900"
              >
                <History className="h-3.5 w-3.5" />
                {t(
                  "products.barcodeManager.history",
                )}
              </button>
            </div>

            <ProductBarcodeSimplePanel
              product={product}
              items={items}
              canMutate={
                canMutate
              }
              busy={
                interfaceBusy
              }
              onReplace={
                replacePrimaryBarcode
              }
              onAssignIndependentPackage={
                assignIndependent
              }
            />

            {historyOpen ? (
              <ProductBarcodeHistoryPanel
                product={
                  product
                }
                items={items}
                canMutate={
                  canMutate
                }
                busy={
                  interfaceBusy
                }
                hasMore={
                  hasMore
                }
                loadingMore={
                  loadingMore
                }
                onClose={() =>
                  setHistoryOpen(
                    false,
                  )
                }
                onLoadMore={() =>
                  void loadMore()
                }
                onReuse={
                  replacePrimaryBarcode
                }
                onRemove={
                  removeBarcode
                }
              />
            ) : null}
          </>
        ) : null}
      </div>
    </Modal>
  );
}
