import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTransferDetail, parseTransferPage } from "../parsers";
import type {
  TransferDirection,
  TransferStatus,
  WarehouseTransferDetail,
  WarehouseTransferListItem,
} from "../types";
import { getErrorMessage } from "../utils";

export function useTransferList(locationId: number) {
  const authenticatedFetch = useAuthFetch();

  const [items, setItems] = useState<WarehouseTransferListItem[]>([]);
  const [status, setStatus] = useState<TransferStatus | "">("");
  const [direction, setDirection] = useState<TransferDirection>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestSeq = useRef(0);

  const [detail, setDetail] = useState<WarehouseTransferDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestSeq = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
      setTotal(null);
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setCursor(null);
    setCursorHistory([]);
    setNextCursor(null);
    setTotal(null);
    setDetail(null);
  }, [locationId, status, direction]);

  const fetchTransfers = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);

    try {
      const params = new URLSearchParams({
        location_id: String(locationId),
        direction,
        limit: "50",
      });
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (cursor) params.set("cursor", cursor);

      const raw = await authenticatedFetch(
        `/warehouse/unified/transfers?${params.toString()}`
      );

      if (seq !== requestSeq.current) return;

      const page = parseTransferPage(raw);
      const invalid = page.items.find(
        (transfer) =>
          transfer.source_location_id !== locationId &&
          transfer.destination_location_id !== locationId
      );

      if (invalid) {
        throw new Error(
          "مرفوض: السيرفر أعاد حوالة خارج نطاق المستودع المحدد."
        );
      }

      setItems(page.items);
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      setItems([]);
      setNextCursor(null);
      toast.error("فشل جلب الحوالات: " + getErrorMessage(error));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [
    authenticatedFetch,
    cursor,
    direction,
    locationId,
    search,
    status,
  ]);

  useEffect(() => {
    void fetchTransfers();
  }, [fetchTransfers, refreshKey]);

  const openDetail = useCallback(
    async (transfer: WarehouseTransferListItem) => {
      const seq = ++detailRequestSeq.current;
      setDetailLoading(true);
      setDetail(null);

      try {
        const raw = await authenticatedFetch(
          `/warehouse/unified/transfers/${transfer.id}`
        );

        if (seq !== detailRequestSeq.current) return;

        setDetail(parseTransferDetail(raw, locationId));
      } catch (error: unknown) {
        if (seq !== detailRequestSeq.current) return;
        toast.error(
          "فشل جلب تفاصيل الحوالة: " + getErrorMessage(error)
        );
      } finally {
        if (seq === detailRequestSeq.current) setDetailLoading(false);
      }
    },
    [authenticatedFetch, locationId]
  );

  const closeDetail = useCallback(() => {
    if (!detailLoading) setDetail(null);
  }, [detailLoading]);

  const resetDetail = useCallback(() => {
    setDetail(null);
  }, []);

  const refreshTransfers = useCallback(() => {
    setRefreshKey((value) => value + 1);
  }, []);

  const handleNext = useCallback(() => {
    if (!nextCursor) return;
    setCursorHistory((prev) => [...prev, cursor]);
    setCursor(nextCursor);
  }, [cursor, nextCursor]);

  const handlePrevious = useCallback(() => {
    if (cursorHistory.length === 0) return;
    const previous = cursorHistory[cursorHistory.length - 1] ?? null;
    setCursorHistory((prev) => prev.slice(0, -1));
    setCursor(previous);
  }, [cursorHistory]);

  const inTransitCount = useMemo(
    () => items.filter((item) => item.status === "IN_TRANSIT").length,
    [items]
  );

  return {
    items,
    status,
    setStatus,
    direction,
    setDirection,
    searchInput,
    setSearchInput,
    total,
    loading,
    cursorHistory,
    nextCursor,
    detail,
    detailLoading,
    inTransitCount,
    openDetail,
    closeDetail,
    resetDetail,
    refreshTransfers,
    handleNext,
    handlePrevious,
  };
}
