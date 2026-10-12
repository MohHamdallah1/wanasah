import { useEffect } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { parseProductQualityPage } from "./wholeProductQualityContract";

export function useProductQualitySources(productVariantId: number | null) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const companyId = access.data?.company_id ?? null;
  const backofficeUserId = access.data?.backoffice_user_id ?? null;
  const query = useInfiniteQuery({
    queryKey: ["inline-product-quality-sources", companyId, backofficeUserId, productVariantId],
    enabled: productVariantId !== null && companyId !== null && backofficeUserId !== null,
    initialPageParam: null as number | null,
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (pageParam !== null) params.set("cursor", String(pageParam));
      return parseProductQualityPage(
        await authFetch(`/warehouse/variants/${productVariantId}/quality-issue-sources?${params.toString()}`, { signal }),
      );
    },
    getNextPageParam: (lastPage) => lastPage.hasMore ? lastPage.nextCursor ?? undefined : undefined,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });

  // The inline location view must be complete before it offers product-wide actions.
  useEffect(() => {
    if (query.hasNextPage && !query.isFetchingNextPage) {
      void query.fetchNextPage();
    }
  }, [query.hasNextPage, query.isFetchingNextPage, query.fetchNextPage]);

  return query;
}
