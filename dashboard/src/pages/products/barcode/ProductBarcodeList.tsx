import {
  Ban,
  Barcode,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductBarcodeRecord,
} from "@/pages/products/contracts";

type Props = {
  items: ProductBarcodeRecord[];
  loading: boolean;
  loadReady: boolean;
  loadError: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  canMutate: boolean;
  onRetry: () => void;
  onLoadMore: () => void;
  onDeactivate: (
    item: ProductBarcodeRecord,
  ) => void;
};

export function ProductBarcodeList({
  items,
  loading,
  loadReady,
  loadError,
  hasMore,
  loadingMore,
  canMutate,
  onRetry,
  onLoadMore,
  onDeactivate,
}: Props) {
  const { t } = useTranslation();

  if (loadError) {
    return (
      <div className="flex min-h-[180px] flex-col items-center justify-center px-6 text-center">
        <p className="text-xs font-black text-rose-800">
          {t(
            "products.barcodeManager.loadFailed"
          )}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-rose-200 bg-white px-3 text-xs font-black text-rose-700"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t("common.retry")}
        </button>
      </div>
    );
  }

  return (
    <section className="min-h-0">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <Barcode className="h-4 w-4" />
          </span>
          <h3 className="text-xs font-black text-slate-900">
            {t(
              "products.barcodeManager.current"
            )}
          </h3>
        </div>
        {loadReady ? (
          <span className="shrink-0 text-[10px] font-bold tabular-nums text-slate-400">
            {items.length}
          </span>
        ) : null}
      </div>

      <div className="max-h-[340px] overflow-auto">
        {loading ? (
          <div className="flex min-h-[150px] items-center justify-center text-xs font-bold text-slate-400">
            {t("common.loading")}
          </div>
        ) : loadReady &&
          !items.length ? (
          <div className="flex min-h-[150px] flex-col items-center justify-center px-6 text-center">
            <Barcode className="mb-2 h-5 w-5 text-slate-300" />
            <p className="text-xs font-bold text-slate-400">
              {t(
                "products.barcodeManager.none"
              )}
            </p>
          </div>
        ) : loadReady ? (
          items.map((item) => (
            <div
              key={item.id}
              className="group grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-slate-100 px-4 py-2.5 last:border-b-0 hover:bg-slate-50/70"
            >
              <div className="min-w-0">
                <p className="break-all font-mono text-sm font-black text-slate-950">
                  {item.barcode}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-bold text-slate-500">
                  <span>
                    {t(
                      `uom.${item.uom.code}`,
                      {
                        defaultValue:
                          item.uom.name ||
                          item.uom.code,
                      }
                    )}
                  </span>
                  <span aria-hidden="true">
                    ·
                  </span>
                  <span>
                    {t(
                      `products.barcodeManager.types.${item.barcode_type}`
                    )}
                  </span>
                  {item.is_primary ? (
                    <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-emerald-700 ring-1 ring-inset ring-emerald-200">
                      {t(
                        "products.barcodeManager.primary"
                      )}
                    </span>
                  ) : null}
                  {!item.is_active ? (
                    <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-slate-500 ring-1 ring-inset ring-slate-200">
                      {t(
                        "products.barcodeManager.inactive"
                      )}
                    </span>
                  ) : null}
                </div>
              </div>

              {item.is_active ? (
                <button
                  type="button"
                  disabled={!canMutate}
                  onClick={() =>
                    onDeactivate(item)
                  }
                  aria-label={t(
                    "products.barcodeManager.deactivate"
                  )}
                  title={t(
                    "products.barcodeManager.deactivate"
                  )}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent text-amber-700 transition hover:border-amber-200 hover:bg-white disabled:opacity-40"
                >
                  <Ban className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          ))
        ) : null}
      </div>

      {loadReady && hasMore ? (
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
                  "products.barcodeManager.loadMore"
                )}
          </button>
        </div>
      ) : null}
    </section>
  );
}
