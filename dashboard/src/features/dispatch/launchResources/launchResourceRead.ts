import { useEffect, useState } from "react";
import { z } from "zod";
import type { useAuthFetch } from "@/hooks/useAuthFetch";
type LaunchAuthFetch = ReturnType<typeof useAuthFetch>;

const option = z.object({
  id: z.string().regex(/^[1-9][0-9]*$/),
  label: z.string().min(1),
  available: z.boolean(),
  code: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
}).strict().refine(x => x.available === (x.code === "AVAILABLE"), "INCONSISTENT_AVAILABILITY");
export const launchAvailabilitySchema = z.object({
  advisory: z.literal(true),
  zones: z.array(option).max(1024),
  drivers: z.array(option).max(1024),
  vehicles: z.array(option).max(1024),
  warehouses: z.array(option).max(1024),
}).strict().superRefine((data, ctx) => {
  for (const kind of ["zones", "drivers", "vehicles", "warehouses"] as const) {
    if (new Set(data[kind].map(x => x.id)).size !== data[kind].length)
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "DUPLICATE_" + kind });
  }
});
export type LaunchAvailability = z.infer<typeof launchAvailabilitySchema>;
export type LaunchOption = LaunchAvailability["drivers"][number];

export function optionFor(state: LaunchAvailability | null,
  kind: "zones" | "drivers" | "vehicles" | "warehouses",
  id: string): LaunchOption | undefined {
  return state?.[kind].find(x => x.id === id);
}
export function selectionBlocked(state: LaunchAvailability | null, selection: {
  zoneId: string; driverId: string; vehicleId: string; warehouseId: string;
}): boolean {
  return !state || !(
    optionFor(state, "zones", selection.zoneId)?.available &&
    optionFor(state, "drivers", selection.driverId)?.available &&
    optionFor(state, "vehicles", selection.vehicleId)?.available &&
    optionFor(state, "warehouses", selection.warehouseId)?.available
  );
}
export async function readLaunchAvailability(fetch: LaunchAuthFetch,
  selectedDriverId: string, selectedVehicleId: string,
  signal: AbortSignal): Promise<LaunchAvailability> {
  const params = new URLSearchParams();
  if (/^[1-9][0-9]*$/.test(selectedDriverId))
    params.set("selected_driver_id", selectedDriverId);
  if (/^[1-9][0-9]*$/.test(selectedVehicleId))
    params.set("selected_vehicle_id", selectedVehicleId);
  const raw = await fetch("/dispatch/launch/resource-availability" +
    (params.toString() ? "?" + params.toString() : ""), { signal, cache: "no-store" });
  return launchAvailabilitySchema.parse(raw);
}
export function useLaunchResourceAvailability({
  fetch, actorScope, admitted, driverId, vehicleId, routeEvidence,
}: {
  fetch: LaunchAuthFetch; actorScope: string | null;
  admitted: boolean; driverId: string; vehicleId: string; routeEvidence: unknown;
}) {
  const [snapshot, setSnapshot] = useState<{
    actor: string; driver: string; vehicle: string; route: unknown;
    data: LaunchAvailability;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!admitted || !actorScope) {
      setSnapshot(null); setError(null); return;
    }
    const controller = new AbortController();
    setError(null);
    void readLaunchAvailability(fetch, driverId, vehicleId, controller.signal)
      .then(data => {
        if (!controller.signal.aborted)
          setSnapshot({ actor: actorScope, driver: driverId,
            vehicle: vehicleId, route: routeEvidence, data });
      })
      .catch(err => {
        if (!controller.signal.aborted) {
          setSnapshot(null);
          setError(err instanceof Error ? err.message : "M05_AVAILABILITY_UNVERIFIED");
        }
      });
    return () => controller.abort();
  }, [fetch, actorScope, admitted, driverId, vehicleId, routeEvidence]);
  const fresh = Boolean(admitted && actorScope && snapshot &&
    snapshot.actor === actorScope && snapshot.driver === driverId &&
    snapshot.vehicle === vehicleId && snapshot.route === routeEvidence);
  return { data: fresh ? snapshot?.data ?? null : null, fresh, error };
}
