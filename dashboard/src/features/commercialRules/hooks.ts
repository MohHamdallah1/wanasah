import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  fetchOfferCatalogVariants,
  fetchOfferDefinitions,
  fetchOfferPolicy,
  fetchOfferVersions,
  resolveOfferCatalogVariants,
  fetchTaxJurisdictions,
  fetchTaxPolicy,
  fetchTaxRuleSets,
  fetchTaxVersions,
  fetchCatalogVariants
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

export function useOfferCatalogVariants(
  enabled: boolean,
  requiredIds: number[] = []
) {
  const authFetch = useAuthFetch();
  const query = useInfiniteQuery({
    queryKey: ["commercial-rules", "offers", "references", "variants"],
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      fetchOfferCatalogVariants(authFetch, pageParam, signal),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 120_000,
    retry: false,
  });
  const browsed = flatten(query.data?.pages);
  const browsedIds = new Set(browsed.map((row) => row.id));
  const missingIds = [...new Set(requiredIds)]
    .filter((id) => Number.isSafeInteger(id) && id > 0 && !browsedIds.has(id))
    .sort((a, b) => a - b);
  const resolved = useQuery({
    queryKey: [
      "commercial-rules",
      "offers",
      "references",
      "variants",
      "resolve",
      ...missingIds,
    ],
    enabled: enabled && missingIds.length > 0,
    queryFn: ({ signal }) => resolveOfferCatalogVariants(authFetch, missingIds, signal),
    staleTime: 120_000,
    retry: false,
  });
  const items = [...browsed];
  const seen = new Set(items.map((row) => row.id));
  for (const row of resolved.data?.items ?? []) {
    if (!seen.has(row.id)) {
      seen.add(row.id);
      items.push(row);
    }
  }
  return { ...query, items, isResolvingRequired: resolved.isFetching };
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
    queryFn: ({ pageParam, signal }) =>
    fetchCatalogVariants(authFetch, pageParam, signal),
    getNextPageParam: (lastPage) => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    staleTime: 120_000,
    retry: false,
  });
  return { ...query, items: flatten(query.data?.pages) };
}
