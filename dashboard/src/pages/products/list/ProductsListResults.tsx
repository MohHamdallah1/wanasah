import {
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  apiErrorCode,
  apiErrorStatus,
} from "@/lib/apiErrors";
import type {
  ProductDisplayColumn,
  ProductDisplayDensity,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProduct,
} from "@/pages/products/contracts";
import { ProductMobileCard } from "@/pages/products/list/ProductMobileCard";
import {
  ProductsListBlockingState,
  ProductsListNotice,
  type ProductListBlockingState,
} from "@/pages/products/list/ProductsListState";
import { ProductTableRow } from "@/pages/products/list/ProductTableRow";

type Props = {
  items: SimpleProduct[];
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  error: unknown;
  online: boolean;
  hasResultCriteria: boolean;
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
  onClearCriteria: () => void;
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
  error,
  online,
  hasResultCriteria,
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
  onClearCriteria,
  onOpenDetails,
  onEditPrice,
  onEditTracking,
  onPrevious,
  onNext,
}: Props) {
  const { t } = useTranslation();
  const hasItems =
    items.length > 0;
  const errorStatus =
    apiErrorStatus(error);
  const errorCode =
    apiErrorCode(error);
  const permissionDenied =
    isError &&
    errorStatus === 403;
  const offlineFailure =
    !online ||
    (
      isError &&
      (
        errorStatus === 0 ||
        errorCode ===
          "NETWORK_UNAVAILABLE"
      )
    );

  let blockingState:
    | ProductListBlockingState
    | null = null;

  if (permissionDenied) {
    blockingState =
      "permission";
  } else if (
    isLoading &&
    !hasItems
  ) {
    blockingState =
      "loading";
  } else if (
    !hasItems &&
    offlineFailure
  ) {
    blockingState =
      "offline";
  } else if (
    !hasItems &&
    isError
  ) {
    blockingState =
      "error";
  } else if (!hasItems) {
    blockingState =
      hasResultCriteria
        ? "filtered-empty"
        : "empty";
  }

  if (blockingState) {
    return (
      <ProductsListBlockingState
        state={blockingState}
        error={error}
        onRetry={onRetry}
        onClearCriteria={
          onClearCriteria
        }
      />
    );
  }

  const showLocalNotice =
    hasItems &&
    (
      offlineFailure ||
      isError
    );

  return (
    <>
      {showLocalNotice ? (
        <ProductsListNotice
          offline={offlineFailure}
          error={error}
          onRetry={onRetry}
        />
      ) : null}

      {isNarrowViewport ? (
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-2">
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
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
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto bg-white">
          <table className="w-full min-w-[920px] text-start text-sm">
            <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 text-[11px] font-black text-slate-500 backdrop-blur-sm">
              <tr>
                <th
                  scope="col"
                  className={`${tableHeaderSpacing} w-12 text-center`}
                >
                  #
                </th>
                <th className={`${tableHeaderSpacing} text-start`}>
                  {t(
                    "products.columns.product"
                  )}
                </th>
                {columns.package ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.package"
                    )}
                  </th>
                ) : null}
                {columns.unitsPerPackage ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.unitsPerPackage"
                    )}
                  </th>
                ) : null}
                {columns.tracking ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.tracking"
                    )}
                  </th>
                ) : null}
                {columns.lifecycle ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.lifecycle"
                    )}
                  </th>
                ) : null}
                {columns.unitBarcode ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.unitBarcode"
                    )}
                  </th>
                ) : null}
                {columns.packageBarcode ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.packageBarcode"
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.packagePrice ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.packagePrice"
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.unitPrice ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
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
              {items.map(
                (item, index) => (
                  <ProductTableRow
                    key={item.id}
                    item={item}
                    rowNumber={
                      index + 1
                    }
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
              isFetching ||
              !online
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
              isFetching ||
              !online
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
