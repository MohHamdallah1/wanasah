import { useEffect, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTransferLocations } from "../parsers";
import { isTransferWarehouse, type TransferWarehouse } from "../draftStorage";

/** Cached draft labels are hints only; every selection is revalidated by purpose. */
export function useTransferWarehouses(open: boolean, purpose: "source" | "destination", selected: TransferWarehouse | null) {
  const fetch = useAuthFetch();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string; items: TransferWarehouse[]; loading: boolean; error: unknown }>({ key: "", items: [], loading: false, error: null });
  const key = JSON.stringify([open, purpose, query, selected?.id, revision]);
  useEffect(() => { const timer = setTimeout(() => setQuery(search.trim().length >= 2 ? search.trim() : ""), 300); return () => clearTimeout(timer); }, [search]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setState({ key, items: [], loading: true, error: null });
    const read = async (text: string) => {
      const params = new URLSearchParams({ purpose, limit: "50" });
      if (text.length >= 2) params.set("search", text);
      return parseTransferLocations(await fetch(`/warehouse/unified/transfer/locations?${params}`, { signal: controller.signal })).filter(isTransferWarehouse);
    };
    void (async () => {
      const items = await read(query);
      if (selected && !items.some((item) => item.id === selected.id)) {
        const matches = await read(selected.code);
        const valid = matches.find((item) => item.id === selected.id);
        if (valid) items.unshift(valid);
      }
      if (!controller.signal.aborted) setState({ key, items, loading: false, error: null });
    })().catch((error) => { if (!controller.signal.aborted) setState({ key, items: [], loading: false, error }); });
    return () => controller.abort();
  }, [fetch, open, purpose, query, key, selected]);
  const current = state.key === key ? state : { items: [], loading: open, error: null };
  return { ...current, search, setSearch, retry: () => setRevision((n) => n + 1), valid: !!selected && !current.loading && current.items.some((item) => item.id === selected.id) };
}
