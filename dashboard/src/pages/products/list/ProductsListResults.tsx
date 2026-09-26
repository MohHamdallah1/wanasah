import {
  Boxes,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductDisplayColumn,
  ProductDisplayDensity,
} from "@/lib/productDisplayPreferences";
import { ProductMobileCard } from "@/pages/products/list/ProductMobileCard";
import { ProductTableRow } from "@/pages/products/list/ProductTableRow";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";

type Props = {
  items: SimpleProduct[];
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  isNarrowViewport: boolean;
  pricingVisible: boolean;
  canEditPrice: boolean;
  canEditTracking: boolean;
  columns: Record<
    ProductDisplayColumn,
    boolean
  >;
  density: ProductDisplayDensity;
  tableHeaderSpacing: string;
  tableColumnCount: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onRetry: () => void;
  onOpenDetails: (
    item: SimpleProduct,
  ) => void;
  onEditPrice: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
  onPrevious: () => void;
  onNext: () => void;
};

export function ProductsListResults({
  items,
  isLoading,
  isError,
  isFetching,
  isNarrowViewport,
  pricingVisible,
  canEditPrice,
  canEditTracking,
  columns,
  density,
  tableHeaderSpacing,
  tableColumnCount,
  hasPrevious,
  hasNext,
  onRetry,
  onOpenDetails,
  onEditPrice,
  onEditTracking,
  onPrevious,
  onNext,
}: Props) {
  const { t } = useTranslation();

  return (
    <>
      {isNarrowViewport ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {isLoading ? (
            <div className="py-12 text-center text-sm font-bold text-slate-400">
              {t("common.loading")}
            </div>
          ) : null}

          {isError ? (
            <div className="rounded-2xl bg-rose-50 p-5 text-center">
              <p className="font-black text-rose-900">
                {t(
                  "products.errors.listLoadTitle"
                )}
              </p>
              <p className="mt-1 text-xs font-semibold leading-6 text-rose-700">
                {t(
                  "products.errors.listLoadDescription"
                )}
              </p>
              <button
                type="button"
                onClick={onRetry}
                className="mt-3 w-full rounded-xl border border-rose-200 bg-white px-4 py-2.5 text-xs font-black text-rose-800"
              >
                {t("common.retry")}
              </button>
            </div>
          ) : null}

          {!isLoading &&
          !isError &&
          !items.length ? (
            <div className="py-12 text-center">
              <Boxes className="mx-auto mb-3 h-8 w-8 text-slate-300" />
              <p className="font-black text-slate-700">
                {t(
                  "products.emptyTitle"
                )}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                {t(
                  "products.emptyDescription"
                )}
              </p>
            </div>
          ) : null}

          {!isLoading &&
          !isError &&
          items.length ? (
            <div className="space-y-3">
              {items.map(
                (item) => (
                  <ProductMobileCard
                    key={item.id}
                    item={item}
                    pricingVisible={
                      pricingVisible
                    }
                    canEditPrice={
                      canEditPrice
                    }
                    canEditTracking={
                      canEditTracking
                    }
                    columns={
                      columns
                    }
                    density={
                      density
                    }
                    onOpenDetails={
                      onOpenDetails
                    }
                    onEditPrice={
                      onEditPrice
                    }
                    onEditTracking={
                      onEditTracking
                    }
                  />
                )
              )}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto bg-white">
          <table className="w-full min-w-[920px] text-start text-sm">
            <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 text-[11px] font-black text-slate-500 backdrop-blur-sm">
              <tr>
                <th className={tableHeaderSpacing}>
                  {t(
                    "products.columns.product"
                  )}
                </th>
                {columns.package ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.package"
                    )}
                  </th>
                ) : null}
                {columns.unitsPerPackage ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.unitsPerPackage"
                    )}
                  </th>
                ) : null}
                {columns.tracking ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.tracking"
                    )}
                  </th>
                ) : null}
                {columns.lifecycle ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.lifecycle"
                    )}
                  </th>
                ) : null}
                {columns.unitBarcode ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.unitBarcode"
                    )}
                  </th>
                ) : null}
                {columns.packageBarcode ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.packageBarcode"
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.packagePrice ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.packagePrice"
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.unitPrice ? (
                  <th className={tableHeaderSpacing}>
                    {t(
                      "products.columns.unitPrice"
                    )}
                  </th>
                ) : null}
                <th
                  className={`${tableHeaderSpacing} w-12 text-center`}
                >
                  <span className="sr-only">
                    {t(
                      "products.columns.action"
                    )}
                  </span>
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td
                    colSpan={
                      tableColumnCount
                    }
                    className="py-16 text-center font-bold text-slate-400"
                  >
                    {t(
                      "common.loading"
                    )}
                  </td>
                </tr>
              ) : null}

              {isError ? (
                <tr>
                  <td
                    colSpan={
                      tableColumnCount
                    }
                    className="py-14 text-center"
                  >
                    <div className="mx-auto max-w-md rounded-2xl bg-rose-50 p-5">
                      <p className="font-black text-rose-900">
                        {t(
                          "products.errors.listLoadTitle"
                        )}
                      </p>
                      <p className="mt-1 text-xs font-semibold leading-6 text-rose-700">
                        {t(
                          "products.errors.listLoadDescription"
                        )}
                      </p>
                      <button
                        type="button"
                        onClick={onRetry}
                        className="mt-3 rounded-xl border border-rose-200 bg-white px-4 py-2 text-xs font-black text-rose-800"
                      >
                        {t(
                          "common.retry"
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ) : null}

              {!isLoading &&
              !isError &&
              !items.length ? (
                <tr>
                  <td
                    colSpan={
                      tableColumnCount
                    }
                    className="py-16 text-center"
                  >
                    <Boxes className="mx-auto mb-3 h-8 w-8 text-slate-300" />
                    <p className="font-black text-slate-700">
                      {t(
                        "products.emptyTitle"
                      )}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {t(
                        "products.emptyDescription"
                      )}
                    </p>
                  </td>
                </tr>
              ) : null}

              {items.map(
                (item) => (
                  <ProductTableRow
                    key={item.id}
                    item={item}
                    pricingVisible={
                      pricingVisible
                    }
                    canEditPrice={
                      canEditPrice
                    }
                    canEditTracking={
                      canEditTracking
                    }
                    columns={
                      columns
                    }
                    density={
                      density
                    }
                    onOpenDetails={
                      onOpenDetails
                    }
                    onEditPrice={
                      onEditPrice
                    }
                    onEditTracking={
                      onEditTracking
                    }
                  />
                )
              )}
            </tbody>
          </table>
        </div>
      )}

      {hasPrevious ||
      hasNext ? (
        <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-white px-4 py-2.5">
          <button
            type="button"
            disabled={
              !hasPrevious ||
              isFetching
            }
            onClick={onPrevious}
            aria-label={t(
              "products.familyPrevious"
            )}
            className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
          </button>
          <button
            type="button"
            disabled={
              !hasNext ||
              isFetching
            }
            onClick={onNext}
            aria-label={t(
              "products.familyNext"
            )}
            className="rounded-lg border border-slate-200 bg-white p-2 disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4 rtl:rotate-180" />
          </button>
        </div>
      ) : null}
    </>
  );
}
