import {
  Clock3,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import {
  useMemo,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  resolveI18nLocale,
} from "@/lib/locale";
import type {
  SimpleBarcodeTarget,
} from "@/pages/products/barcode/barcodeUiTypes";
import type {
  ProductBarcodeRecord,
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  product: SimpleProduct;
  items: ProductBarcodeRecord[];
  canMutate: boolean;
  busy: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onClose: () => void;
  onLoadMore: () => void;
  onReuse: (
    target: SimpleBarcodeTarget,
    barcode: string,
  ) => Promise<boolean>;
  onRemove: (
    item: ProductBarcodeRecord,
  ) => Promise<boolean>;
};

export function ProductBarcodeHistoryPanel({
  product,
  items,
  canMutate,
  busy,
  hasMore,
  loadingMore,
  onClose,
  onLoadMore,
  onReuse,
  onRemove,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const locale =
    resolveI18nLocale(i18n);
  const [
    confirmingRemoveId,
    setConfirmingRemoveId,
  ] = useState<number | null>(
    null,
  );

  const ordered = useMemo(
    () =>
      [...items].sort(
        (a, b) => {
          const byStart =
            Date.parse(
              b.valid_from,
            ) -
            Date.parse(
              a.valid_from,
            );
          return byStart !== 0
            ? byStart
            : b.id - a.id;
        },
      ),
    [items],
  );

  const formatDate = (
    value: string | null,
  ) => {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    if (
      Number.isNaN(
        date.getTime(),
      )
    ) {
      return value;
    }
    return new Intl.DateTimeFormat(
      locale,
      {
        dateStyle: "medium",
        timeStyle: "short",
      },
    ).format(date);
  };

  const targetFor = (
    item: ProductBarcodeRecord,
  ): SimpleBarcodeTarget | null =>
    item.uom.id ===
    product.base_uom_id
      ? "base"
      : item.uom.id ===
          product.package_uom_id
        ? "package"
        : null;

  const labelFor = (
    item: ProductBarcodeRecord,
  ) => {
    const target =
      targetFor(item);
    if (target === "base") {
      return t(
        "products.barcodeManager.unitBarcode",
      );
    }
    if (target === "package") {
      return t(
        "products.barcodeManager.packageBarcode",
      );
    }
    return t(
      `uom.${item.uom.code}`,
      {
        defaultValue:
          item.uom.name ||
          item.uom.code,
      },
    );
  };

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <Clock3 className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-xs font-black text-slate-900">
              {t(
                "products.barcodeManager.history",
              )}
            </h3>
            <p className="mt-0.5 text-[9px] font-semibold leading-4 text-slate-500">
              {t(
                "products.barcodeManager.historyDescription",
              )}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label={t(
            "common.close",
          )}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-slate-500 transition hover:bg-slate-50"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="max-h-[360px] overflow-y-auto">
        {ordered.length === 0 ? (
          <div className="px-4 py-10 text-center text-xs font-bold text-slate-400">
            {t(
              "products.barcodeManager.historyEmpty",
            )}
          </div>
        ) : (
          ordered.map((item) => {
            const target =
              targetFor(item);
            const isCurrent =
              item.is_active &&
              item.is_primary;
            const canReuse =
              !item.is_active &&
              target !== null &&
              !(
                target ===
                  "package" &&
                product.package_uses_base_barcode
              );
            const confirming =
              confirmingRemoveId ===
              item.id;

            return (
              <div
                key={item.id}
                className="border-b border-slate-100 px-4 py-3 last:border-b-0"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all font-mono text-sm font-black text-slate-950">
                        {item.barcode}
                      </span>
                      <span
                        className={
                          isCurrent
                            ? "rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-black text-emerald-700"
                            : "rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-black text-slate-500"
                        }
                      >
                        {t(
                          isCurrent
                            ? "products.barcodeManager.currentStatus"
                            : item.is_active
                              ? "products.barcodeManager.additionalActive"
                              : "products.barcodeManager.previousStatus",
                        )}
                      </span>
                    </div>

                    <p className="mt-1 text-[10px] font-bold text-slate-600">
                      {labelFor(
                        item,
                      )}
                    </p>
                    <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-400">
                      {t(
                        "products.barcodeManager.historyPeriod",
                        {
                          from:
                            formatDate(
                              item.valid_from,
                            ) ??
                            "—",
                          to:
                            formatDate(
                              item.valid_to,
                            ) ??
                            t(
                              "products.barcodeManager.now",
                            ),
                        },
                      )}
                    </p>
                  </div>

                  {!confirming ? (
                    <div className="flex shrink-0 flex-wrap gap-1.5">
                      {canReuse ? (
                        <button
                          type="button"
                          disabled={
                            !canMutate ||
                            busy
                          }
                          onClick={() =>
                            void onReuse(
                              target!,
                              item.barcode,
                            )
                          }
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-[9px] font-black text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          {t(
                            "products.barcodeManager.useAgain",
                          )}
                        </button>
                      ) : null}

                      {item.is_active ? (
                        <button
                          type="button"
                          disabled={
                            !canMutate ||
                            busy
                          }
                          onClick={() =>
                            setConfirmingRemoveId(
                              item.id,
                            )
                          }
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-2.5 text-[9px] font-black text-rose-700 transition hover:bg-rose-50 disabled:opacity-40"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          {t(
                            "products.barcodeManager.removeFromProduct",
                          )}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                {confirming ? (
                  <div className="mt-3 rounded-xl bg-rose-50 p-3 ring-1 ring-inset ring-rose-100">
                    <p className="text-[10px] font-bold leading-5 text-rose-900">
                      {t(
                        "products.barcodeManager.removeConfirm",
                      )}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={
                          !canMutate ||
                          busy
                        }
                        onClick={() => {
                          void (async () => {
                            if (
                              await onRemove(
                                item,
                              )
                            ) {
                              setConfirmingRemoveId(
                                null,
                              );
                            }
                          })();
                        }}
                        className="rounded-lg bg-rose-700 px-3 py-1.5 text-[9px] font-black text-white disabled:opacity-40"
                      >
                        {t(
                          "products.barcodeManager.confirmRemove",
                        )}
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          setConfirmingRemoveId(
                            null,
                          )
                        }
                        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[9px] font-black text-slate-600 disabled:opacity-40"
                      >
                        {t(
                          "common.cancel",
                        )}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      {hasMore ? (
        <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-2.5">
          <button
            type="button"
            disabled={loadingMore}
            onClick={onLoadMore}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-600 transition hover:text-slate-900 disabled:opacity-40"
          >
            {loadingMore
              ? t("common.loading")
              : t(
                  "products.barcodeManager.loadMore",
                )}
          </button>
        </div>
      ) : null}
    </section>
  );
}
