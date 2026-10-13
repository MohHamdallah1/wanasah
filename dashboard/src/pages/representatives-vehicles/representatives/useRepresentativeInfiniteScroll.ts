import { useCallback, useEffect, useRef, useState } from "react";

interface RepresentativeInfiniteScrollOptions {
  hasMore: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => Promise<unknown> | unknown;
}

export function useRepresentativeInfiniteScroll({
  hasMore,
  isFetchingNextPage,
  onLoadMore,
}: RepresentativeInfiniteScrollOptions) {
  const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null);
  const [manualFallback, setManualFallback] = useState(false);
  const requestPending = useRef(false);

  const sentinelRef = useCallback((node: HTMLDivElement | null) => {
    setSentinel(node);
  }, []);

  useEffect(() => {
    if (!hasMore || !sentinel) return undefined;
    if (typeof IntersectionObserver === "undefined") {
      setManualFallback(true);
      return undefined;
    }

    setManualFallback(false);
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          !entries.some((entry) => entry.isIntersecting) ||
          !hasMore ||
          isFetchingNextPage ||
          requestPending.current
        ) {
          return;
        }

        requestPending.current = true;
        void Promise.resolve(onLoadMore()).finally(() => {
          requestPending.current = false;
        });
      },
      { rootMargin: "160px 0px" },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isFetchingNextPage, onLoadMore, sentinel]);

  return { sentinelRef, manualFallback };
}
