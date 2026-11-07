import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** A bounded DOM window. Scroll state stays in the actual list element. */
export function useLedgerWindow(
  count: number, estimatedHeight: number, onNearBottom: () => void,
  hasMore: boolean, blocked: boolean,
) {
  const rootRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 800 });
  const onScroll = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    setViewport(value => value.top === root.scrollTop && value.height === root.clientHeight
      ? value : { top: root.scrollTop, height: root.clientHeight });
    if (hasMore && !blocked &&
      root.scrollHeight - root.scrollTop - root.clientHeight < 3 * estimatedHeight) {
      onNearBottom();
    }
  }, [blocked, estimatedHeight, hasMore, onNearBottom]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const resize = new ResizeObserver(() => onScroll());
    resize.observe(root);
    onScroll();
    return () => resize.disconnect();
  }, [onScroll]);

  useEffect(() => {
    const root = rootRef.current;
    const marker = markerRef.current;
    if (!root || !marker || blocked || !hasMore) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(item => item.isIntersecting)) onNearBottom();
    }, { root, rootMargin: "250px 0px" });
    observer.observe(marker);
    return () => observer.disconnect();
  }, [blocked, hasMore, onNearBottom, count]);

  // For small result sets render all rows, retaining existing acceptance tests.
  // At scale limit mounted rows. The overscan also protects keyboard actions.
  const windowed = count > 100;
  const overscan = 18;
  const first = windowed ? Math.max(0, Math.floor(viewport.top / estimatedHeight) - overscan) : 0;
  const amount = Math.max(40, Math.ceil(viewport.height / estimatedHeight) + 2 * overscan);
  const last = windowed ? Math.min(count, first + amount) : count;
  return useMemo(() => ({
    rootRef, markerRef, onScroll,
    first, last,
    before: first * estimatedHeight,
    after: Math.max(0, count - last) * estimatedHeight,
    mounted: last - first,
  }), [first, last, estimatedHeight, count, onScroll]);
}
