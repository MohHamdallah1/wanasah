import { useCallback, useEffect, useState } from "react";
import type { useDispatchProductWindow } from "./useDispatchProductWindow";

type DispatchWindow = ReturnType<typeof useDispatchProductWindow>;
type SentinelOptions = { enabled?: boolean; requireUserScroll?: boolean };

function useBoundary(active: boolean, onIntersect: () => void, requireUserScroll = false) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!active || !node || typeof IntersectionObserver === "undefined") return;
    // The launch table scrolls with its parent workspace, never a new
    // nested vertical list. Only a real downward gesture near the bottom
    // admits the next 80. A visible sentinel alone MUST NOT prefetch.
    const root = requireUserScroll
      ? node.closest<HTMLElement>('[data-testid="dispatch-launch-workspace"]') : null;
    let intersecting = false;
    let userRequested = false;
    const maybeLoad = () => {
      if (!intersecting || !userRequested) return;
      if (root) {
        const remaining = root.scrollHeight - root.scrollTop - root.clientHeight;
        if (remaining > Math.max(80, root.clientHeight / 3)) return;
      }
      userRequested = false;
      onIntersect();
    };
    const userGesture = (event: Event) => {
      if (event instanceof WheelEvent && event.deltaY <= 0) return;
      if (event instanceof KeyboardEvent) {
        if (!["ArrowDown", "PageDown", "End", " "].includes(event.key)) return;
        const target = event.target;
        if (target instanceof HTMLElement && (
          target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
        )) return;
      }
      userRequested = true;
      maybeLoad();
    };
    if (requireUserScroll && root) {
      root.addEventListener("wheel", userGesture, { passive: true });
      root.addEventListener("touchmove", userGesture, { passive: true });
      root.addEventListener("keydown", userGesture);
      root.addEventListener("scroll", maybeLoad, { passive: true });
    }
    const observer = new IntersectionObserver((entries) => {
      intersecting = entries.some((entry) => entry.isIntersecting);
      if (!requireUserScroll) onIntersectIfVisible();
      else maybeLoad();
    }, { root: null, rootMargin: requireUserScroll ? "0px" : "1200px 0px", threshold: 0 });
    function onIntersectIfVisible() {
      if (intersecting) onIntersect();
    }
    observer.observe(node);
    return () => {
      observer.disconnect();
      if (requireUserScroll && root) {
        root.removeEventListener("wheel", userGesture);
        root.removeEventListener("touchmove", userGesture);
        root.removeEventListener("keydown", userGesture);
        root.removeEventListener("scroll", maybeLoad);
      }
    };
  }, [active, node, onIntersect, requireUserScroll]);
  return useCallback((element: HTMLElement | null) => setNode(element), []);
}

export function useDispatchWindowSentinels(page: DispatchWindow, options: SentinelOptions = {}) {
  const enabled = options.enabled ?? true;
  const topRef = useBoundary(enabled && page.hasPrevious && !page.loadingWindow && !page.error, page.loadPrevious);
  const bottomRef = useBoundary(enabled && page.hasMore && !page.loadingWindow && !page.error,
    page.loadMore, options.requireUserScroll ?? false);
  return { topRef, bottomRef };
}
