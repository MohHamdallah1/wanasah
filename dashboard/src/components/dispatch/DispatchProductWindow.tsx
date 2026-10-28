import { useCallback, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import type { ReturnTypeOfDispatchWindow } from "./dispatchWindowTypes";

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

export function useDispatchWindowSentinels(page: ReturnTypeOfDispatchWindow) {
  const topRef = useBoundary(page.hasPrevious && !page.loadingWindow && !page.error, page.loadPrevious);
  const bottomRef = useBoundary(page.hasMore && !page.loadingWindow && !page.error, page.loadMore);
  return { topRef, bottomRef };
}

function useMeasuredNode(index: number, onMeasure: (index: number, height: number) => void) {
  const [node, setNode] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (!node) return;
    const measure = () => onMeasure(index, node.getBoundingClientRect().height);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [index, node, onMeasure]);
  return useCallback((element: HTMLElement | null) => setNode(element), []);
}

export function MeasuredProductPage({ index, onMeasure, children, className = "" }: {
  index: number;
  onMeasure: (index: number, height: number) => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useMeasuredNode(index, onMeasure);
  return <div ref={ref} data-window-page={index} className={className}>{children}</div>;
}

export function MeasuredProductTableBody({ index, onMeasure, children, className = "" }: {
  index: number;
  onMeasure: (index: number, height: number) => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useMeasuredNode(index, onMeasure);
  return <tbody ref={ref} data-window-page={index} className={className}>{children}</tbody>;
}
