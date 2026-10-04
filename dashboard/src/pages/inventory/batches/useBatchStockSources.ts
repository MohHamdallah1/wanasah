import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";

import {
  parseBatchStockSources,
} from "./batchStockSourcesContract";

export function useBatchStockSources(
  batchId: number | null,
) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  return useQuery({
    queryKey: [
      "batch-stock-sources",
      companyId,
      driverId,
      batchId,
    ],
    enabled:
      batchId !== null &&
      companyId !== null &&
      driverId !== null,
    queryFn: async ({ signal }) =>
      parseBatchStockSources(
        await authFetch(
          `/warehouse/batches/${batchId}/stock-sources`,
          { signal },
        ),
      ),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
