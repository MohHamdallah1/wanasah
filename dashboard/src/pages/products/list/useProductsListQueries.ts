import {
  keepPreviousData,
  useQuery,
} from "@tanstack/react-query";

import {
  parseProductFamilies,
  parseSimpleProductPage,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  params: string;
  cursor: string | null;
  filtersOpen: boolean;
  familyFilterSearch: string;
  familyFilterParams: string;
  authFetch: AuthFetch;
};

export function useProductsListQueries({
  companyId,
  params,
  cursor,
  filtersOpen,
  familyFilterSearch,
  familyFilterParams,
  authFetch,
}: Params) {
  const productsQuery =
    useQuery({
      queryKey: [
        "simple-products",
        companyId,
        params,
      ],
      enabled: Boolean(
        companyId,
      ),
      placeholderData:
        cursor
          ? keepPreviousData
          : undefined,
      queryFn: async ({
        signal,
      }) =>
        parseSimpleProductPage(
          await authFetch(
            `/simple-products?${params}`,
            { signal },
          ),
        ),
    });

  const familyFilterOptionsQuery =
    useQuery({
      queryKey: [
        "simple-product-families",
        companyId,
        "filter-options",
        familyFilterSearch,
      ],
      enabled: Boolean(
        companyId &&
        filtersOpen,
      ),
      queryFn: async ({
        signal,
      }) =>
        parseProductFamilies(
          await authFetch(
            `/simple-products/families?${familyFilterParams}`,
            { signal },
          ),
        ),
    });

  return {
    productsQuery,
    familyFilterOptionsQuery,
  };
}
