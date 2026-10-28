import { useCallback, useEffect, useState } from "react";
import type { useDispatchProductWindow } from "./useDispatchProductWindow";

type DispatchWindow = ReturnType<typeof useDispatchProductWindow>;

function useBoundary(active: boolean, onIntersect: () => void) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!active || !node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onIntersect();
    }, { root: null, rootMargin: "1200px 0px", threshold: 0 });
    observer.observe(node);
    return () => observer.disconnect();
  }, [active, node, onIntersect]);
  return useCallback((element: HTMLElement | null) => setNode(element), []);
}

export function useDispatchWindowSentinels(page: DispatchWindow) {
  const topRef = useBoundary(page.hasPrevious && !page.loadingWindow && !page.error, page.loadPrevious);
  const bottomRef = useBoundary(page.hasMore && !page.loadingWindow && !page.error, page.loadMore);
  return { topRef, bottomRef };
}
