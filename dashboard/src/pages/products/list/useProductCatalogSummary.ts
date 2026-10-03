import { useQuery } from "@tanstack/react-query";

import { parseCatalogSummary } from "@/pages/products/list/catalogSummaryContract";

export function useProductCatalogSummary({ companyId, driverId, authFetch }: {
  companyId: number | null;
  driverId: number | null;
  authFetch: (path: string, opts?: RequestInit) => Promise<unknown>;
}) {
  return useQuery({
    // Reuse the catalog invalidation prefix; never cache across identities.
    queryKey: ["simple-products", companyId, "catalog-summary", driverId],
    enabled: Boolean(companyId && driverId),
    queryFn: async ({ signal }) => parseCatalogSummary(
      await authFetch("/simple-products/summary", { signal }), companyId,
    ),
  });
}
