import { useEffect, useRef, useState } from "react";
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
  // A verified same-actor READ may remain visible during an ordinary SPA
  // return. A new signed availability GET is still mandatory for COMMANDS.
  // The epoch changes synchronously before effects so a prior response never
  // becomes command-fresh for even one render on re-admission.
  const admissionEpoch = useRef(0);
  const wasAdmitted = useRef(admitted);
  if (wasAdmitted.current !== admitted) {
    wasAdmitted.current = admitted;
    admissionEpoch.current += 1;
  }
  const [snapshot, setSnapshot] = useState<{
    actor: string; driver: string; vehicle: string; route: unknown;
    epoch: number; data: LaunchAvailability;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!actorScope) {
      setSnapshot(null); setError(null); return;
    }
    // Hiding Dispatch is not revocation. Keep only this exact actor's signed
    // presentation snapshot while the next genuine capability/read is pending.
    if (!admitted) return;
    const controller = new AbortController();
    const epoch = admissionEpoch.current;
    setError(null);
    void readLaunchAvailability(fetch, driverId, vehicleId, controller.signal)
      .then(data => {
        if (!controller.signal.aborted)
          setSnapshot({ actor: actorScope, driver: driverId,
            vehicle: vehicleId, route: routeEvidence, epoch, data });
      })
      .catch(err => {
        if (!controller.signal.aborted) {
          setSnapshot(null);
          setError(err instanceof Error ? err.message : "M05_AVAILABILITY_UNVERIFIED");
        }
      });
    return () => controller.abort();
  }, [fetch, actorScope, admitted, driverId, vehicleId, routeEvidence]);
  const sameSignedRead = Boolean(actorScope && snapshot && !error &&
    snapshot.actor === actorScope && snapshot.driver === driverId &&
    snapshot.vehicle === vehicleId && snapshot.route === routeEvidence);
  const fresh = Boolean(admitted && sameSignedRead &&
    snapshot?.epoch === admissionEpoch.current);
  // data is presentation-only until fresh; selectionBlocked(...), launch,
  // inventory and FIELD execution retain the original fail-closed proof.
  return { data: sameSignedRead ? snapshot?.data ?? null : null, fresh, error };
}
