import {
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  completeDurableOperation,
  durableScope,
  getOrCreateDurableRequestId,
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
  const [loadReady, setLoadReady] =
    useState(false);
  const [loadError, setLoadError] =
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
      setLoadReady(false);
      setLoadError(false);
      return () =>
        controller.abort();
    }

    setItems([]);
    setLoading(true);
    setLoadReady(false);
    setLoadError(false);

    void (async () => {
      try {
        const parsed =
          parseProductBarcodes(
            await authFetch(
              "/catalog/variants/" +
                productId +
                "/barcodes",
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

        setItems(parsed.items);
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
    product?.id,
    reloadToken,
    t,
  ]);

  useEffect(() => {
    setBarcode("");
    setBarcodeType("INTERNAL");
    setTarget("base");
    setIsPrimary(false);
  }, [product?.id]);

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

  const refreshBarcodes = () => {
    setLoadReady(false);
    setReloadToken(
      (current) => current + 1
    );
  };

  const addBarcode = async () => {
    const clean = barcode.trim();
    if (
      !canMutate ||
      !clean ||
      targetUomId === null ||
      companyId === null ||
      driverId === null
    ) {
      return;
    }

    const body = {
      uom_id: targetUomId,
      barcode: clean,
      barcode_type: barcodeType,
      is_primary: isPrimary,
      valid_from: null,
      valid_to: null,
    };
    const scope = durableScope(
      companyId,
      driverId,
      "catalog-barcode-create",
      [
        product.id,
        targetUomId,
        barcodeType,
        isPrimary ? "primary" : "secondary",
        encodeURIComponent(clean),
      ].join(":")
    );

    setBusy(true);
    try {
      const requestId =
        await getOrCreateDurableRequestId(
          scope,
          body
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
                requestId,
              ...body,
            }),
          }
        )
      );
      completeDurableOperation(
        scope,
        requestId
      );
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
    if (
      !canMutate ||
      !item.is_active ||
      companyId === null ||
      driverId === null
    ) {
      return;
    }

    const body = {
      expected_version:
        item.version,
      is_primary: false,
      valid_to: null,
      is_active: false,
    };
    const scope = durableScope(
      companyId,
      driverId,
      "catalog-barcode-update",
      item.id
    );

    setBusy(true);
    try {
      const requestId =
        await getOrCreateDurableRequestId(
          scope,
          body
        );
      parseProductBarcodeMutation(
        await authFetch(
          "/catalog/barcodes/" +
            item.id,
          {
            method: "PATCH",
            body: JSON.stringify({
              request_id:
                requestId,
              ...body,
            }),
          }
        )
      );
      completeDurableOperation(
        scope,
        requestId
      );
      toast.success(
        t(
          "products.barcodeManager.deactivated"
        )
      );
      refreshBarcodes();
      await onChanged();
    } catch (error) {
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

            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-600">
                {t(
                  "products.barcodeManager.scope"
                )}
                <select
                  value={target}
                  disabled={!canMutate}
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
                  null ? (
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
                  disabled={!canMutate}
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
                  disabled={!canMutate}
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
                  disabled={!canMutate}
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
                  !barcode.trim() ||
                  targetUomId === null
                }
                onClick={() =>
                  void addBarcode()
                }
                className="sm:col-span-2 rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-black text-white disabled:opacity-40"
              >
                {t(
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
