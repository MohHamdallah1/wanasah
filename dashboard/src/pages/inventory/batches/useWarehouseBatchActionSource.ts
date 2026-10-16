import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { parseWarehouseBatchActionSource } from "./batchActionContracts";

export function useWarehouseBatchActionSource(
  locationId: number | null,
  productVariantId: number | null,
  batchId: number | null,
) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess(locationId);
  const companyId = access.data?.company_id ?? null;
  const backofficeUserId = access.data?.backoffice_user_id ?? null;

  return useQuery({
    queryKey: [
      "batch-action-source",
      companyId,
      backofficeUserId,
      locationId,
      productVariantId,
      batchId,
    ],
    enabled:
      locationId !== null &&
      productVariantId !== null &&
      batchId !== null &&
      companyId !== null &&
      backofficeUserId !== null &&
      access.can("inventory.read"),
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ location_id: String(locationId) });
      return parseWarehouseBatchActionSource(
        await authFetch(
          `/warehouse/inventory/${productVariantId}/batches/${batchId}/source?${params.toString()}`,
          { signal },
        ),
        {
          locationId: locationId as number,
          productVariantId: productVariantId as number,
          batchId: batchId as number,
        },
      );
    },
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
