import { useInfiniteQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";

import { parseQualityBatchCandidatePage } from "./qualityBatchCandidatesContract";

export function useQualityBatchCandidates(productVariantId: number | null) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  return useInfiniteQuery({
    queryKey: ["quality-batch-candidates", companyId, driverId, productVariantId],
    enabled: productVariantId !== null && companyId !== null && driverId !== null,
    initialPageParam: null as number | null,
    queryFn: async ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "25" });
      if (pageParam !== null) params.set("cursor", String(pageParam));
      const parsed = parseQualityBatchCandidatePage(
        await authFetch(
          `/warehouse/variants/${productVariantId}/quality-batch-candidates?${params.toString()}`,
          { signal },
        ),
      );
      if (parsed.product_variant_id !== productVariantId) {
        throw Object.assign(new Error("QUALITY_BATCH_CANDIDATES_SCOPE_MISMATCH"), {
          code: "QUALITY_BATCH_CANDIDATES_SCOPE_MISMATCH",
        });
      }
      return parsed;
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
