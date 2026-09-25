import {
  useQuery,
} from "@tanstack/react-query";

import {
  parseProductFamilies,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  createOpen: boolean;
  familyOptionSearch: string;
  familyOptionParams: string;
  authFetch: AuthFetch;
};

export function useCreateFamilyOptionsQuery({
  companyId,
  createOpen,
  familyOptionSearch,
  familyOptionParams,
  authFetch,
}: Params) {
  return useQuery({
    queryKey: [
      "simple-product-families",
      companyId,
      "options",
      familyOptionSearch,
    ],
    enabled: Boolean(
      companyId &&
      createOpen
    ),
    queryFn: async ({
      signal,
    }) =>
      parseProductFamilies(
        await authFetch(
          `/simple-products/families?${familyOptionParams}`,
          { signal }
        )
      ),
  });
}
