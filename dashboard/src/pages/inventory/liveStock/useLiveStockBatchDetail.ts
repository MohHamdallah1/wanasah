import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage, apiErrorStatus } from "@/lib/apiErrors";
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

const isAuthorityDenial = (error: unknown): boolean =>
  [401, 403, 404].includes(apiErrorStatus(error) ?? 0);

export function useLiveStockBatchDetail(
  locationId: number,
  fallbackMessage: string,
  staleMessage: string,
  onReadDenied?: () => void,
) {
  const authFetch = useAuthFetch();
  const [product, setProduct] = useState<WarehouseProduct | null>(null);
  const [page, setPage] = useState<WarehouseBatchDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [sourceByBatch, setSourceByBatch] = useState<
    Record<number, LiveStockWarehouseSource>
  >({});
  const [sourceOpenId, setSourceOpenId] = useState<number | null>(null);
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
    setSourceOpenId(null);
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
        if (isAuthorityDenial(error)) {
          onReadDenied?.();
          // A revoked read must not leave formerly authorized evidence visible.
          sourceSeq.current += 1;
          sourceAbort.current?.abort();
          setSourceByBatch({});
          setSourceOpenId(null);
          setSourceLoadingId(null);
          setSourceErrorId(null);
          setPage(null);
        }
        setLoadError({
          message: apiErrorMessage(error, fallbackMessage),
          kind: isAuthorityDenial(error) ? "initial" : append ? "continuation" : "initial",
        });
      } finally {
        if (requestAbort.current === controller) requestAbort.current = null;
        if (sequence === requestSeq.current) setLoading(false);
      }
    },
    [authFetch, fallbackMessage, locationId, onReadDenied],
  );

  const refresh = useCallback(
    (selected?: WarehouseProduct) => {
      const current = selected ?? product;
      if (!current) return;
      stopRequests();
      setProduct(current);
      setPage(null);
      setLoadError(null);
      setLoading(false);
      setSourceByBatch({});
      setSourceOpenId(null);
      setSourceLoadingId(null);
      setSourceErrorId(null);
      // Detail is an independent bounded read; never imply the list and detail
      // are one database snapshot or retain old source evidence as verified.
      void readPage(current, null, false);
    },
    [product, readPage, stopRequests],
  );

  const invalidate = useCallback(() => {
    if (!product) return;
    stopRequests();
    setPage(null);
    setLoading(false);
    setLoadError({ message: staleMessage, kind: "initial" });
    setSourceByBatch({});
    setSourceOpenId(null);
    setSourceLoadingId(null);
    setSourceErrorId(null);
  }, [product, staleMessage, stopRequests]);

  const open = useCallback(
    (selected: WarehouseProduct) => {
      stopRequests();
      setProduct(selected);
      setPage(null);
      setLoadError(null);
      setLoading(false);
      setSourceByBatch({});
      setSourceOpenId(null);
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

  const fetchSource = useCallback(
    async (batchId: number, selected: WarehouseProduct) => {
      const sequence = ++sourceSeq.current;
      sourceAbort.current?.abort();
      const controller = new AbortController();
      sourceAbort.current = controller;
      setSourceByBatch({});
      setSourceLoadingId(batchId);
      setSourceErrorId(null);
      try {
        const raw = await authFetch(
          `/warehouse/inventory/${encodeURIComponent(
            String(selected.id),
          )}/batches/${encodeURIComponent(
            String(batchId),
          )}/source?location_id=${encodeURIComponent(String(locationId))}`,
          { signal: controller.signal },
        );
        if (sequence !== sourceSeq.current) return;
        const parsed = parseLiveStockWarehouseSource(raw);
        if (
          parsed.location_id !== locationId ||
          parsed.product_variant_id !== selected.id ||
          parsed.batch_id !== batchId
        ) {
          throw new Error("LIVE_STOCK_SOURCE_RESPONSE_INVALID");
        }
        setSourceByBatch({ [batchId]: parsed });
      } catch (error: unknown) {
        if (sequence !== sourceSeq.current) return;
        if (error instanceof Error && error.name === "AbortError") return;
        if (isAuthorityDenial(error)) {
          onReadDenied?.();
          // Source revocation invalidates the entire displayed batch evidence.
          stopRequests();
          setPage(null);
          setLoading(false);
          setLoadError({ message: apiErrorMessage(error, fallbackMessage), kind: "initial" });
          setSourceByBatch({});
          setSourceOpenId(null);
          setSourceLoadingId(null);
          setSourceErrorId(null);
        } else {
          setSourceErrorId(batchId);
        }
      } finally {
        if (sourceAbort.current === controller) sourceAbort.current = null;
        if (sequence === sourceSeq.current) setSourceLoadingId(null);
      }
    },
    [authFetch, fallbackMessage, locationId, onReadDenied, stopRequests],
  );

  const loadSource = useCallback(
    (batchId: number) => {
      if (!product || !page?.batches.some((batch) => batch.batch_id === batchId)) return;
      if (sourceOpenId === batchId) {
        sourceSeq.current += 1;
        sourceAbort.current?.abort();
        sourceAbort.current = null;
        setSourceOpenId(null);
        setSourceLoadingId(null);
        setSourceErrorId(null);
        setSourceByBatch({});
        return;
      }
      setSourceOpenId(batchId);
      // Reopening always revalidates. Cache is presentation state, not proof
      // that a source remains accessible or has unchanged quantities.
      void fetchSource(batchId, product);
    },
    [fetchSource, page?.batches, product, sourceOpenId],
  );

  const prefetchSource = useCallback(
    (batchId: number) => {
      if (
        !product ||
        sourceLoadingId === batchId ||
        sourceByBatch[batchId] ||
        !page?.batches.some((batch) => batch.batch_id === batchId)
      ) return;
      void fetchSource(batchId, product);
    },
    [fetchSource, page?.batches, product, sourceByBatch, sourceLoadingId],
  );

  const retrySource = useCallback(
    (batchId: number) => {
      if (
        !product ||
        sourceOpenId !== batchId ||
        sourceLoadingId === batchId ||
        !page?.batches.some((batch) => batch.batch_id === batchId)
      ) return;
      void fetchSource(batchId, product);
    },
    [fetchSource, page?.batches, product, sourceLoadingId, sourceOpenId],
  );

  return {
    product,
    page,
    loading,
    loadError,
    sourceByBatch,
    sourceOpenId,
    sourceLoadingId,
    sourceErrorId,
    open,
    close,
    refresh,
    invalidate,
    retry,
    loadMore,
    loadSource,
    prefetchSource,
    retrySource,
  };
}
