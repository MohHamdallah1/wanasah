import { useEffect, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { parseSupplierPage } from "@/features/suppliers/contracts";

export function useSupplierListSearch(active: boolean | null = true) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const text = input.trim();
      setSearch(text.length >= 2 ? text : "");
    }, 300);
    return () => clearTimeout(timer);
  }, [input]);

  const query = useInfiniteQuery({
    queryKey: ["supplier-list", access.data?.company_id, access.data?.driver_id, active, search, generation],
    enabled: access.can("supplier.read"),
    retry: false,
    staleTime: 0,
    initialPageParam: null as string | null,
    queryFn: async ({ signal, pageParam }) => {
      const params = new URLSearchParams({ limit: "30" });
      if (active !== null) params.set("active", String(active));
      if (search) params.set("search", search);
      if (pageParam) params.set("cursor", pageParam);
      return parseSupplierPage(await authFetch(`/suppliers?${params}`, { signal }));
    },
    getNextPageParam: lastPage => lastPage.has_more ? lastPage.next_cursor ?? undefined : undefined,
  });

  const items = query.data?.pages.flatMap(page => page.items) ?? [];
  const resetPagination = () => setGeneration(value => value + 1);

  return { query, access, input, setInput, items, resetPagination };
}
