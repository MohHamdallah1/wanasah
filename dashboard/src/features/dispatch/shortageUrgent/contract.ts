import type { Shortage, PendingRoute } from "@/types/dispatch";
import { signedShortageProgress } from "../shortageCommand/contract";

export type UrgentIntent = { request_id: string; driver_id: number; quantity_base: number };
export type UrgentPending = { scope: string; shortageId: number; shopId: number; zoneId: number; productId: number; requested: number; body: UrgentIntent };
export type UrgentQuote = { epoch: number; vehicle: number; unit: string; stock: string; limit: number };
export type EligibleDriver = { id: string; name: string; vehicle: string };
export type UrgentReceipt = { request_id: string; shortage_id: number; assignment_id: number; visit_id: number; approved_base: number; outstanding_base: number; custody_epoch_id: number; state: "URGENT_AUTHORIZED" };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const positive = (n: unknown): n is number => typeof n === "number" && Number.isSafeInteger(n) && n > 0;
const nonnegative = (n: unknown): n is number => typeof n === "number" && Number.isSafeInteger(n) && n >= 0;
export const numericId = (id: unknown): number => typeof id === "string" && /^[1-9]\d*$/.test(id) && positive(Number(id)) ? Number(id) : 0;
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
export function urgentBudget(row: Shortage) {
  const signed = signedShortageProgress(row);
  if (!signed || row.status !== "pending" || !nonnegative(row.activeUrgentBase) ||
      !nonnegative(row.unassignedBase) || row.activeUrgentBase > signed.outstanding ||
      row.unassignedBase !== signed.outstanding - row.activeUrgentBase) return null;
  return { ...signed, active: row.activeUrgentBase, unassigned: row.unassignedBase };
}
export function eligibleUrgentDrivers(routes: readonly PendingRoute[], drivers: readonly {id:string;name:string}[]): EligibleDriver[] {
  return drivers.flatMap(driver => {
    const matches = routes.filter(r => r.driverId === driver.id && r.status === "active");
    const route = matches[0];
    return matches.length === 1 && route.can_execute === true && numericId(driver.id) && numericId(route.vehicleId)
      ? [{ ...driver, vehicle: route.vehicleId }] : [];
  });
}
export function allowedUrgentDriver(row: Shortage, driver: EligibleDriver) {
  return (!row.driverId || row.driverId === driver.id) && numericId(row.id) > 0 &&
    numericId(row.productId) > 0 && numericId(row.shopId) > 0 && numericId(row.zoneId) > 0;
}
/** A quote is indicative only. Reject malformed/duplicate/mismatched evidence. Floor exact decimal stock without IEEE rounding. */
export function parseUrgentQuote(raw: unknown, row: Shortage, driver: EligibleDriver): UrgentQuote | null {
  const budget = urgentBudget(row);
  if (!budget || !allowedUrgentDriver(row, driver) || !object(raw) || raw.status !== "VERIFIED" ||
      raw.source !== "CANONICAL_VEHICLE_CUSTODY" || raw.vehicle_id !== numericId(driver.vehicle) ||
      !positive(raw.vehicle_location_id) || !positive(raw.custody_epoch_id) ||
      typeof raw.stock_snapshot !== "string" || !raw.stock_snapshot || !Array.isArray(raw.items) || raw.items.length !== 1) return null;
  const line: unknown = raw.items[0];
  if (!object(line) || line.product_id !== row.productId || typeof line.base_uom !== "string" ||
      !line.base_uom.trim() || line.base_uom.length > 64 || typeof line.available_base !== "string" ||
      line.available_base.length > 70 || !/^(?:0|[1-9]\d*)(?:\.\d{1,24})?$/.test(line.available_base)) return null;
  const stock = BigInt(line.available_base.split(".")[0]);
  const limit = Number(stock < BigInt(budget.unassigned) ? stock : BigInt(budget.unassigned));
  return { epoch: raw.custody_epoch_id, vehicle: raw.vehicle_id as number, unit: line.base_uom, stock: line.available_base, limit };
}
export function pendingUrgentKey(scope: string) {
  if (!/^[1-9]\d*:[1-9]\d*:[1-9]\d*$/.test(scope)) throw Error("URGENT_SCOPE");
  return "wanasah:dispatch:d10:shortage-urgent:v1:" + scope;
}
function validPending(raw: unknown, scope: string): raw is UrgentPending {
  if (!object(raw) || raw.scope !== scope || !positive(raw.shortageId) || !positive(raw.shopId) ||
      !positive(raw.zoneId) || !positive(raw.productId) || !positive(raw.requested) || !object(raw.body)) return false;
  const b = raw.body;
  return Object.keys(b).sort().join(",") === "driver_id,quantity_base,request_id" &&
    typeof b.request_id === "string" && uuid.test(b.request_id) && positive(b.driver_id) &&
    positive(b.quantity_base) && b.quantity_base <= raw.requested;
}
export function readUrgent(scope: string): UrgentPending | null {
  const raw = localStorage.getItem(pendingUrgentKey(scope));
  if (raw === null) return null;
  const parsed: unknown = JSON.parse(raw);
  if (!validPending(parsed, scope)) throw Error("URGENT_STORAGE");
  return parsed;
}
export function storeUrgent(scope: string, row: Shortage, driver: EligibleDriver, quantity: number): UrgentPending {
  if (readUrgent(scope)) throw Error("URGENT_EXISTS");
  const budget = urgentBudget(row);
  if (!budget || !allowedUrgentDriver(row, driver) || !positive(quantity) || quantity > budget.unassigned) throw Error("URGENT_INVALID");
  const pending: UrgentPending = {scope, shortageId:numericId(row.id), shopId:numericId(row.shopId), zoneId:numericId(row.zoneId),
    productId:numericId(row.productId), requested:budget.requested, body:{request_id:crypto.randomUUID(),driver_id:numericId(driver.id),quantity_base:quantity}};
  if (!validPending(pending, scope)) throw Error("URGENT_INVALID");
  localStorage.setItem(pendingUrgentKey(scope), JSON.stringify(pending));
  if (JSON.stringify(readUrgent(scope)) !== JSON.stringify(pending)) throw Error("URGENT_STORAGE");
  return pending;
}
export function clearUrgent(scope: string, pending: UrgentPending) {
  if (JSON.stringify(readUrgent(scope)) !== JSON.stringify(pending)) throw Error("URGENT_STORAGE");
  localStorage.removeItem(pendingUrgentKey(scope));
  if (readUrgent(scope)) throw Error("URGENT_STORAGE");
}
export function parseUrgentReceipt(raw: unknown, pending: UrgentPending): UrgentReceipt | null {
  if (!object(raw) || raw.state !== "URGENT_AUTHORIZED" || raw.request_id !== pending.body.request_id ||
      raw.shortage_id !== pending.shortageId || raw.approved_base !== pending.body.quantity_base ||
      !positive(raw.assignment_id) || !positive(raw.visit_id) || !positive(raw.custody_epoch_id) ||
      !nonnegative(raw.outstanding_base) || raw.outstanding_base < pending.body.quantity_base ||
      raw.outstanding_base > pending.requested) return null;
  return raw as UrgentReceipt;
}
