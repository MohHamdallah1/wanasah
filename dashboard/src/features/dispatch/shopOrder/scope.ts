import type { Shop } from "@/types/dispatch";

export type ShopOrderChange = { id: string; sequence?: number; archived?: boolean };

const byOrder = (a: Shop, b: Shop) =>
  Number(a.sequence) - Number(b.sequence) || a.id.localeCompare(b.id);

/** Search is company-wide; sequence edits belong ONLY to the selected Zone. */
export const canReorderShop = (shop: Shop, selectedZoneId: string): boolean =>
  Boolean(selectedZoneId) && !shop.archived && shop.zoneId === selectedZoneId;

/** Reorder the entire selected-zone active list, never the cross-zone search subset. */
export function moveShopInSelectedZone(
  shops: readonly Shop[],
  selectedZoneId: string,
  sourceShopId: string,
  targetIndex: number,
): Shop[] {
  const active = shops.filter(s => canReorderShop(s, selectedZoneId)).sort(byOrder);
  const from = active.findIndex(s => s.id === sourceShopId);
  if (from < 0 || !Number.isInteger(targetIndex)) return shops as Shop[];
  const to = Math.min(Math.max(targetIndex, 0), active.length - 1);
  if (from === to && active.every((s, index) => Number(s.sequence) === index + 1)) return shops as Shop[];
  const reordered = [...active];
  const [moved] = reordered.splice(from, 1);
  reordered.splice(to, 0, moved);
  const order = new Map(reordered.map((s, index) => [s.id, index + 1]));
  return shops.map(s => order.has(s.id) ? { ...s, sequence: order.get(s.id)! } : s);
}

export function moveShopBeforeInSelectedZone(
  shops: readonly Shop[], selectedZoneId: string, sourceId: string, targetId: string,
): Shop[] {
  const active = shops.filter(s => canReorderShop(s, selectedZoneId)).sort(byOrder);
  const sourceIndex = active.findIndex(s => s.id === sourceId);
  const targetIndex = active.findIndex(s => s.id === targetId);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return shops as Shop[];
  // Drag-and-drop uses the target row's final position, not the search result index.
  return moveShopInSelectedZone(shops, selectedZoneId, sourceId, targetIndex);
}

/** Diff exclusively within the selected zone, preserving staged archive semantics. */
export function buildShopOrderChanges(
  original: readonly Shop[], draft: readonly Shop[], selectedZoneId: string,
): ShopOrderChange[] {
  if (!selectedZoneId) return [];
  const baseline = new Map(original.filter(s => s.zoneId === selectedZoneId).map(s => [s.id, s]));
  const changes: ShopOrderChange[] = [];
  for (const shop of draft) {
    if (shop.zoneId !== selectedZoneId) continue;
    const before = baseline.get(shop.id);
    if (!before || before.zoneId !== shop.zoneId) continue;
    if (before.archived !== shop.archived) {
      if (!before.archived && shop.archived) changes.push({ id: shop.id, archived: true });
      // Restoring archived Shops belongs to the separate canonical restore flow.
      continue;
    }
    if (!shop.archived && Number(before.sequence) !== Number(shop.sequence)) {
      changes.push({ id: shop.id, sequence: shop.sequence });
    }
  }
  return changes;
}

export const hasShopOrderChanges = (
  original: readonly Shop[], draft: readonly Shop[], zoneId: string,
) => buildShopOrderChanges(original, draft, zoneId).length > 0;

/** Do not replay a pending draft across a new/missing selected-zone Shop membership. */
export function sameSelectedZoneMembership(
  intended: readonly Shop[], current: readonly Shop[], zoneId: string,
): boolean {
  if (!zoneId) return false;
  const a = new Set(intended.filter(s => s.zoneId === zoneId).map(s => s.id));
  const b = new Set(current.filter(s => s.zoneId === zoneId).map(s => s.id));
  return a.size === b.size && [...a].every(id => b.has(id));
}

/** HTTP 200 is not enough: require a NEW authorized snapshot with every write reflected. */
export function verifyShopOrderReadback(
  changes: readonly ShopOrderChange[], readback: readonly Shop[], selectedZoneId: string,
  intendedDraft: readonly Shop[],
): boolean {
  if (!changes.length || !selectedZoneId) return false;
  const intended = intendedDraft.filter(s => s.zoneId === selectedZoneId);
  const actual = readback.filter(s => s.zoneId === selectedZoneId);
  if (actual.length !== intended.length || !intended.length) return false;
  const byId = new Map(actual.map(s => [s.id, s]));
  if (byId.size !== actual.length) return false;
  // Verify the ENTIRE selected-zone order, not just rows mentioned in PUT.
  // Another writer can change an unsubmitted row while our command is in flight.
  if (!intended.every(row => {
    const fresh = byId.get(row.id);
    return !!fresh && fresh.archived === row.archived &&
      (fresh.archived || Number(fresh.sequence) === Number(row.sequence));
  })) return false;
  return changes.every(change => {
    const row = byId.get(change.id);
    if (!row || row.zoneId !== selectedZoneId) return false;
    if (change.sequence !== undefined && Number(row.sequence) !== Number(change.sequence)) return false;
    if (change.archived !== undefined && row.archived !== change.archived) return false;
    return true;
  });
}
