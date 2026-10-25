import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useTransferTranslation as useTranslation } from "../i18n";
import { parseSourceInventoryPage, parseTransferLocations } from "../parsers";
import type { TransferCreateDirection, TransferLocationOption, TransferSourceInventoryItem } from "../types";
import { getErrorMessage } from "../utils";
import { compareQuantity } from "../../quantity";

export function useTransferQueries(createOpen: boolean, createDirection: TransferCreateDirection, locationId: number,
  counterpartLocationId: number | null, sourceLocationId: number | null, destinationLocationId: number | null) {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTranslation();
  const [transferLocations, setTransferLocations] = useState<
    TransferLocationOption[]
  >([]);
  const [transferLocationsLoading, setTransferLocationsLoading] =
    useState(false);
  const [transferLocationSearchInput, setTransferLocationSearchInput] =
    useState("");
  const [transferLocationSearch, setTransferLocationSearch] = useState("");
  const transferLocationsRequestSeq = useRef(0);
  const [productSearchInput, setProductSearchInput] = useState("");
  const [productSearch, setProductSearch] = useState("");
  const [sourceProducts, setSourceProducts] = useState<
    TransferSourceInventoryItem[]
  >([]);
  const [sourceProductsLoading, setSourceProductsLoading] = useState(false);
  const [sourceProductsLoadingMore, setSourceProductsLoadingMore] =
    useState(false);
  const [sourceProductsNextCursor, setSourceProductsNextCursor] =
    useState<string | null>(null);
  const sourceProductsRequestSeq = useRef(0);
  const currentSource = JSON.stringify([createOpen, sourceLocationId, destinationLocationId, productSearch]);
  const sourceScopeRef = useRef(currentSource);
  sourceScopeRef.current = currentSource;
  const currentLocations = JSON.stringify([createOpen, createDirection, locationId, transferLocationSearch]);
  const locationScopeRef = useRef(currentLocations);
  locationScopeRef.current = currentLocations;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = productSearchInput.trim();
      setProductSearch(clean.length >= 2 ? clean : "");
    }, 300);

    return () => window.clearTimeout(timer);
  }, [productSearchInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = transferLocationSearchInput.trim();
      setTransferLocationSearch(clean.length >= 2 ? clean : "");
    }, 300);

    return () => window.clearTimeout(timer);
  }, [transferLocationSearchInput]);


  const invalidateQueries = useCallback(() => { ++sourceProductsRequestSeq.current; ++transferLocationsRequestSeq.current; }, []);
  const resetQueries = useCallback(() => {
    ++sourceProductsRequestSeq.current; ++transferLocationsRequestSeq.current;
    setTransferLocations([]); setTransferLocationSearchInput(""); setTransferLocationSearch("");
    setProductSearchInput(""); setProductSearch("");
    setSourceProducts([]); setSourceProductsNextCursor(null); setSourceProductsLoadingMore(false);
    setSourceProductsLoading(false); setTransferLocationsLoading(false);
  }, []);
  useEffect(() => invalidateQueries, [invalidateQueries]);
  const fetchTransferLocations = useCallback(async () => {
    if (!createOpen) return;

    const seq = ++transferLocationsRequestSeq.current;
    setTransferLocationsLoading(true);

    try {
      const params = new URLSearchParams({ limit: "50", purpose: createDirection === "outgoing" ? "destination" : "source" });
      if (transferLocationSearch) {
        params.set("search", transferLocationSearch);
      }

      const raw = await authenticatedFetch(
        `/warehouse/unified/transfer/locations?${params.toString()}`
      );

      if (seq !== transferLocationsRequestSeq.current || locationScopeRef.current !== currentLocations) return;

      const locations = parseTransferLocations(raw).filter(
        (item) => item.location_type === "WAREHOUSE" && item.id !== locationId
      );

      setTransferLocations((prev) => {
        const merged = new Map<number, TransferLocationOption>();
        for (const item of prev) if (item.id === counterpartLocationId) merged.set(item.id, item);
        for (const item of locations) merged.set(item.id, item);
        return [...merged.values()];
      });
    } catch (error: unknown) {
      if (seq !== transferLocationsRequestSeq.current || locationScopeRef.current !== currentLocations) return;
      toast.error(
        getErrorMessage(error, t("inventoryTransfers.locationsFailure"))
      );
    } finally {
      if (seq === transferLocationsRequestSeq.current && locationScopeRef.current === currentLocations) {
        setTransferLocationsLoading(false);
      }
    }
  }, [
    authenticatedFetch,
    createOpen,
    createDirection,
    locationId,
    counterpartLocationId,
    t,
    transferLocationSearch,
    currentLocations,
  ]);

  useEffect(() => {
    void fetchTransferLocations();
  }, [fetchTransferLocations]);

  const fetchSourceProducts = useCallback(
    async (
      pageCursor: string | null = null,
      append = false
    ) => {
      if (!createOpen || sourceLocationId === null || destinationLocationId === null) {
        setSourceProducts([]);
        setSourceProductsNextCursor(null);
        return;
      }

      const seq = ++sourceProductsRequestSeq.current;

      if (append) {
        setSourceProductsLoadingMore(true);
      } else {
        setSourceProductsLoading(true);
        setSourceProductsNextCursor(null);
      }

      try {
        const params = new URLSearchParams({
          location_id: String(sourceLocationId),
          destination_location_id: String(destinationLocationId),
          transfer_purpose: "WAREHOUSE_BALANCING",
          limit: "50",
        });
        if (productSearch) params.set("search", productSearch);
        if (pageCursor) params.set("cursor", pageCursor);

        const raw = await authenticatedFetch(
          `/warehouse/unified/transfer/source-inventory?${params.toString()}`
        );

        if (seq !== sourceProductsRequestSeq.current || sourceScopeRef.current !== currentSource) return;

        const page = parseSourceInventoryPage(raw);
        const nextItems = page.items.filter(
          (item) => compareQuantity(item.available_quantity, "0") > 0
        );

        setSourceProducts((prev) => {
          if (!append) return nextItems;

          const merged = new Map<number, TransferSourceInventoryItem>();
          for (const item of prev) merged.set(item.id, item);
          for (const item of nextItems) merged.set(item.id, item);
          return [...merged.values()];
        });

        setSourceProductsNextCursor(page.next_cursor);
      } catch (error: unknown) {
        if (seq !== sourceProductsRequestSeq.current || sourceScopeRef.current !== currentSource) return;

        if (!append) {
          setSourceProducts([]);
          setSourceProductsNextCursor(null);
        }

        toast.error(
          getErrorMessage(error, t("inventoryTransfers.sourceFailure"))
        );
      } finally {
        if (seq === sourceProductsRequestSeq.current && sourceScopeRef.current === currentSource) {
          if (append) {
            setSourceProductsLoadingMore(false);
          } else {
            setSourceProductsLoading(false);
          }
        }
      }
    },
    [
      authenticatedFetch,
      createOpen,
      productSearch,
      sourceLocationId,
      destinationLocationId,
      currentSource,
      t,
    ]
  );


  useEffect(() => {
    ++sourceProductsRequestSeq.current;
    setSourceProducts([]); setSourceProductsNextCursor(null); setSourceProductsLoadingMore(false);
  }, [createOpen, sourceLocationId, destinationLocationId]);
  useEffect(() => { void fetchSourceProducts(null, false); }, [fetchSourceProducts]);
  const loadMoreSourceProducts = () => {
    if (sourceProductsNextCursor && !sourceProductsLoadingMore) void fetchSourceProducts(sourceProductsNextCursor, true);
  };
  return { transferLocations, setTransferLocations, transferLocationsLoading, transferLocationSearchInput, setTransferLocationSearchInput,
    sourceProducts, sourceProductsLoading, sourceProductsLoadingMore, sourceProductsNextCursor, productSearchInput, setProductSearchInput,
    resetQueries, invalidateQueries, loadMoreSourceProducts };
}
