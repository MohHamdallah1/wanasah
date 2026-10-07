import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { parseSupplierPage } from "./contracts";

export function useSupplierSearch(active: boolean | null = true) {
  const authFetch = useAuthFetch();
  const access = useInventoryAccess();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<string | null>>([]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const text = input.trim();
      setSearch(text.length >= 2 ? text : "");
      setCursor(null); setHistory([]);
    }, 300);
    return () => clearTimeout(timer);
  }, [input, active]);
  const query = useQuery({
    queryKey: ["suppliers", access.data?.company_id, access.data?.driver_id, active, search, cursor],
    enabled: access.can("supplier.read"), retry: false, staleTime: 0,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ limit: "30" });
      if (active !== null) params.set("active", String(active));
      if (search) params.set("search", search);
      if (cursor) params.set("cursor", cursor);
      return parseSupplierPage(await authFetch(`/suppliers?${params}`, { signal }));
    },
  });
  const next = () => {
    if (!query.data?.next_cursor) return;
    setHistory(old => [...old, cursor]); setCursor(query.data.next_cursor);
  };
  const back = () => { setCursor(history[history.length - 1] ?? null); setHistory(old => old.slice(0, -1)); };
  const resetPagination = () => { setCursor(null); setHistory([]); };
  return { query, access, input, setInput, next, back, resetPagination, hasBack: history.length > 0 };
}
