import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  parseBatchDetailResponse,
  type WarehouseBatchDetailResponse,
  type WarehouseProduct,
} from "./contracts";
import {
  parseLiveStockWarehouseSource,
  type LiveStockWarehouseSource,
} from "./sourceContract";

const PAGE_SIZE = 50;

type LoadError = {
  message: string;
  kind: "initial" | "continuation";
};

export function useLiveStockBatchDetail(
  locationId: number,
  fallbackMessage: string,
) {
  const authFetch = useAuthFetch();
  const [product, setProduct] = useState<WarehouseProduct | null>(null);
  const [page, setPage] = useState<WarehouseBatchDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [sourceByBatch, setSourceByBatch] = useState<
    Record<number, LiveStockWarehouseSource>
  >({});
  const [sourceLoadingId, setSourceLoadingId] = useState<number | null>(null);
  const [sourceErrorId, setSourceErrorId] = useState<number | null>(null);

  const requestSeq = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);
  const sourceSeq = useRef(0);
  const sourceAbort = useRef<AbortController | null>(null);

  const stopRequests = useCallback(() => {
    requestSeq.current += 1;
    requestAbort.current?.abort();
    requestAbort.current = null;
    sourceSeq.current += 1;
    sourceAbort.current?.abort();
    sourceAbort.current = null;
  }, []);

  const close = useCallback(() => {
    stopRequests();
    setProduct(null);
    setPage(null);
    setLoading(false);
    setLoadError(null);
    setSourceByBatch({});
    setSourceLoadingId(null);
    setSourceErrorId(null);
  }, [stopRequests]);

  useEffect(() => close, [close]);
  useEffect(() => {
    close();
  }, [close, locationId]);

  const readPage = useCallback(
    async (
      selected: WarehouseProduct,
      cursor: string | null,
      append: boolean,
    ) => {
      const sequence = ++requestSeq.current;
      requestAbort.current?.abort();
      const controller = new AbortController();
      requestAbort.current = controller;
      setLoading(true);
      setLoadError(null);

      try {
        const params = new URLSearchParams({
          location_id: String(locationId),
          limit: String(PAGE_SIZE),
        });
        if (cursor) params.set("cursor", cursor);
        const raw = await authFetch(
          `/warehouse/inventory/${encodeURIComponent(
            String(selected.id),
          )}/batches?${params.toString()}`,
          { signal: controller.signal },
        );
        if (sequence !== requestSeq.current) return;

        const parsed = parseBatchDetailResponse(raw);
        if (
          parsed.location_id !== locationId ||
          parsed.product_variant_id !== selected.id ||
          parsed.currency_code.toUpperCase() !== selected.currency_code.toUpperCase()
        ) {
          throw new Error("LIVE_STOCK_BATCH_RESPONSE_INVALID");
        }

        setPage((current) => {
          if (!append || current === null) return parsed;
          const seen = new Set(current.batches.map((batch) => batch.batch_id));
          return {
            ...parsed,
            batches: [
              ...current.batches,
              ...parsed.batches.filter((batch) => !seen.has(batch.batch_id)),
            ],
          };
        });
      } catch (error: unknown) {
        if (sequence !== requestSeq.current) return;
        if (error instanceof Error && error.name === "AbortError") return;
        setLoadError({
          message: apiErrorMessage(error, fallbackMessage),
          kind: append ? "continuation" : "initial",
        });
      } finally {
        if (requestAbort.current === controller) requestAbort.current = null;
        if (sequence === requestSeq.current) setLoading(false);
      }
    },
    [authFetch, fallbackMessage, locationId],
  );

  const open = useCallback(
    (selected: WarehouseProduct) => {
      stopRequests();
      setProduct(selected);
      setPage(null);
      setSourceByBatch({});
      setSourceLoadingId(null);
      setSourceErrorId(null);
      void readPage(selected, null, false);
    },
    [readPage, stopRequests],
  );

  const retry = useCallback(() => {
    if (!product) return;
    const continuation = loadError?.kind === "continuation" && page?.next_cursor;
    void readPage(
      product,
      continuation ? page.next_cursor : null,
      Boolean(continuation),
    );
  }, [loadError?.kind, page?.next_cursor, product, readPage]);

  const loadMore = useCallback(() => {
    if (!product || !page?.next_cursor || loading) return;
    void readPage(product, page.next_cursor, true);
  }, [loading, page?.next_cursor, product, readPage]);

  const loadSource = useCallback(
    async (batchId: number) => {
      if (!product || sourceByBatch[batchId]) return;
      const sequence = ++sourceSeq.current;
      sourceAbort.current?.abort();
      const controller = new AbortController();
      sourceAbort.current = controller;
      setSourceLoadingId(batchId);
      setSourceErrorId(null);
      try {
        const raw = await authFetch(
          `/warehouse/inventory/${encodeURIComponent(
            String(product.id),
          )}/batches/${encodeURIComponent(
            String(batchId),
          )}/source?location_id=${encodeURIComponent(String(locationId))}`,
          { signal: controller.signal },
        );
        if (sequence !== sourceSeq.current) return;
        const parsed = parseLiveStockWarehouseSource(raw);
        if (
          parsed.location_id !== locationId ||
          parsed.product_variant_id !== product.id ||
          parsed.batch_id !== batchId
        ) {
          throw new Error("LIVE_STOCK_SOURCE_RESPONSE_INVALID");
        }
        setSourceByBatch((current) => ({ ...current, [batchId]: parsed }));
      } catch (error: unknown) {
        if (sequence !== sourceSeq.current) return;
        if (error instanceof Error && error.name === "AbortError") return;
        setSourceErrorId(batchId);
      } finally {
        if (sourceAbort.current === controller) sourceAbort.current = null;
        if (sequence === sourceSeq.current) setSourceLoadingId(null);
      }
    },
    [authFetch, locationId, product, sourceByBatch],
  );

  return {
    product,
    page,
    loading,
    loadError,
    sourceByBatch,
    sourceLoadingId,
    sourceErrorId,
    open,
    close,
    retry,
    loadMore,
    loadSource,
  };
}
