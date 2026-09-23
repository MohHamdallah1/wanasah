import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  parseProductBarcodeMutation,
  parseProductBarcodes,
  type ProductBarcodeRecord,
  type ProductBarcodeType,
  type SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct | null;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
};

export function ProductBarcodeManager({
  product,
  onClose,
  onChanged,
}: Props) {
  const { t } = useTranslation();
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<ProductBarcodeRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [barcode, setBarcode] = useState("");
  const [barcodeType, setBarcodeType] =
    useState<ProductBarcodeType>("INTERNAL");
  const [target, setTarget] =
    useState<"base" | "package">("base");
  const [isPrimary, setIsPrimary] = useState(false);

  const load = useCallback(async () => {
    if (!product) {
      setItems([]);
      setLoadError(false);
      return;
    }
    setLoading(true);
    setLoadError(false);
    try {
      const raw = await authFetch(
        "/catalog/variants/" + product.id + "/barcodes",
      );
      setItems(parseProductBarcodes(raw).items);
    } catch (error) {
      setItems([]);
      setLoadError(true);
      toast.error(
        apiErrorMessage(
          error,
          t("products.barcodeManager.loadFailed"),
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [authFetch, product, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!product) {
      setBarcode("");
      setBarcodeType("INTERNAL");
      setTarget("base");
      setIsPrimary(false);
    }
  }, [product]);

  if (!product) {
    return null;
  }

  const targetUomId =
    target === "package"
      ? product.package_uom_id
      : product.base_uom_id;

  const addBarcode = async () => {
    const clean = barcode.trim();
    if (!clean || targetUomId === null) {
      return;
    }
    setBusy(true);
    try {
      const response = parseProductBarcodeMutation(
        await authFetch(
          "/catalog/variants/" + product.id + "/barcodes",
          {
            method: "POST",
            body: JSON.stringify({
              request_id: crypto.randomUUID(),
              uom_id: targetUomId,
              barcode: clean,
              barcode_type: barcodeType,
              is_primary: isPrimary,
              valid_from: new Date().toISOString(),
              valid_to: null,
            }),
          },
        ),
      );
      toast.success(response.message);
      setBarcode("");
      setIsPrimary(false);
      await load();
      await onChanged();
    } catch (error) {
      toast.error(
        apiErrorMessage(
          error,
          t("products.barcodeManager.saveFailed"),
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async (
    item: ProductBarcodeRecord,
  ) => {
    if (!item.is_active) {
      return;
    }
    setBusy(true);
    try {
      const response = parseProductBarcodeMutation(
        await authFetch(
          "/catalog/barcodes/" + item.id,
          {
            method: "PATCH",
            body: JSON.stringify({
              request_id: crypto.randomUUID(),
              expected_version: item.version,
              is_primary: false,
              valid_to: new Date().toISOString(),
              is_active: false,
            }),
          },
        ),
      );
      toast.success(response.message);
      await load();
      await onChanged();
    } catch (error) {
      toast.error(
        apiErrorMessage(
          error,
          t("products.barcodeManager.saveFailed"),
        ),
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
      title={t("products.barcodeManager.title", {
        name: product.name,
      })}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-4">
        {loadError ? (
          <div className="flex items-center justify-between gap-3 rounded-xl bg-rose-50 p-3">
            <p className="text-xs font-bold text-rose-800">
              {t("products.barcodeManager.loadFailed")}
            </p>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs font-black text-rose-800"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        <section className="rounded-2xl border border-slate-200 p-4">
          <h3 className="text-sm font-black text-slate-900">
            {t("products.barcodeManager.current")}
          </h3>
          <div className="mt-3 space-y-2">
            {loading ? (
              <p className="text-xs font-bold text-slate-400">
                {t("common.loading")}
              </p>
            ) : null}
            {!loading && !items.length ? (
              <p className="text-xs font-bold text-slate-400">
                {t("products.barcodeManager.none")}
              </p>
            ) : null}
            {items.map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-3"
              >
                <div>
                  <p className="font-mono text-sm font-black text-slate-900">
                    {item.barcode}
                  </p>
                  <p className="mt-1 text-[11px] font-bold text-slate-500">
                    {item.uom.code} · {item.barcode_type}
                    {item.is_primary
                      ? " · " + t("products.barcodeManager.primary")
                      : ""}
                    {!item.is_active
                      ? " · " + t("products.barcodeManager.inactive")
                      : ""}
                  </p>
                </div>
                {item.is_active ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void deactivate(item)}
                    className="rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-black text-amber-800 disabled:opacity-40"
                  >
                    {t("products.barcodeManager.deactivate")}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 p-4">
          <h3 className="text-sm font-black text-slate-900">
            {t("products.barcodeManager.add")}
          </h3>
          <p className="mt-1 text-[11px] font-semibold leading-5 text-slate-500">
            {t("products.barcodeManager.historyHint")}
          </p>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-bold text-slate-600">
              {t("products.barcodeManager.scope")}
              <select
                value={target}
                onChange={(event) =>
                  setTarget(
                    event.target.value as "base" | "package",
                  )
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5"
              >
                <option value="base">
                  {t("products.barcodeManager.unit")}
                </option>
                {product.package_uom_id !== null ? (
                  <option value="package">
                    {t("products.barcodeManager.package")}
                  </option>
                ) : null}
              </select>
            </label>

            <label className="text-xs font-bold text-slate-600">
              {t("products.barcodeManager.type")}
              <select
                value={barcodeType}
                onChange={(event) =>
                  setBarcodeType(
                    event.target.value as ProductBarcodeType,
                  )
                }
                className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5"
              >
                {[
                  "INTERNAL",
                  "EAN8",
                  "EAN13",
                  "UPC_A",
                  "GTIN14",
                  "GS1_128",
                ].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="sm:col-span-2 text-xs font-bold text-slate-600">
              {t("products.barcodeManager.value")}
              <input
                value={barcode}
                onChange={(event) =>
                  setBarcode(event.target.value)
                }
                maxLength={128}
                className="mt-1.5 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono"
              />
            </label>

            <label className="sm:col-span-2 flex items-center gap-2 text-xs font-bold text-slate-600">
              <input
                type="checkbox"
                checked={isPrimary}
                onChange={(event) =>
                  setIsPrimary(event.target.checked)
                }
              />
              {t("products.barcodeManager.makePrimary")}
            </label>

            <button
              type="button"
              disabled={
                busy ||
                !barcode.trim() ||
                targetUomId === null
              }
              onClick={() => void addBarcode()}
              className="sm:col-span-2 rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-black text-white disabled:opacity-40"
            >
              {t("products.barcodeManager.save")}
            </button>
          </div>
        </section>
      </div>
    </Modal>
  );
}
