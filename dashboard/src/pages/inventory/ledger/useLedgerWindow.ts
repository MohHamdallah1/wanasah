import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Variable-height virtual list with bounded DOM and measured cumulative
 * offsets. The observer belongs to the actual scroll root, never the hidden
 * responsive sibling. No background preloading when a root is not laid out.
 */
export function useLedgerWindow(
  count: number, estimatedHeight: number, onNearBottom: () => void,
  hasMore: boolean, blocked: boolean,
) {
  const rootRef = useRef<HTMLDivElement>(null);
  const markerRef = useRef<HTMLDivElement>(null);
  const measured = useRef(new Map<number, number>());
  const [revision, setRevision] = useState(0);
  const [viewport, setViewport] = useState({ top: 0, height: 800 });
  const laidOut = (root: HTMLDivElement) => root.clientHeight > 0 && root.offsetWidth > 0;

  const offsets = useMemo(() => {
    const result = new Float64Array(count + 1);
    for (let index = 0; index < count; index += 1) {
      result[index + 1] = result[index] + (measured.current.get(index) ?? estimatedHeight);
    }
    return result;
    // revision is intentionally the measurement invalidation token.
  }, [count, estimatedHeight, revision]);

  const locate = (distance: number) => {
    let low = 0;
    let high = count;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (offsets[middle + 1] <= distance) low = middle + 1;
      else high = middle;
    }
    return Math.min(count, low);
  };
  const windowed = count > 100;
  const overscan = 18;
  const first = windowed
    ? Math.min(Math.max(0, locate(viewport.top) - overscan), count - 1)
    : 0;
  const last = windowed
    ? Math.min(count, Math.max(first + 40, locate(viewport.top + viewport.height) + overscan))
    : count;

  const onScroll = useCallback(() => {
    const root = rootRef.current;
    if (!root || !laidOut(root)) return;
    setViewport(current => current.top === root.scrollTop && current.height === root.clientHeight
      ? current : { top: root.scrollTop, height: root.clientHeight });
    if (hasMore && !blocked &&
      root.scrollHeight - root.scrollTop - root.clientHeight < 3 * estimatedHeight) {
      onNearBottom();
    }
  }, [blocked, estimatedHeight, hasMore, onNearBottom]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => onScroll()) : null;
    observer?.observe(root);
    onScroll();
    return () => observer?.disconnect();
  }, [onScroll]);

  useEffect(() => {
    const root = rootRef.current;
    const marker = markerRef.current;
    if (!root || !marker || blocked || !hasMore || !laidOut(root) ||
      typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(entries => {
      if (laidOut(root) && entries.some(item => item.isIntersecting)) onNearBottom();
    }, { root, rootMargin: "250px 0px" });
    observer.observe(marker);
    return () => observer.disconnect();
  }, [blocked, hasMore, onNearBottom, count, first, last]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const nodes = root.querySelectorAll<HTMLElement>("[data-ledger-virtual-index]");
    let changed = false;
    const record = (node: HTMLElement, height: number) => {
      const index = Number(node.dataset.ledgerVirtualIndex);
      if (!Number.isSafeInteger(index) || index < 0 || index >= count ||
        !Number.isFinite(height) || height <= 0) return;
      if (Math.abs((measured.current.get(index) ?? estimatedHeight) - height) > 1) {
        measured.current.set(index, height);
        changed = true;
      }
    };
    const observer = new ResizeObserver(entries => {
      let changedNow = false;
      for (const entry of entries) {
        const node = entry.target as HTMLElement;
        const index = Number(node.dataset.ledgerVirtualIndex);
        const observedHeight = entry.borderBoxSize?.[0]?.blockSize;
        const height = Number.isFinite(observedHeight) && observedHeight > 0
          ? observedHeight : entry.contentRect.height;
        if (!Number.isSafeInteger(index) || index < 0 || index >= count ||
          !Number.isFinite(height) || height <= 0) continue;
        if (Math.abs((measured.current.get(index) ?? estimatedHeight) - height) > 1) {
          measured.current.set(index, height);
          changedNow = true;
        }
      }
      if (changedNow) setRevision(value => value + 1);
    });
    nodes.forEach(node => {
      record(node, node.getBoundingClientRect().height);
      observer.observe(node);
    });
    if (changed) setRevision(value => value + 1);
    return () => observer.disconnect();
  }, [count, estimatedHeight, first, last]);

  return {
    rootRef, markerRef, onScroll,
    first, last,
    before: offsets[first],
    after: Math.max(0, offsets[count] - offsets[last]),
    mounted: last - first,
  };
}
