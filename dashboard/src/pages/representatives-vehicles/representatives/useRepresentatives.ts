import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { listRepresentatives } from "./api";
import type { RepresentativeStatusFilter } from "./contracts";

export function useRepresentatives() {
  const authFetch = useAuthFetch();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<RepresentativeStatusFilter>("all");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const normalized = input.trim();
      setSearch(normalized.length >= 2 ? normalized.slice(0, 100) : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [input]);

  const query = useInfiniteQuery({
    queryKey: ["representatives", localStorage.getItem("company_id"), localStorage.getItem("principal_id"), search, status],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) =>
      listRepresentatives(authFetch, {
        search,
        status,
        cursor: pageParam,
        limit: 30,
        signal,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const items = useMemo(() => {
    const seen = new Set<number>();
    return (query.data?.pages ?? [])
      .flatMap((page) => page.items)
      .filter((representative) => {
        if (seen.has(representative.id)) return false;
        seen.add(representative.id);
        return true;
      });
  }, [query.data]);

  return {
    input,
    setInput,
    search,
    status,
    setStatus,
    items,
    query,
  };
}
