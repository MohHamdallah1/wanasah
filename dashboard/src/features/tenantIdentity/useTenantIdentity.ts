import { useQuery } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTenantIdentity } from "./contracts";

export function useTenantIdentity() {
  const authenticatedFetch = useAuthFetch();
  return useQuery({
    queryKey: ["tenant-identity"],
    queryFn: async ({ signal }) => parseTenantIdentity(
      await authenticatedFetch("/tenant/identity", { signal }),
    ),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}
