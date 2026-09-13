import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  fetchOfferDefinitions,
  fetchOfferPolicy,
  fetchOfferVersions,
  fetchTaxJurisdictions,
  fetchTaxPolicy,
  fetchTaxRuleSets,
  fetchTaxVersions,
} from "./api";

const flatten = <T,>(
  pages: Array<{ items: T[] }> | undefined
): T[] => pages?.flatMap((page) => page.items) ?? [];

export function useOfferPolicy() {
  const authFetch = useAuthFetch();
  return useQuery({
    queryKey: ["commercial-rules", "offers", "policy"],
    queryFn: () => fetchOfferPolicy(authFetch),
    staleTime: 60_000,
    retry: false,
  });
}

export function useTaxPolicy() {
  const authFetch = useAuthFetch();
  return useQuery({
    queryKey: ["commercial-rules", "tax", "policy"],
    queryFn: () => fetchTaxPolicy(authFetch),
    staleTime: 60_000,
    retry: false,
  });
}

export function useOfferDefinitions() {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "offers", "definitions"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      fetchOfferDefinitions(authFetch, pageParam, signal),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 30_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}

export function useOfferVersions(definitionId: number | null) {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "offers", "versions", definitionId],
    enabled: definitionId !== null,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      if (definitionId === null) throw new Error("لم يتم اختيار عرض.");
      return fetchOfferVersions(authFetch, definitionId, pageParam, signal);
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 20_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}

export function useTaxJurisdictions(enabled = true) {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "tax", "jurisdictions"],
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      fetchTaxJurisdictions(authFetch, pageParam, signal),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 60_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}

export function useTaxRuleSets() {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "tax", "rule-sets"],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      fetchTaxRuleSets(authFetch, pageParam, signal),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 30_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}

export function useTaxVersions(ruleSetId: number | null) {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "tax", "versions", ruleSetId],
    enabled: ruleSetId !== null,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      if (ruleSetId === null) throw new Error("لم يتم اختيار مجموعة ضريبية.");
      return fetchTaxVersions(authFetch, ruleSetId, pageParam, signal);
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 20_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}

export function useCatalogVariants(enabled: boolean) {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "references", "catalog-variants"],
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => import("./api").then(({ fetchCatalogVariants }) => fetchCatalogVariants(authFetch, pageParam, signal)),
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 120_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}
