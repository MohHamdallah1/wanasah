import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseSourceInventoryPage } from "../parsers";
import type { TransferSourceInventoryItem } from "../types";
import type { TransferWarehouse } from "../draftStorage";
import { compareQuantity } from "../../quantity";
import { useTransferWarehouses } from "./useTransferWarehouses";

const emptyProducts: TransferSourceInventoryItem[] = [];

export function useTransferQueries(open: boolean, source: TransferWarehouse | null, destination: TransferWarehouse | null) {
  const fetch = useAuthFetch();
  const sources = useTransferWarehouses(open, "source", source);
  const destinations = useTransferWarehouses(open, "destination", destination);
  const ready = sources.valid && destinations.valid && source?.id !== destination?.id;
  const [productSearchInput, setProductSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const key = JSON.stringify([open, ready, source?.id, destination?.id, query, revision]);
  const keyRef = useRef(key); keyRef.current = key;
  const [state, setState] = useState<{ key: string; items: TransferSourceInventoryItem[]; cursor: string | null; loading: boolean; error: unknown }>({ key: "", items: [], cursor: null, loading: false, error: null });
  const active = useRef(false);
  useEffect(() => { const timer = setTimeout(() => setQuery(productSearchInput.trim().length >= 2 ? productSearchInput.trim() : ""), 300); return () => clearTimeout(timer); }, [productSearchInput]);
  const resetProductSearch = useCallback(() => { setProductSearchInput(""); setQuery(""); }, []);
  const readSourcePage = useCallback(async (search: string, cursor: string | null, signal?: AbortSignal) => {
    if (!source || !destination || !ready) throw new Error("TRANSFER_SOURCE_NOT_READY");
    const params = new URLSearchParams({ location_id: String(source.id), destination_location_id: String(destination.id), transfer_purpose: "WAREHOUSE_BALANCING", limit: "50" });
    if (search.length >= 2) params.set("search", search);
    if (cursor) params.set("cursor", cursor);
    return parseSourceInventoryPage(await fetch(`/warehouse/unified/transfer/source-inventory?${params}`, { signal }));
  }, [fetch, source, destination, ready]);
  useEffect(() => {
    const controller = new AbortController(); active.current = false;
    setState({ key, items: [], cursor: null, loading: open && ready, error: null });
    if (open && ready) void readSourcePage(query, null, controller.signal).then((page) => {
      if (!controller.signal.aborted) setState({ key, items: page.items.filter((item) => compareQuantity(item.available_quantity, "0") > 0), cursor: page.next_cursor, loading: false, error: null });
    }).catch((error) => { if (!controller.signal.aborted) setState({ key, items: [], cursor: null, loading: false, error }); });
    return () => controller.abort();
  }, [open, ready, key, query, readSourcePage]);
  const current = state.key === key ? state : { items: emptyProducts, cursor: null, loading: open && ready, error: null };
  const loadMoreSourceProducts = async () => {
    if (!current.cursor || current.loading || active.current) return;
    active.current = true;
    setState((s) => ({ ...s, loading: true }));
    try {
      const page = await readSourcePage(query, current.cursor);
      if (keyRef.current !== key) return;
      setState((s) => ({ key, items: [...new Map([...s.items, ...page.items.filter((item) => compareQuantity(item.available_quantity, "0") > 0)].map((p) => [p.id, p])).values()], cursor: page.next_cursor, loading: false, error: null }));
    } catch (error) { if (keyRef.current === key) setState((s) => ({ ...s, loading: false, error })); }
    finally { if (keyRef.current === key) active.current = false; }
  };
  return { sources, destinations, ready, sourceProducts: current.items, sourceProductsLoading: current.loading, sourceProductsError: current.error,
    sourceProductsNextCursor: current.cursor, productSearchInput, setProductSearchInput, resetProductSearch, readSourcePage, loadMoreSourceProducts,
    retryProducts: () => setRevision((n) => n + 1) };
}
