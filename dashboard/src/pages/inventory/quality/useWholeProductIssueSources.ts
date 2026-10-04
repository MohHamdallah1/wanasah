import { useInfiniteQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";

import { parseWholeProductIssueSourcesPage } from "./wholeProductIssueContract";

export function useWholeProductIssueSources(
  productVariantId: number | null,
) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  return useInfiniteQuery({
    queryKey: [
      "whole-product-quality-issue-sources",
      companyId,
      driverId,
      productVariantId,
    ],
    enabled:
      productVariantId !== null &&
      companyId !== null &&
      driverId !== null,
    initialPageParam: null as number | null,
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "25" });
      if (pageParam !== null) params.set("cursor", String(pageParam));
      return parseWholeProductIssueSourcesPage(
        await authFetch(
          `/warehouse/variants/${productVariantId}/quality-issue-sources?${params.toString()}`,
          { signal },
        ),
      );
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
