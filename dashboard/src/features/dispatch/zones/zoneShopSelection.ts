import type { Shop } from "@/types/dispatch";

/** Bulk authority is limited to VISIBLE selected-zone rows, never search-hidden IDs. */
export function zoneShopSelection(
  visible: readonly Shop[],
  selectedIds: readonly string[],
  selectedZoneId: string,
) {
  const eligibleVisible = visible.filter(shop => shop.zoneId === selectedZoneId && !shop.archived);
  const eligibleIds = new Set(eligibleVisible.map(shop => shop.id));
  const visibleSelectedIds = selectedIds.filter(id => eligibleIds.has(id));
  return {
    eligibleVisible,
    visibleSelectedIds,
    hiddenSelectedCount: selectedIds.length - visibleSelectedIds.length,
    blocked: selectedIds.length !== visibleSelectedIds.length,
  };
}
