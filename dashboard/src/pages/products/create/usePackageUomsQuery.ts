import {
  useQuery,
} from "@tanstack/react-query";

import {
  parsePackageUoms,
} from "@/pages/products/contracts";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  authFetch: AuthFetch;
};

export function usePackageUomsQuery({
  authFetch,
}: Params) {
  return useQuery({
    queryKey: [
      "simple-product-package-uoms",
    ],
    queryFn: async ({
      signal,
    }) =>
      parsePackageUoms(
        await authFetch(
          "/simple-products/package-uoms",
          { signal }
        )
      ),
  });
}
