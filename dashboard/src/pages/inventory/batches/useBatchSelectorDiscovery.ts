import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseBatchProductPage } from "../liveStock/contracts";
import { parseBatchIndexCursorPage } from "./batchIndexContracts";
import type { BatchFilterFamilyOption, BatchFilterProductOption } from "./BatchIndexFilters";

type Kind = "family" | "product";
type Option = BatchFilterFamilyOption | BatchFilterProductOption;
type Page = { items: Option[]; next_cursor: string | null };
type ReaderState = {
  key: string;
  items: Option[];
  cursor: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: boolean;
};
const empty = (key = ""): ReaderState => ({
  key, items: [], cursor: null, loading: false, loadingMore: false, error: false,
});

const combine = (previous: Option[], incoming: Option[]) => {
  const seen = new Set(previous.map((item) => item.id));
  return [...previous, ...incoming.filter((item) => !seen.has(item.id))];
};

// Family options come from warehouse-relevant BATCH rows, never from the
// company-wide families endpoint (which may include families with no batches).
const parseFamilyPage = (raw: unknown, locationId: number, search: string): Page => {
  const page = parseBatchIndexCursorPage(raw);
  if (page.location_id !== locationId) throw new Error("BATCH_SELECTOR_LOCATION_MISMATCH");
  const values = new Map<number, BatchFilterFamilyOption>();
  for (const row of page.items) {
    if (search && !row.family_name.toLocaleLowerCase().includes(search.toLocaleLowerCase())) continue;
    values.set(row.product_id, { id: row.product_id, name: row.family_name });
  }
  return { items: [...values.values()], next_cursor: page.next_cursor };
};

export function useBatchSelectorDiscovery({
  locationId, companyId, principalId, active,
}: {
  locationId: number;
  companyId: number | null;
  principalId: number | null;
  active: boolean;
}) {
  const authFetch = useAuthFetch();
  const [familySearch, setFamilySearch] = useState("");
  const [productSearch, setProductSearch] = useState("");
  const [opened, setOpened] = useState<Record<Kind, boolean>>({ family: false, product: false });
  const [familyState, setFamilyState] = useState<ReaderState>(empty);
  const [productState, setProductState] = useState<ReaderState>(empty);
  const [retry, setRetry] = useState<Record<Kind, number>>({ family: 0, product: 0 });
  const seq = useRef({ family: 0, product: 0 });
  const abort = useRef<Record<Kind, AbortController | null>>({ family: null, product: null });
  const scope = companyId && principalId ? [companyId, principalId, locationId].join(":") : "";
  const familyQuery = familySearch.trim().slice(0, 100);
  const productQuery = productSearch.trim().slice(0, 100);
  const familyKey = [scope, "family", familyQuery].join("|");
  const productKey = [scope, "product", productQuery].join("|");
  const current = useRef({ family: familyKey, product: productKey, active });
  current.current = { family: familyKey, product: productKey, active };

  const fetchPage = useCallback(async (
    kind: Kind, query: string, cursor: string | null, controller: AbortController,
  ): Promise<Page> => {
    const params = new URLSearchParams({ location_id: String(locationId), limit: "50" });
    if (query.length >= 2) params.set("search", query);
    if (cursor) params.set("cursor", cursor);
    if (kind === "family") {
      // The batch cursor is the only existing endpoint proving a family has
      // at least one relevant batch in this authorized warehouse.
      params.set("sort", "PRODUCT_ASC");
      const raw = await authFetch("/warehouse/inventory/batches/cursor?" + params.toString(), { signal: controller.signal });
      return parseFamilyPage(raw, locationId, query);
    }
    const raw = await authFetch("/warehouse/inventory/batch-products?" + params.toString(), { signal: controller.signal });
    const page = parseBatchProductPage(raw);
    return { items: page.items.map(({ id, name, sku }) => ({ id, name, sku })), next_cursor: page.next_cursor };
  }, [authFetch, locationId]);

  // Requests are lazy until the corresponding search/select receives focus.
  // Every effect is aborted on hide, query, warehouse or principal transition.
  useEffect(() => {
    const kind: Kind = "family";
    const key = familyKey, query = familyQuery;
    const request = ++seq.current[kind];
    abort.current[kind]?.abort();
    setFamilyState(empty(key));
    if (!active || !scope || !opened[kind] || query.length === 1) return;
    const controller = new AbortController();
    abort.current[kind] = controller;
    setFamilyState({ ...empty(key), loading: true });
    const timer = window.setTimeout(() => {
      void fetchPage(kind, query, null, controller)
        .then(page => {
          if (controller.signal.aborted || request !== seq.current[kind] || current.current.family !== key || !current.current.active) return;
          setFamilyState({ ...empty(key), items: page.items, cursor: page.next_cursor });
        })
        .catch(() => {
          if (!controller.signal.aborted && request === seq.current[kind]) setFamilyState({ ...empty(key), error: true });
        });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); seq.current[kind] += 1; };
  }, [active, scope, familyKey, familyQuery, opened.family, retry.family, fetchPage]);

  useEffect(() => {
    const kind: Kind = "product";
    const key = productKey, query = productQuery;
    const request = ++seq.current[kind];
    abort.current[kind]?.abort();
    setProductState(empty(key));
    if (!active || !scope || !opened[kind] || query.length === 1) return;
    const controller = new AbortController();
    abort.current[kind] = controller;
    setProductState({ ...empty(key), loading: true });
    const timer = window.setTimeout(() => {
      void fetchPage(kind, query, null, controller)
        .then(page => {
          if (controller.signal.aborted || request !== seq.current[kind] || current.current.product !== key || !current.current.active) return;
          setProductState({ ...empty(key), items: page.items, cursor: page.next_cursor });
        })
        .catch(() => {
          if (!controller.signal.aborted && request === seq.current[kind]) setProductState({ ...empty(key), error: true });
        });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); seq.current[kind] += 1; };
  }, [active, scope, productKey, productQuery, opened.product, retry.product, fetchPage]);

  useEffect(() => {
    const revoke = () => {
      seq.current.family += 1; seq.current.product += 1;
      abort.current.family?.abort(); abort.current.product?.abort();
      setFamilyState(empty()); setProductState(empty());
      setOpened({ family: false, product: false });
    };
    window.addEventListener("inventory-permission-denied", revoke);
    return () => window.removeEventListener("inventory-permission-denied", revoke);
  }, []);

  const loadMore = useCallback((kind: Kind) => {
    const key = kind === "family" ? familyKey : productKey;
    const query = kind === "family" ? familyQuery : productQuery;
    const state = kind === "family" ? familyState : productState;
    const setter = kind === "family" ? setFamilyState : setProductState;
    if (!active || !scope || state.key !== key || !state.cursor || state.loading || state.loadingMore) return;
    const cursor = state.cursor;
    const request = ++seq.current[kind];
    abort.current[kind]?.abort();
    const controller = new AbortController();
    abort.current[kind] = controller;
    setter({ ...state, loadingMore: true, error: false });
    void fetchPage(kind, query, cursor, controller)
      .then(page => {
        if (controller.signal.aborted || request !== seq.current[kind] || current.current[kind] !== key || !current.current.active) return;
        if (page.next_cursor === cursor) throw new Error("BATCH_SELECTOR_NON_ADVANCING_CURSOR");
        setter({ ...empty(key), items: combine(state.items, page.items), cursor: page.next_cursor });
      })
      .catch(() => {
        if (!controller.signal.aborted && request === seq.current[kind]) setter({ ...state, error: true });
      });
  }, [active, scope, familyKey, productKey, familyQuery, productQuery, familyState, productState, fetchPage]);

  return {
    familySearch, productSearch, setFamilySearch, setProductSearch,
    open: (kind: Kind) => setOpened(value => value[kind] ? value : { ...value, [kind]: true }),
    close: (kind: Kind) => setOpened(value => !value[kind] ? value : { ...value, [kind]: false }),
    retry: (kind: Kind) => setRetry(value => ({ ...value, [kind]: value[kind] + 1 })),
    loadMore,
    families: active && familyState.key === familyKey ? familyState.items as BatchFilterFamilyOption[] : [],
    products: active && productState.key === productKey ? productState.items as BatchFilterProductOption[] : [],
    family: active && familyState.key === familyKey ? familyState : empty(),
    product: active && productState.key === productKey ? productState : empty(),
  };
}
