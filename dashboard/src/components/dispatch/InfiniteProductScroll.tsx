import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";

export function InfiniteProductScroll({ page }: { page: ReturnType<typeof useDispatchProductSearch> }) {
  const { t } = useTranslation();
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { error, hasMore, items, loadMore, loading, loadingMore } = page;

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore || loading || loadingMore || error || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMore();
    }, { root: null, rootMargin: "500px 0px", threshold: 0 });
    observer.observe(node);
    return () => observer.disconnect();
  }, [error, hasMore, loadMore, loading, loadingMore]);

  if (!items.length && !loadingMore) return null;
  return <div ref={sentinelRef} className="py-3 text-center text-xs font-semibold text-slate-500">
    {loadingMore
      ? <span role="status">{t("dispatchProductSearch.loadingMore")}</span>
      : hasMore
        ? <span>{t("dispatchProductSearch.scrollMore")}</span>
        : <span>{t("dispatchProductSearch.end")}</span>}
  </div>;
}
