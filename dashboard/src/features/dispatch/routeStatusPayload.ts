/**
 * A Route transition only updates Route metadata. Physical custody is handled
 * by the separately confirmed, idempotent canonical Adjust Load command.
 */
export interface RouteStatusOnlyPayload {
  status: "active" | "closed" | "waiting" | "postponed";
  driverId: string;
  vehicleId: string;
}

export function buildRouteStatusOnlyPayload(
  status: RouteStatusOnlyPayload["status"],
  driverId: string,
  vehicleId: string,
): RouteStatusOnlyPayload {
  return { status, driverId, vehicleId };
}
