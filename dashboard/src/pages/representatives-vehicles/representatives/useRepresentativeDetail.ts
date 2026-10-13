import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { getRepresentative } from "./api";

export function useRepresentativeDetail(
  representativeId: number | null,
  enabled = true,
) {
  const authFetch = useAuthFetch();
  const cacheKey = ["representative-detail", localStorage.getItem("company_id"), localStorage.getItem("principal_id"), representativeId] as const;

  const query = useQuery({
    queryKey: cacheKey,
    enabled: enabled && representativeId !== null,
    queryFn: ({ signal }) =>
      getRepresentative(authFetch, representativeId as number, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  return { ...query, cacheKey };
}
