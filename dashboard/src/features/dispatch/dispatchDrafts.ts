import type { Quantity } from "@/lib/quantity";
import type { Shop, Zone } from "@/types/dispatch";

const prefix = "wanasah:dispatch:d10:";
const safeScope = (scope: string | null) => Boolean(scope && /^\d+:\d+:\d+$/.test(scope));
const validId = (v: unknown): v is string => typeof v === "string" && /^[1-9]\d*$/.test(v) && Number.isSafeInteger(Number(v));
const positiveQty = (v: unknown): v is Quantity => typeof v === "string" &&
  /^\d+(?:\.\d+)?$/.test(v) && Number.isFinite(Number(v)) && Number(v) >= 0;
const write = (key: string, payload: object) => {
  try { localStorage.setItem(key, JSON.stringify(payload)); } catch { /* Keep editing in memory if storage is full. */ }
};
const read = (key: string): unknown => {
  try { const data = localStorage.getItem(key); return data ? JSON.parse(data) as unknown : null; }
  catch { return null; }
};
export const routeDraftKey = (scope: string, warehouse: string, vehicle: string, zone: string, driver: string) =>
  `${prefix}route:${scope}:${warehouse}:${vehicle}:${zone}:${driver}`;
export const shortageDraftKey = (scope: string) => `${prefix}shortage:${scope}`;

type RouteDraft = { scope: string; warehouse: string; vehicle: string; zone: string; driver: string;
  base: Record<string, Quantity>; targets: Record<string, Quantity>; version: 1 };

export function saveRouteLoadDraft(scope: string | null, warehouse: string, vehicle: string, zone: string, driver: string,
  base: Record<string, Quantity>, targets: Record<string, Quantity>): void {
  if (!safeScope(scope) || ![warehouse, vehicle, zone, driver].every(validId)) return;
  if (Object.keys(targets).length > 160 || Object.keys(base).length > 160) return;
  const entries = Object.entries(targets);
  if (!entries.every(([key, value]) => validId(key) && positiveQty(value))) return;
  if (!Object.entries(base).every(([key, value]) => validId(key) && positiveQty(value))) return;
  write(routeDraftKey(scope!, warehouse, vehicle, zone, driver), {
    scope, warehouse, vehicle, zone, driver, version: 1, base, targets,
  } satisfies RouteDraft);
}
export function restoreRouteLoadDraft(scope: string | null, warehouse: string, vehicle: string, zone: string, driver: string,
  current: Record<string, Quantity>, authorizedProductIds: readonly string[]): Record<string, Quantity> | null {
  if (!safeScope(scope) || ![warehouse, vehicle, zone, driver].every(validId)) return null;
  const value = read(routeDraftKey(scope!, warehouse, vehicle, zone, driver));
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const draft = value as Partial<RouteDraft>;
  if (draft.version !== 1 || draft.scope !== scope || draft.warehouse !== warehouse ||
      draft.vehicle !== vehicle || draft.zone !== zone || draft.driver !== driver ||
      !draft.base || !draft.targets) return null;
  const source = Object.entries(draft.base), targets = Object.entries(draft.targets);
  if (targets.length > 160 || source.length > 160 || !source.every(([k,v]) => validId(k) && positiveQty(v)) ||
      !targets.every(([k,v]) => validId(k) && positiveQty(v))) return null;
  // Reuse only when the vehicle's CURRENT physical balance is unchanged; a matching ID is insufficient.
  const allowed = new Set(authorizedProductIds);
  if (source.some(([id, qty]) => !allowed.has(id) || current[id] !== qty)) return null;
  if (targets.some(([id]) => !allowed.has(id))) return null;
  return { ...current, ...draft.targets };
}
export function clearRouteLoadDraft(scope: string | null, warehouse: string, vehicle: string, zone: string, driver: string): void {
  if (safeScope(scope) && [warehouse, vehicle, zone, driver].every(validId))
    localStorage.removeItem(routeDraftKey(scope!, warehouse, vehicle, zone, driver));
}

export type ShortageDraftRow = { productId: string; productName: string; quantity: number };
export type DispatchShortageDraft = {
  scope: string; zoneId: string; shopId: string; driverId: string;
  rows: ShortageDraftRow[]; version: 1;
};
export function clearShortageDraft(scope: string | null): void {
  if (safeScope(scope)) localStorage.removeItem(shortageDraftKey(scope!));
}
export function saveShortageDraft(scope: string | null, draft: Omit<DispatchShortageDraft, "scope" | "version">): void {
  if (!safeScope(scope) || !validId(draft.zoneId) || !validId(draft.shopId) ||
      (draft.driverId !== "" && !validId(draft.driverId)) || !draft.rows.length ||
      draft.rows.length > 80 || !draft.rows.every(row => validId(row.productId) &&
        row.productName.length > 0 && row.productName.length <= 300 &&
        Number.isSafeInteger(row.quantity) && row.quantity > 0)) return;
  write(shortageDraftKey(scope!), { ...draft, scope, version: 1 } satisfies DispatchShortageDraft);
}
export function restoreShortageDraft(scope: string | null,
  zones: readonly Zone[], shops: readonly Shop[], drivers: readonly { id: string }[],
): DispatchShortageDraft | null {
  if (!safeScope(scope)) return null;
  const value = read(shortageDraftKey(scope!));
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const draft = value as DispatchShortageDraft;
  if (draft.version !== 1 || draft.scope !== scope || !validId(draft.zoneId) ||
      !validId(draft.shopId) || !zones.some(zone => zone.id === draft.zoneId) ||
      !shops.some(shop => shop.id === draft.shopId && shop.zoneId === draft.zoneId && !shop.archived) ||
      (draft.driverId !== "" && !drivers.some(driver => driver.id === draft.driverId)) ||
      !Array.isArray(draft.rows) || draft.rows.length === 0 || draft.rows.length > 80 ||
      !draft.rows.every(row => row && validId(row.productId) && typeof row.productName === "string" &&
        row.productName.length > 0 && row.productName.length <= 300 &&
        Number.isSafeInteger(row.quantity) && row.quantity > 0)) return null;
  return draft;
}
