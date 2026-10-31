import { useQuery } from "@tanstack/react-query";
import { useDashboardSession } from "@/hooks/useDashboardSession";
import { isDashboardSessionCurrent } from "@/lib/authStorage";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTenantIdentity } from "./contracts";

export function useTenantIdentity() {
  const authenticatedFetch = useAuthFetch();
  const session = useDashboardSession();
  return useQuery({
    queryKey: ["tenant-identity", session?.generation, session?.identity],
    enabled: session !== null,
    queryFn: async ({ signal }) => {
      const current = () => session && isDashboardSessionCurrent(session) && !signal.aborted;
      if (!current()) throw new DOMException("Session changed", "AbortError");
      const identity = parseTenantIdentity(
        await authenticatedFetch("/tenant/identity", { signal }),
      );
      if (!current()) throw new DOMException("Session changed", "AbortError");
      if (String(identity.company_id) !== JSON.parse(session!.identity)[0]) {
        throw new Error("TENANT_IDENTITY_CONTRACT_INVALID");
      }
      return identity;
    },
    placeholderData: undefined,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}
