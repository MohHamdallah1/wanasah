import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { parseWholeProductQualityPreview } from "./wholeProductQualityPreviewContract";

export function useWholeProductQualityPreview(
  productVariantId: number,
  enabled: boolean,
) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const companyId = access.data?.company_id ?? null;
  const driverId = access.data?.driver_id ?? null;

  return useQuery({
    queryKey: [
      "whole-product-quality-resolve-preview",
      companyId,
      driverId,
      productVariantId,
    ],
    enabled: enabled && companyId !== null && driverId !== null,
    queryFn: async ({ signal }) => parseWholeProductQualityPreview(
      await authFetch(
        `/warehouse/quality/products/${productVariantId}/resolve-preview`,
        { signal },
      ),
    ),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
}
