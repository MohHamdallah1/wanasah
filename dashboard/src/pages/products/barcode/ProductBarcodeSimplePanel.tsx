import {
  Check,
  Package,
  RotateCcw,
  ScanBarcode,
  X,
} from "lucide-react";
import {
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  ProductBarcodeRecord,
  SimpleProduct,
} from "@/pages/products/contracts";

export type SimpleBarcodeTarget =
  | "base"
  | "package";

type Props = {
  product: SimpleProduct;
  items: ProductBarcodeRecord[];
  canMutate: boolean;
  busy: boolean;
  onReplace: (
    target: SimpleBarcodeTarget,
    barcode: string,
  ) => Promise<boolean>;
};

export function ProductBarcodeSimplePanel({
  product,
  items,
  canMutate,
  busy,
  onReplace,
}: Props) {
  const { t } = useTranslation();
  const [
    editingTarget,
    setEditingTarget,
  ] =
    useState<SimpleBarcodeTarget | null>(
      null,
    );
  const [
    draft,
    setDraft,
  ] = useState("");

  const activePrimaryByUom =
    useMemo(() => {
      const result =
        new Map<
          number,
          ProductBarcodeRecord
        >();
      for (const item of items) {
        if (
          item.is_active &&
          item.is_primary
        ) {
          result.set(
            item.uom.id,
            item,
          );
        }
      }
      return result;
    }, [items]);

  const latestInactiveByUom =
    useMemo(() => {
      const result =
        new Map<
          number,
          ProductBarcodeRecord
        >();
      for (const item of items) {
        if (item.is_active) {
          continue;
        }
        const previous =
          result.get(item.uom.id);
        if (
          !previous ||
          item.id > previous.id
        ) {
          result.set(
            item.uom.id,
            item,
          );
        }
      }
      return result;
    }, [items]);

  const baseCurrent =
    product.base_uom_id === null
      ? null
      : activePrimaryByUom.get(
          product.base_uom_id,
        ) ?? null;

  const packageCurrent =
    product.package_uom_id === null
      ? null
      : activePrimaryByUom.get(
          product.package_uom_id,
        ) ?? null;

  const beginEdit = (
    target: SimpleBarcodeTarget,
    current:
      | ProductBarcodeRecord
      | null,
  ) => {
    setEditingTarget(target);
    setDraft(
      current?.barcode ?? "",
    );
  };

  const cancelEdit = () => {
    setEditingTarget(null);
    setDraft("");
  };

  const save = async (
    target: SimpleBarcodeTarget,
  ) => {
    const clean = draft.trim();
    if (!clean) {
      return;
    }
    if (
      await onReplace(
        target,
        clean,
      )
    ) {
      cancelEdit();
    }
  };

  const renderCard = ({
    target,
    title,
    description,
    current,
    latestInactive,
    shared = false,
  }: {
    target: SimpleBarcodeTarget;
    title: string;
    description: string;
    current:
      | ProductBarcodeRecord
      | null;
    latestInactive:
      | ProductBarcodeRecord
      | null;
    shared?: boolean;
  }) => {
    const editing =
      editingTarget === target;

    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                {target ===
                "base" ? (
                  <ScanBarcode className="h-4 w-4" />
                ) : (
                  <Package className="h-4 w-4" />
                )}
              </span>
              <div className="min-w-0">
                <h3 className="text-xs font-black text-slate-900">
                  {title}
                </h3>
                <p className="mt-0.5 text-[10px] font-semibold leading-4 text-slate-500">
                  {description}
                </p>
              </div>
            </div>
          </div>

          {!shared &&
          !editing ? (
            <button
              type="button"
              disabled={
                !canMutate ||
                busy
              }
              onClick={() =>
                beginEdit(
                  target,
                  current,
                )
              }
              className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[10px] font-black text-slate-700 transition hover:bg-slate-50 disabled:opacity-40"
            >
              {t(
                current
                  ? "products.barcodeManager.change"
                  : "products.barcodeManager.set",
              )}
            </button>
          ) : null}
        </div>

        {shared ? (
          <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-[11px] font-bold leading-5 text-amber-900 ring-1 ring-inset ring-amber-100">
            {t(
              "products.barcodeManager.packageSharesUnit",
            )}
            {baseCurrent ? (
              <span className="ms-1 font-mono font-black">
                {baseCurrent.barcode}
              </span>
            ) : null}
          </div>
        ) : editing ? (
          <div className="mt-4">
            <label className="text-[10px] font-black text-slate-600">
              {t(
                "products.barcodeManager.newValue",
              )}
              <input
                autoFocus
                value={draft}
                disabled={
                  !canMutate ||
                  busy
                }
                onChange={(
                  event,
                ) =>
                  setDraft(
                    event.target.value,
                  )
                }
                maxLength={128}
                className="mt-1.5 h-10 w-full rounded-xl border border-slate-200 bg-white px-3 font-mono text-sm font-bold outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100 disabled:opacity-40"
              />
            </label>
            <p className="mt-1.5 text-[9px] font-semibold leading-4 text-slate-500">
              {t(
                "products.barcodeManager.replaceHint",
              )}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={
                  !canMutate ||
                  busy ||
                  !draft.trim()
                }
                onClick={() =>
                  void save(target)
                }
                className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-slate-950 px-3 text-[10px] font-black text-white transition hover:bg-slate-800 disabled:opacity-40"
              >
                <Check className="h-3.5 w-3.5" />
                {t(
                  "common.save",
                )}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={cancelEdit}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-[10px] font-black text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
              >
                <X className="h-3.5 w-3.5" />
                {t(
                  "common.cancel",
                )}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            {current ? (
              <div className="flex min-w-0 items-center gap-2">
                <span className="break-all font-mono text-lg font-black tracking-wide text-slate-950">
                  {current.barcode}
                </span>
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-black text-emerald-700">
                  {t(
                    "products.barcodeManager.active",
                  )}
                </span>
              </div>
            ) : (
              <p className="text-xs font-bold text-slate-400">
                {t(
                  "products.barcodeManager.noActive",
                )}
              </p>
            )}

            {!current &&
            latestInactive ? (
              <button
                type="button"
                disabled={
                  !canMutate ||
                  busy
                }
                onClick={() =>
                  void onReplace(
                    target,
                    latestInactive.barcode,
                  )
                }
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-black text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t(
                  "products.barcodeManager.restorePrevious",
                  {
                    barcode:
                      latestInactive.barcode,
                  },
                )}
              </button>
            ) : null}
          </div>
        )}
      </section>
    );
  };

  const baseInactive =
    product.base_uom_id === null
      ? null
      : latestInactiveByUom.get(
          product.base_uom_id,
        ) ?? null;
  const packageInactive =
    product.package_uom_id === null
      ? null
      : latestInactiveByUom.get(
          product.package_uom_id,
        ) ?? null;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {renderCard({
        target: "base",
        title: t(
          "products.barcodeManager.unitBarcode",
        ),
        description: t(
          "products.barcodeManager.unitBarcodeHint",
        ),
        current: baseCurrent,
        latestInactive:
          baseInactive,
      })}

      {product.package_uom_id !==
      null
        ? renderCard({
            target: "package",
            title: t(
              "products.barcodeManager.packageBarcode",
            ),
            description: t(
              product.package_uses_base_barcode
                ? "products.barcodeManager.packageSharedHint"
                : "products.barcodeManager.packageBarcodeHint",
            ),
            current:
              product.package_uses_base_barcode
                ? baseCurrent
                : packageCurrent,
            latestInactive:
              packageInactive,
            shared:
              product.package_uses_base_barcode,
          })
        : null}
    </div>
  );
}
