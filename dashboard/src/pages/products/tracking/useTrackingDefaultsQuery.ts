import {
  useQuery,
} from "@tanstack/react-query";

import {
  parseProductTrackingDefaults,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  authFetch: AuthFetch;
};

export function useTrackingDefaultsQuery({
  companyId,
  authFetch,
}: Params) {
  return useQuery({
    queryKey: [
      "simple-product-tracking-defaults",
      companyId,
    ],
    enabled: Boolean(companyId),
    queryFn: async ({
      signal,
    }) =>
      parseProductTrackingDefaults(
        await authFetch(
          "/simple-products/tracking/defaults",
          { signal }
        )
      ),
  });
}
