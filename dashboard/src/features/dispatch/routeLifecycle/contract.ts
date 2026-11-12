/** M05 consumes ONLY signed M02/M03 read-side assignment evidence.
 * Legacy DispatchRoute.driverId/vehicleId/workSessionId are historic values,
 * never the active execution period or signed vehicle custodian.
 */
export type LifecycleAction = "POSTPONE" | "RESUME" | "CLOSE";

export interface RouteAssignmentProof {
  routeId: number;
  assignmentRevision: number;
  currentPeriodId: number | null;
  currentDriverId: number | null;
  currentVehicleId: number | null;
}

export interface VehicleAcceptanceProof {
  vehicleId: number;
  driverId: number;
  custodyRevision: number;
  accepted: true;
  authorized: true;
}

export interface RouteLifecycleIntent {
  action: LifecycleAction;
  expected_context_revision: number;
  expected_period_id: number | null;
  expected_vehicle_custody_revision: number | null;
  target_driver_id: number | null;
  target_vehicle_id: number | null;
}

export interface RouteLifecycleReceipt {
  state: "COMMITTED";
  request_id: string;
  route_id: number;
  action: LifecycleAction;
  status: "active" | "postponed" | "closed";
  context_revision: number;
  zone_reserved: boolean;
  live_assets_reserved: boolean;
}

const positive = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const idOrNull = (value: unknown): number | null | undefined =>
  value === null ? null : positive(value) ? value : undefined;

/** Fail closed: old /dispatch/active_routes does NOT supply these values.
 * A LEAD-owned bounded Backend read must supply them before M05 buttons act.
 */
export function parseRouteAssignmentProof(raw: unknown): RouteAssignmentProof | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;
  const routeId = typeof data.id === "string" && /^[1-9]\d*$/.test(data.id)
    ? Number(data.id) : data.id;
  const currentPeriodId = idOrNull(data.currentPeriodId);
  const currentDriverId = idOrNull(data.currentDriverId);
  const currentVehicleId = idOrNull(data.currentVehicleId);
  if (!positive(routeId) || !positive(data.assignmentContextRevision) ||
      currentPeriodId === undefined || currentDriverId === undefined ||
      currentVehicleId === undefined) return null;
  if (currentPeriodId !== null && (currentDriverId === null || currentVehicleId === null)) return null;
  return {
    routeId, assignmentRevision: data.assignmentContextRevision,
    currentPeriodId, currentDriverId, currentVehicleId,
  };
}

/** The target custodian must come from an actual current signed Backend read,
 * never from a vehicle dropdown or the last historical route assignment.
 */
export function createLifecycleIntent(
  action: LifecycleAction,
  route: RouteAssignmentProof,
  target?: VehicleAcceptanceProof,
): RouteLifecycleIntent {
  if (!positive(route.routeId) || !positive(route.assignmentRevision)) {
    throw new Error("M05_ROUTE_ASSIGNMENT_UNVERIFIED");
  }
  if (action === "RESUME") {
    if (!target || target.accepted !== true || target.authorized !== true ||
        !positive(target.vehicleId) || !positive(target.driverId) ||
        !positive(target.custodyRevision) || route.currentPeriodId !== null) {
      throw new Error("M05_CURRENT_CUSTODY_REQUIRED");
    }
    return {
      action,
      expected_context_revision: route.assignmentRevision,
      expected_period_id: null,
      expected_vehicle_custody_revision: target.custodyRevision,
      target_driver_id: target.driverId,
      target_vehicle_id: target.vehicleId,
    };
  }
  if (target) throw new Error("M05_NO_IMPLICIT_REASSIGNMENT");
  return {
    action,
    expected_context_revision: route.assignmentRevision,
    expected_period_id: route.currentPeriodId,
    expected_vehicle_custody_revision: null,
    target_driver_id: null, target_vehicle_id: null,
  };
}

export function parseLifecycleReceipt(
  raw: unknown, routeId: number, action: LifecycleAction, requestId: string,
): RouteLifecycleReceipt {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("M05_RECEIPT_INVALID");
  const row = raw as Record<string, unknown>;
  const status = action === "POSTPONE" ? "postponed" : action === "RESUME" ? "active" : "closed";
  if (row.state !== "COMMITTED" || row.request_id !== requestId ||
      row.route_id !== routeId || row.action !== action || row.status !== status ||
      !positive(row.context_revision) || typeof row.zone_reserved !== "boolean" ||
      typeof row.live_assets_reserved !== "boolean" ||
      row.zone_reserved !== (action !== "CLOSE") ||
      row.live_assets_reserved !== (action === "RESUME")) throw new Error("M05_RECEIPT_INVALID");
  return row as unknown as RouteLifecycleReceipt;
}
