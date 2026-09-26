import {
  useEffect,
  useRef,
} from "react";
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
  canReassignFamily: boolean;
  canEditTracking: boolean;
  columns: Record<
    ProductDisplayColumn,
    boolean
  >;
  density: ProductDisplayDensity;
  tableHeaderSpacing: string;
  hasNext: boolean;
  onLoadMore: () => void;
  onRetry: () => void;
  onClearCriteria: () => void;
  onOpenDetails: (
    item: SimpleProduct,
  ) => void;
  onEditPrice: (
    item: SimpleProduct,
  ) => void;
  onReassignFamily: (
    item: SimpleProduct,
  ) => void;
  onEditTracking: (
    item: SimpleProduct,
  ) => void;
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
  canReassignFamily,
  canEditTracking,
  columns,
  density,
  tableHeaderSpacing,
  hasNext,
  onLoadMore,
  onRetry,
  onClearCriteria,
  onOpenDetails,
  onEditPrice,
  onReassignFamily,
  onEditTracking,
}: Props) {
  const { t } =
    useTranslation();
  const scrollContainerRef =
    useRef<HTMLDivElement | null>(
      null,
    );
  const loadMoreRef =
    useRef<HTMLDivElement | null>(
      null,
    );

  useEffect(() => {
    if (
      !hasNext ||
      isFetching ||
      !online ||
      typeof IntersectionObserver ===
        "undefined"
    ) {
      return;
    }

    const root =
      scrollContainerRef.current;
    const target =
      loadMoreRef.current;

    if (
      !root ||
      !target
    ) {
      return;
    }

    const observer =
      new IntersectionObserver(
        ([entry]) => {
          if (
            entry?.isIntersecting
          ) {
            onLoadMore();
          }
        },
        {
          root,
          rootMargin:
            "480px 0px",
          threshold: 0,
        },
      );

    observer.observe(target);
    return () =>
      observer.disconnect();
  }, [
    hasNext,
    isFetching,
    online,
    onLoadMore,
  ]);

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

  const loadMoreMarker =
    hasNext ||
    isFetching ? (
      <div
        ref={loadMoreRef}
        className="flex h-10 items-center justify-center"
        aria-live="polite"
      >
        {isFetching ? (
          <>
            <span
              aria-hidden="true"
              className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-slate-500"
            />
            <span className="sr-only">
              {t(
                "products.states.loadingTitle",
              )}
            </span>
          </>
        ) : null}
      </div>
    ) : null;

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
        <div
          ref={scrollContainerRef}
          className="min-h-0 flex-1 overflow-y-auto bg-slate-50/50 p-2"
        >
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
                  canReassignFamily={
                    canReassignFamily
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
                  onReassignFamily={
                    onReassignFamily
                  }
                  onEditTracking={
                    onEditTracking
                  }
                />
              ),
            )}
          </div>
          {loadMoreMarker}
        </div>
      ) : (
        <div
          ref={scrollContainerRef}
          className="min-h-0 flex-1 overflow-auto bg-white"
        >
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
                    "products.columns.product",
                  )}
                </th>
                {columns.package ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.package",
                    )}
                  </th>
                ) : null}
                {columns.unitsPerPackage ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.unitsPerPackage",
                    )}
                  </th>
                ) : null}
                {columns.tracking ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.tracking",
                    )}
                  </th>
                ) : null}
                {columns.lifecycle ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.lifecycle",
                    )}
                  </th>
                ) : null}
                {columns.unitBarcode ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.unitBarcode",
                    )}
                  </th>
                ) : null}
                {columns.packageBarcode ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.packageBarcode",
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.packagePrice ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.packagePrice",
                    )}
                  </th>
                ) : null}
                {pricingVisible &&
                columns.unitPrice ? (
                  <th className={`${tableHeaderSpacing} text-center`}>
                    {t(
                      "products.columns.unitPrice",
                    )}
                  </th>
                ) : null}
                <th
                  className={`${tableHeaderSpacing} w-12 text-center`}
                >
                  <span className="sr-only">
                    {t(
                      "products.columns.action",
                    )}
                  </span>
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {items.map(
                (
                  item,
                  index,
                ) => (
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
                    canReassignFamily={
                      canReassignFamily
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
                    onReassignFamily={
                      onReassignFamily
                    }
                    onEditTracking={
                      onEditTracking
                    }
                  />
                ),
              )}
            </tbody>
          </table>
          {loadMoreMarker}
        </div>
      )}
    </>
  );
}
