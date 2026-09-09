import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import type {
  CycleBatchOption,
  CycleProductOption,
  StocktakeAuthFetch,
} from "../types";
import {
  getErrorMessage,
  parseCycleBatchPage,
  parseCycleProductPage,
  parseStartSessionId,
} from "../parsers";

interface UseCycleCountStartArgs {
  locationId: number;
  enabled: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  sessionKey: string;
  phaseKey: string;
  setSessionId: (value: string | null) => void;
  loadCountSheet: (sessionId: string) => Promise<void>;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useCycleCountStart({
  locationId,
  enabled,
  authenticatedFetch,
  sessionKey,
  phaseKey,
  setSessionId,
  loadCountSheet,
  notifyStocktakeChanged,
}: UseCycleCountStartArgs) {
  const [productSearchInput, setProductSearchInput] = useState("");
  const [productSearch, setProductSearch] = useState("");
  const [products, setProducts] = useState<CycleProductOption[]>([]);
  const [productsNextCursor, setProductsNextCursor] = useState<string | null>(null);
  const [productsLoading, setProductsLoading] = useState(false);
  const [productsLoadingMore, setProductsLoadingMore] = useState(false);
  const productRequestSeq = useRef(0);
  const [selectedProduct, setSelectedProduct] = useState<CycleProductOption | null>(null);

  const [batchSearchInput, setBatchSearchInput] = useState("");
  const [batchSearch, setBatchSearch] = useState("");
  const [batches, setBatches] = useState<CycleBatchOption[]>([]);
  const [batchesNextCursor, setBatchesNextCursor] = useState<string | null>(null);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [batchesLoadingMore, setBatchesLoadingMore] = useState(false);
  const batchRequestSeq = useRef(0);
  const [selectedBatch, setSelectedBatch] = useState<CycleBatchOption | null>(null);

  const [notes, setNotes] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = productSearchInput.trim();
      setProductSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [productSearchInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = batchSearchInput.trim();
      setBatchSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [batchSearchInput]);

  const resetForm = useCallback(() => {
    productRequestSeq.current += 1;
    batchRequestSeq.current += 1;
    setProductSearchInput("");
    setProductSearch("");
    setProducts([]);
    setProductsNextCursor(null);
    setProductsLoading(false);
    setProductsLoadingMore(false);
    setSelectedProduct(null);
    setBatchSearchInput("");
    setBatchSearch("");
    setBatches([]);
    setBatchesNextCursor(null);
    setBatchesLoading(false);
    setBatchesLoadingMore(false);
    setSelectedBatch(null);
    setNotes("");
  }, []);

  const fetchProducts = useCallback(async (cursor: string | null = null, append = false) => {
    if (!enabled) return;
    const seq = ++productRequestSeq.current;
    if (append) {
      setProductsLoadingMore(true);
    } else {
      setProductsLoading(true);
    }
    if (!append) setProductsNextCursor(null);

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
      });
      if (productSearch) params.set("search", productSearch);
      if (cursor) params.set("cursor", cursor);
      const raw = await authenticatedFetch(`/warehouse/inventory/cursor?${params.toString()}`);
      if (seq !== productRequestSeq.current) return;
      const page = parseCycleProductPage(raw);
      setProducts((prev) => {
        if (!append) return page.items;
        const merged = new Map<number, CycleProductOption>();
        for (const item of prev) merged.set(item.id, item);
        for (const item of page.items) merged.set(item.id, item);
        return [...merged.values()];
      });
      setProductsNextCursor(page.next_cursor);
    } catch (error: unknown) {
      if (seq !== productRequestSeq.current) return;
      if (!append) {
        setProducts([]);
        setProductsNextCursor(null);
      }
      toast.error(getErrorMessage(error, "فشل جلب أصناف الجرد الدوري."));
    } finally {
      if (seq === productRequestSeq.current) {
        if (append) {
          setProductsLoadingMore(false);
        } else {
          setProductsLoading(false);
        }
        }
    }
  }, [authenticatedFetch, enabled, locationId, productSearch]);

  useEffect(() => {
    if (!enabled) return;
    setProducts([]);
    setProductsNextCursor(null);
    void fetchProducts(null, false);
  }, [enabled, fetchProducts]);

  const fetchBatches = useCallback(async (cursor: string | null = null, append = false) => {
    if (!enabled || !selectedProduct) {
      setBatches([]);
      setBatchesNextCursor(null);
      return;
    }
    const seq = ++batchRequestSeq.current;
    if (append) {
      setBatchesLoadingMore(true);
    } else {
      setBatchesLoading(true);
    }
    if (!append) setBatchesNextCursor(null);

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        product_variant_id: String(selectedProduct.id),
        limit: "50",
      });
      if (batchSearch) params.set("search", batchSearch);
      if (cursor) params.set("cursor", cursor);
      const raw = await authenticatedFetch(`/warehouse/unified/stocktake/cycle-batches?${params.toString()}`);
      if (seq !== batchRequestSeq.current) return;
      const page = parseCycleBatchPage(raw, selectedProduct.id);
      setBatches((prev) => {
        if (!append) return page.items;
        const merged = new Map<number, CycleBatchOption>();
        for (const item of prev) merged.set(item.id, item);
        for (const item of page.items) merged.set(item.id, item);
        return [...merged.values()];
      });
      setBatchesNextCursor(page.next_cursor);
    } catch (error: unknown) {
      if (seq !== batchRequestSeq.current) return;
      if (!append) {
        setBatches([]);
        setBatchesNextCursor(null);
      }
      toast.error(getErrorMessage(error, "فشل جلب دفعات الصنف."));
    } finally {
      if (seq === batchRequestSeq.current) {
        if (append) {
          setBatchesLoadingMore(false);
        } else {
          setBatchesLoading(false);
        }
      }
    }
  }, [authenticatedFetch, batchSearch, enabled, locationId, selectedProduct]);

  useEffect(() => {
    batchRequestSeq.current += 1;
    setBatches([]);
    setBatchesNextCursor(null);
    setSelectedBatch(null);
    if (enabled && selectedProduct) void fetchBatches(null, false);
  }, [enabled, fetchBatches, selectedProduct]);

  const chooseProduct = useCallback((product: CycleProductOption) => {
    setSelectedProduct(product);
    setBatchSearchInput("");
    setBatchSearch("");
    setSelectedBatch(null);
  }, []);

  const clearProduct = useCallback(() => {
    setSelectedProduct(null);
    setBatchSearchInput("");
    setBatchSearch("");
    setSelectedBatch(null);
  }, []);

  const loadMoreProducts = useCallback(() => {
    if (!productsNextCursor || productsLoadingMore) return;
    void fetchProducts(productsNextCursor, true);
  }, [fetchProducts, productsLoadingMore, productsNextCursor]);

  const loadMoreBatches = useCallback(() => {
    if (!batchesNextCursor || batchesLoadingMore) return;
    void fetchBatches(batchesNextCursor, true);
  }, [batchesLoadingMore, batchesNextCursor, fetchBatches]);

  const startCycleCount = useCallback(async () => {
    if (!selectedProduct) {
      toast.error("اختر الصنف الذي تريد جرده.");
      return false;
    }
    if (notes.trim().length > 4000) {
      toast.error("ملاحظات الجرد لا يجوز أن تتجاوز 4000 حرف.");
      return false;
    }

    setStarting(true);
    try {
      const raw = await authenticatedFetch("/warehouse/unified/stocktake/start", {
        method: "POST",
        body: JSON.stringify({
          location_id: locationId,
          stocktake_type: "CYCLE_COUNT",
          product_variant_id: selectedProduct.id,
          batch_id: selectedBatch?.id ?? null,
          notes: notes.trim() || null,
        }),
      });

      const sid = String(parseStartSessionId(raw));
      localStorage.setItem(sessionKey, sid);
      localStorage.setItem(phaseKey, "COUNTING");
      setSessionId(sid);
      await loadCountSheet(sid);
      await notifyStocktakeChanged();

      toast.success(
        selectedBatch
          ? `تم بدء جرد دوري للصنف ${selectedProduct.name} — الدفعة ${selectedBatch.batch_number}.`
          : `تم بدء جرد دوري للصنف ${selectedProduct.name} بكل دفعاته.`
      );
      resetForm();
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, "فشل بدء الجرد الدوري."));
      return false;
    } finally {
      setStarting(false);
    }
  }, [
    authenticatedFetch,
    loadCountSheet,
    locationId,
    notes,
    notifyStocktakeChanged,
    phaseKey,
    resetForm,
    selectedBatch,
    selectedProduct,
    sessionKey,
    setSessionId,
  ]);

  return {
    productSearchInput,
    setProductSearchInput,
    products,
    productsNextCursor,
    productsLoading,
    productsLoadingMore,
    selectedProduct,
    chooseProduct,
    clearProduct,
    loadMoreProducts,
    batchSearchInput,
    setBatchSearchInput,
    batches,
    batchesNextCursor,
    batchesLoading,
    batchesLoadingMore,
    selectedBatch,
    setSelectedBatch,
    loadMoreBatches,
    notes,
    setNotes,
    starting,
    startCycleCount,
    resetForm,
  };
}

export type CycleCountStartController = ReturnType<typeof useCycleCountStart>;
