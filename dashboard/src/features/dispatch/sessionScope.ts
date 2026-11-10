import type { InventoryCapabilities } from "@/hooks/useInventoryAccess";
import { isDashboardSessionCurrent, type DashboardSession } from "@/lib/authStorage";
import type { TabId } from "@/types/dispatch";

/** Verified company + canonical principal + Backoffice profile; never use role names or JWT claims. */
export function dispatchActorScope(session: DashboardSession | null, access: InventoryCapabilities | undefined): string | null {
  if (!session || !access || !isDashboardSessionCurrent(session)) return null;
  try {
    const identity: unknown = JSON.parse(session.identity);
    if (!Array.isArray(identity) || identity.length < 3) return null;
    const ids = [access.company_id, access.principal_id, access.backoffice_user_id];
    if (!ids.every((id, index) => Number.isSafeInteger(id) && id > 0 && String(id) === identity[index])) return null;
    return ids.join(":");
  } catch {
    return null;
  }
}

const prefix = "wanasah:dispatch:session:v1:";
const id = (value: unknown): string => typeof value === "string" && /^[1-9]\\d*$/.test(value) &&
  Number.isSafeInteger(Number(value)) ? value : "";
const tab = (value: unknown): TabId => value === "zones" || value === "launch" || value === "routes" ? value : "routes";
export type DispatchPreferences = {
  activeTab: TabId;
  zoneForShops: string;
  launchZone: string;
  driver: string;
  vehicle: string;
  sourceWarehouse: string;
};
export const defaultDispatchPreferences = (): DispatchPreferences => ({
  activeTab: "routes", zoneForShops: "", launchZone: "", driver: "", vehicle: "", sourceWarehouse: "",
});
export const dispatchPreferencesKey = (scope: string): string => prefix + scope + ":preferences";

export function readDispatchPreferences(scope: string | null): DispatchPreferences {
  if (!scope || !/^\\d+:\\d+:\\d+$/.test(scope)) return defaultDispatchPreferences();
  try {
    const raw = localStorage.getItem(dispatchPreferencesKey(scope));
    if (!raw) return defaultDispatchPreferences();
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return defaultDispatchPreferences();
    const entry = parsed as Record<string, unknown>;
    if (entry.scope !== scope || entry.version !== 1) return defaultDispatchPreferences();
    return {
      activeTab: tab(entry.activeTab), zoneForShops: id(entry.zoneForShops),
      launchZone: id(entry.launchZone), driver: id(entry.driver), vehicle: id(entry.vehicle),
      sourceWarehouse: id(entry.sourceWarehouse),
    };
  } catch {
    return defaultDispatchPreferences();
  }
}

export function writeDispatchPreferences(scope: string | null, prefs: DispatchPreferences): boolean {
  if (!scope || !/^\\d+:\\d+:\\d+$/.test(scope)) return false;
  try {
    localStorage.setItem(dispatchPreferencesKey(scope), JSON.stringify({
      ...prefs, scope, version: 1,
    }));
    return true;
  } catch {
    return false;
  }
}

type IdItem = { id: string };
type WarehouseItem = IdItem & { can_execute?: boolean };
type VehicleItem = IdItem & { can_execute?: boolean };
export function reconcileDispatchPreferences(p: DispatchPreferences, data: {
  zones: readonly IdItem[]; drivers: readonly IdItem[];
  vehicles: readonly VehicleItem[]; warehouses: readonly WarehouseItem[];
}, canLaunch: boolean): DispatchPreferences {
  const has = (list: readonly IdItem[], choice: string) => Boolean(choice) && list.some(row => row.id === choice);
  const sourceWarehouse = canLaunch && has(data.warehouses.filter(w => w.can_execute === true), p.sourceWarehouse)
    ? p.sourceWarehouse : "";
  return {
    activeTab: p.activeTab,
    zoneForShops: has(data.zones, p.zoneForShops) ? p.zoneForShops : data.zones[0]?.id ?? "",
    launchZone: canLaunch && has(data.zones, p.launchZone) ? p.launchZone : "",
    driver: canLaunch && has(data.drivers, p.driver) ? p.driver : "",
    // Vehicle/source pair is one draft context. A missing/revoked Warehouse cannot resurrect a Vehicle.
    vehicle: sourceWarehouse && has(data.vehicles.filter(v => v.can_execute === true), p.vehicle) ? p.vehicle : "",
    sourceWarehouse,
  };
}

/** Remove only unsafe legacy Dispatch keys; never touch D05/D07 immutable durable commands. */
export function clearLegacyDispatchPreferences(): void {
  for (const key of ["activeTab", "wanasah_selected_zone", "wanasah_route_zone", "wanasah_route_driver", "wanasah_route_vehicle", "shop_import_draft"]) {
    localStorage.removeItem(key);
  }
}

/**
 * Async callbacks must carry one immutable authority generation, not just numeric IDs.
 * A -> B -> A with reused IDs is still a different generation.
 */
export function createDispatchAsyncEpoch(session: DashboardSession) {
  let revision = 0;
  let context = "";
  return {
    update(next: string) {
      if (next !== context) { context = next; ++revision; }
    },
    capture() {
      const saved = revision;
      return () => saved === revision && isDashboardSessionCurrent(session);
    },
    revoke() { ++revision; },
  };
}
