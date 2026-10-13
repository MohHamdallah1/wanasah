import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { getRepresentative } from "./api";

export function useRepresentativeDetail(
  representativeId: number | null,
  enabled = true,
) {
  const authFetch = useAuthFetch();

  return useQuery({
    queryKey: ["representatives", "detail", representativeId],
    enabled: enabled && representativeId !== null,
    queryFn: ({ signal }) =>
      getRepresentative(authFetch, representativeId as number, signal),
    staleTime: 0,
    retry: false,
  });
}
