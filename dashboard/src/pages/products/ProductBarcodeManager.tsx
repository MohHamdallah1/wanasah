import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

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
  type DurableCommand,
} from "@/lib/durableOperations";
import {
  parseProductBarcodeMutation,
  parseProductBarcodes,
  type ProductBarcodeRecord,
  type ProductBarcodeType,
  type SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  companyId: number | null;
  driverId: number | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

type BarcodeCreateBody = {
  uom_id: number;
  barcode: string;
  barcode_type: ProductBarcodeType;
  is_primary: boolean;
  valid_from: null;
  valid_to: null;
};

type BarcodeDeactivateBody = {
  expected_version: number;
  is_primary: false;
  valid_to: null;
  is_active: false;
};

const isBarcodeCreateBody = (
  value: unknown
): value is BarcodeCreateBody => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const row = value as Record<
    string,
    unknown
  >;
  return (
    typeof row.uom_id === "number" &&
    Number.isInteger(row.uom_id) &&
    row.uom_id > 0 &&
    typeof row.barcode === "string" &&
    row.barcode.length > 0 &&
    [
      "EAN8",
      "EAN13",
      "UPC_A",
      "GTIN14",
      "GS1_128",
      "INTERNAL",
    ].includes(
      String(row.barcode_type)
    ) &&
    typeof row.is_primary ===
      "boolean" &&
    row.valid_from === null &&
    row.valid_to === null
  );
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
  const requestSequence = useRef(0);

  const [items, setItems] = useState<
    ProductBarcodeRecord[]
  >([]);
  const [loading, setLoading] =
    useState(false);
  const [loadingMore, setLoadingMore] =
    useState(false);
  const [loadReady, setLoadReady] =
    useState(false);
  const [loadError, setLoadError] =
    useState(false);
  const [nextCursor, setNextCursor] =
    useState<string | null>(null);
  const [hasMore, setHasMore] =
    useState(false);
  const [reloadToken, setReloadToken] =
    useState(0);
  const [busy, setBusy] =
    useState(false);
  const [barcode, setBarcode] =
    useState("");
  const [barcodeType, setBarcodeType] =
    useState<ProductBarcodeType>(
      "INTERNAL"
    );
  const [target, setTarget] =
    useState<"base" | "package">(
      "base"
    );
  const [isPrimary, setIsPrimary] =
    useState(false);
  const [
    pendingCreate,
    setPendingCreate,
  ] = useState<
    DurableCommand<BarcodeCreateBody> | null
  >(null);
  const [
    pendingCreateBlocked,
    setPendingCreateBlocked,
  ] = useState(false);

  const productId =
    product?.id ?? null;
  const baseUomId =
    product?.base_uom_id ?? null;
  const packageUomId =
    product?.package_uom_id ?? null;

  const createScope = useCallback(
    (productId: number) =>
      companyId !== null &&
      driverId !== null
        ? durableScope(
            companyId,
            driverId,
            "catalog-barcode-create-v2",
            productId
          )
        : null,
    [companyId, driverId],
  );

  const updateScope = useCallback(
    (barcodeId: number) =>
      companyId !== null &&
      driverId !== null
        ? durableScope(
            companyId,
            driverId,
            "catalog-barcode-update",
            barcodeId
          )
        : null,
    [companyId, driverId],
  );

  const reconcileDeactivation =
    useCallback(
      async (
        loaded:
          ProductBarcodeRecord[]
      ) => {
        for (const item of loaded) {
          const scope =
            updateScope(item.id);
          if (!scope) continue;
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
              pending.requestId
            );
          }
        }
      },
      [updateScope],
    );

  useEffect(() => {
    const productId =
      product?.id ?? null;
    const sequence =
      ++requestSequence.current;
    const controller =
      new AbortController();

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
              }
            )
          );

        if (
          parsed.items.some(
            (item) =>
              item.product_variant_id !==
              productId
          )
        ) {
          throw new Error(
            "PRODUCT_BARCODES_SCOPE_MISMATCH"
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
          parsed.items
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
          parsed.next_cursor
        );
        setHasMore(
          parsed.has_more
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
              "products.barcodeManager.loadFailed"
            )
          )
        );
      } finally {
        if (
          !controller.signal.aborted &&
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
    companyId,
    driverId,
    product?.id,
    reloadToken,
    reconcileDeactivation,
    t,
  ]);

  useEffect(() => {
    let cancelled = false;

    setBarcode("");
    setBarcodeType("INTERNAL");
    setTarget("base");
    setIsPrimary(false);
    setPendingCreate(null);
    setPendingCreateBlocked(false);

    if (
      productId === null ||
      baseUomId === null
    ) {
      return () => {
        cancelled = true;
      };
    }
    const scope =
      createScope(productId);
    if (!scope) {
      return () => {
        cancelled = true;
      };
    }

    void (async () => {
      try {
        const pending =
          await readDurableCommand<unknown>(
            scope
          );
        if (
          cancelled ||
          !pending
        ) {
          return;
        }
        if (
          !isBarcodeCreateBody(
            pending.payload
          )
        ) {
          setPendingCreateBlocked(true);
          toast.error(
            apiErrorMessage(
              Object.assign(
                new Error(),
                {
                  code:
                    "DURABLE_OPERATION_CORRUPT",
                },
              ),
              t(
                "products.barcodeManager.saveFailed"
              )
            )
          );
          return;
        }

        const payload =
          pending.payload;
        const restoredTarget =
          payload.uom_id ===
          baseUomId
            ? "base"
            : payload.uom_id ===
                packageUomId
              ? "package"
              : null;
        if (!restoredTarget) {
          setPendingCreateBlocked(true);
          return;
        }

        setBarcode(
          payload.barcode
        );
        setBarcodeType(
          payload.barcode_type
        );
        setTarget(
          restoredTarget
        );
        setIsPrimary(
          payload.is_primary
        );
        setPendingCreate({
          requestId:
            pending.requestId,
          payload,
          createdAt:
            pending.createdAt,
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        setPendingCreateBlocked(true);
        toast.error(
          apiErrorMessage(
            error,
            t(
              "products.barcodeManager.saveFailed"
            )
          )
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    productId,
    baseUomId,
    packageUomId,
    createScope,
    t,
  ]);

  if (!product) {
    return null;
  }

  const targetUomId =
    target === "package"
      ? product.package_uom_id
      : product.base_uom_id;

  const canMutate =
    loadReady &&
    !loadError &&
    !loading &&
    !busy &&
    isOnline &&
    companyId !== null &&
    driverId !== null;

  const canEditCreate =
    canMutate &&
    pendingCreate === null &&
    !pendingCreateBlocked;

  const refreshBarcodes = () => {
    setLoadReady(false);
    setReloadToken(
      (current) => current + 1
    );
  };

  const loadMore = async () => {
    if (
      !nextCursor ||
      !hasMore ||
      loadingMore ||
      !product
    ) {
      return;
    }

    const productId =
      product.id;
    const sequence =
      requestSequence.current;
    setLoadingMore(true);
    try {
      const parsed =
        parseProductBarcodes(
          await authFetch(
            "/catalog/variants/" +
              productId +
              "/barcodes?limit=100&cursor=" +
              encodeURIComponent(
                nextCursor
              )
          )
        );
      if (
        parsed.items.some(
          (item) =>
            item.product_variant_id !==
            productId
        ) ||
        sequence !==
          requestSequence.current
      ) {
        return;
      }

      const existingIds =
        new Set(
          items.map(
            (item) => item.id
          )
        );
      if (
        parsed.items.some(
          (item) =>
            existingIds.has(
              item.id
            )
        )
      ) {
        throw new Error(
          "PRODUCT_BARCODES_CURSOR_DUPLICATE"
        );
      }

      await reconcileDeactivation(
        parsed.items
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
        ]
      );
      setNextCursor(
        parsed.next_cursor
      );
      setHasMore(
        parsed.has_more
      );
    } catch (error) {
      toast.error(
        apiErrorMessage(
          error,
          t(
            "products.barcodeManager.loadFailed"
          )
        )
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

  const addBarcode = async () => {
    const clean = barcode.trim();
    const scope =
      createScope(product.id);
    if (
      !canMutate ||
      !scope ||
      targetUomId === null
    ) {
      return;
    }

    if (
      !pendingCreate &&
      !clean
    ) {
      return;
    }
    if (
      !pendingCreate &&
      target === "package" &&
      product.package_uses_base_barcode
    ) {
      return;
    }

    const freshBody:
      BarcodeCreateBody = {
        uom_id: targetUomId,
        barcode: clean,
        barcode_type:
          barcodeType,
        is_primary:
          isPrimary,
        valid_from: null,
        valid_to: null,
      };

    setBusy(true);
    try {
      const command =
        pendingCreate ??
        (await getOrCreateDurableCommand(
          scope,
          freshBody
        ));
      setPendingCreate(
        command
      );

      parseProductBarcodeMutation(
        await authFetch(
          "/catalog/variants/" +
            product.id +
            "/barcodes",
          {
            method: "POST",
            body: JSON.stringify({
              request_id:
                command.requestId,
              ...command.payload,
            }),
          }
        )
      );
      completeDurableOperation(
        scope,
        command.requestId
      );
      setPendingCreate(null);
      toast.success(
        t(
          "products.barcodeManager.added"
        )
      );
      setBarcode("");
      setIsPrimary(false);
      refreshBarcodes();
      await onChanged();
    } catch (error) {
      const errorCode =
        apiErrorCode(error);
      const durableConflict =
        errorCode ===
        "DURABLE_OPERATION_PENDING";
      const durableCorrupt =
        errorCode ===
        "DURABLE_OPERATION_CORRUPT";
      if (durableCorrupt) {
        setPendingCreateBlocked(
          true
        );
      }
      if (
        !durableConflict &&
        !durableCorrupt &&
        !isAmbiguousRequestError(
          error
        )
      ) {
        abandonDurableOperation(
          scope
        );
        setPendingCreate(
          null
        );
      }
      toast.error(
        apiErrorMessage(
          error,
          t(
            "products.barcodeManager.saveFailed"
          )
        )
      );
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async (
    item: ProductBarcodeRecord
  ) => {
    const scope =
      updateScope(item.id);
    if (
      !canMutate ||
      !item.is_active ||
      !scope
    ) {
      return;
    }

    const freshBody:
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
          freshBody
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
          }
        )
      );
      completeDurableOperation(
        scope,
        command.requestId
      );
      toast.success(
        t(
          "products.barcodeManager.deactivated"
        )
      );
      refreshBarcodes();
      await onChanged();
    } catch (error) {
      if (
        !isAmbiguousRequestError(
          error
        ) &&
        apiErrorCode(error) !==
          "DURABLE_OPERATION_PENDING" &&
        apiErrorCode(error) !==
          "DURABLE_OPERATION_CORRUPT"
      ) {
        abandonDurableOperation(
          scope
        );
      }
      toast.error(
        apiErrorMessage(
          error,
          t(
            "products.barcodeManager.saveFailed"
          )
        )
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen={product !== null}
      onClose={() => {
        if (!busy) {
          onClose();
        }
      }}
      title={t(
        "products.barcodeManager.title",
        {
          name: product.name,
        }
      )}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-4">
        {loadError ? (
          <div className="flex items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
            <p className="text-xs font-bold text-rose-800">
              {t(
                "products.barcodeManager.loadFailed"
              )}
            </p>
            <button
              type="button"
              onClick={() =>
                setReloadToken(
                  (current) =>
                    current + 1
                )
              }
              className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
            >
              {t(
                "common.retry"
              )}
            </button>
          </div>
        ) : null}

        <section className="rounded-2xl border border-slate-200 p-4">
          <h3 className="text-sm font-black text-slate-900">
            {t(
              "products.barcodeManager.current"
            )}
          </h3>

          <div className="mt-3 space-y-2">
            {loading ? (
              <p className="text-xs font-bold text-slate-400">
                {t(
                  "common.loading"
                )}
              </p>
            ) : null}

            {loadReady &&
            !items.length ? (
              <p className="text-xs font-bold text-slate-400">
                {t(
                  "products.barcodeManager.none"
                )}
              </p>
            ) : null}

            {loadReady
              ? items.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-3"
                  >
                    <div>
                      <p className="font-mono text-sm font-black text-slate-900">
                        {item.barcode}
                      </p>
                      <p className="mt-1 text-[11px] font-bold text-slate-500">
                        {t(
                          `uom.${item.uom.code}`,
                          {
                            defaultValue:
                              item.uom
                                .code,
                          }
                        )}{" "}
                        ·{" "}
                        {
                          item.barcode_type
                        }
                        {item.is_primary
                          ? " · " +
                            t(
                              "products.barcodeManager.primary"
                            )
                          : ""}
                        {!item.is_active
                          ? " · " +
                            t(
                              "products.barcodeManager.inactive"
                            )
                          : ""}
                      </p>
                    </div>

                    {item.is_active ? (
                      <button
                        type="button"
                        disabled={
                          !canMutate
                        }
                        onClick={() =>
                          void deactivate(
                            item
                          )
                        }
                        className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-black text-amber-800 disabled:opacity-40"
                      >
                        {t(
                          "products.barcodeManager.deactivate"
                        )}
                      </button>
                    ) : null}
                  </div>
                ))
              : null}

            {loadReady &&
            hasMore ? (
              <button
                type="button"
                disabled={
                  loadingMore
                }
                onClick={() =>
                  void loadMore()
                }
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 disabled:opacity-40"
              >
                {loadingMore
                  ? t(
                      "common.loading"
                    )
                  : t(
                      "products.barcodeManager.loadMore"
                    )}
              </button>
            ) : null}
          </div>
        </section>

        {loadReady &&
        !loadError ? (
          <section className="rounded-2xl border border-slate-200 p-4">
            <h3 className="text-sm font-black text-slate-900">
              {t(
                "products.barcodeManager.add"
              )}
            </h3>
            <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
              {t(
                "products.barcodeManager.historyHint"
              )}
            </p>

            {pendingCreate ? (
              <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs font-bold leading-5 text-amber-900">
                {t(
                  "products.barcodeManager.pendingRetry"
                )}
              </p>
            ) : null}

            {pendingCreateBlocked ? (
              <p className="mt-3 rounded-xl bg-rose-50 p-3 text-xs font-bold leading-5 text-rose-800">
                {t(
                  "products.barcodeManager.pendingBlocked"
                )}
              </p>
            ) : null}

            {product.package_uom_id !==
              null &&
            product.package_uses_base_barcode ? (
              <p className="mt-3 rounded-xl bg-slate-50 p-3 text-xs font-bold leading-5 text-slate-600">
                {t(
                  "products.barcodeManager.sharedPackageHint"
                )}
              </p>
            ) : null}

            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-600">
                {t(
                  "products.barcodeManager.scope"
                )}
                <select
                  value={target}
                  disabled={
                    !canEditCreate
                  }
                  onChange={(event) =>
                    setTarget(
                      event.target
                        .value as
                        | "base"
                        | "package"
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 disabled:opacity-40"
                >
                  <option value="base">
                    {t(
                      "products.barcodeManager.unit"
                    )}
                  </option>
                  {product.package_uom_id !==
                    null &&
                  !product.package_uses_base_barcode ? (
                    <option value="package">
                      {t(
                        "products.barcodeManager.package"
                      )}
                    </option>
                  ) : null}
                </select>
              </label>

              <label className="text-xs font-bold text-slate-600">
                {t(
                  "products.barcodeManager.type"
                )}
                <select
                  value={barcodeType}
                  disabled={
                    !canEditCreate
                  }
                  onChange={(event) =>
                    setBarcodeType(
                      event.target
                        .value as ProductBarcodeType
                    )
                  }
                  className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 disabled:opacity-40"
                >
                  {[
                    "INTERNAL",
                    "EAN8",
                    "EAN13",
                    "UPC_A",
                    "GTIN14",
                    "GS1_128",
                  ].map((value) => (
                    <option
                      key={value}
                      value={value}
                    >
                      {value}
                    </option>
                  ))}
                </select>
              </label>

              <label className="sm:col-span-2 text-xs font-bold text-slate-600">
                {t(
                  "products.barcodeManager.value"
                )}
                <input
                  value={barcode}
                  disabled={
                    !canEditCreate
                  }
                  onChange={(event) =>
                    setBarcode(
                      event.target.value
                    )
                  }
                  maxLength={128}
                  className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono disabled:opacity-40"
                />
              </label>

              <label className="sm:col-span-2 flex items-center gap-2 text-xs font-bold text-slate-600">
                <input
                  type="checkbox"
                  checked={isPrimary}
                  disabled={
                    !canEditCreate
                  }
                  onChange={(event) =>
                    setIsPrimary(
                      event.target
                        .checked
                    )
                  }
                />
                {t(
                  "products.barcodeManager.makePrimary"
                )}
              </label>

              <button
                type="button"
                disabled={
                  !canMutate ||
                  pendingCreateBlocked ||
                  (!pendingCreate &&
                    (!barcode.trim() ||
                      targetUomId ===
                        null))
                }
                onClick={() =>
                  void addBarcode()
                }
                className="sm:col-span-2 rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-black text-white disabled:opacity-40"
              >
                {pendingCreate
                  ? t(
                      "products.barcodeManager.retryPending"
                    )
                  : t(
                      "products.barcodeManager.save"
                    )}
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </Modal>
  );
}
