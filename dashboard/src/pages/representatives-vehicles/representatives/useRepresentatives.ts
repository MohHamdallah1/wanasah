import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { listRepresentatives } from "./api";
import type { RepresentativeStatusFilter } from "./contracts";

export function useRepresentatives() {
  const authFetch = useAuthFetch();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<RepresentativeStatusFilter>("active");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(input.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [input]);

  const query = useQuery({
    queryKey: ["representatives", search, status],
    queryFn: ({ signal }) => listRepresentatives(authFetch, { search, status, signal }),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);

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
