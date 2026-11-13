import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { lifecycleCopy } from "./copy";
import { apiErrorCode, apiErrorStatus } from "@/lib/apiErrors";
import { CustomSelect } from "@/components/ui/custom-select";
import type { PendingRoute } from "@/types/dispatch";
import {
  createLifecycleIntent, type LifecycleAction,
  type RouteAssignmentProof, type VehicleAcceptanceProof,
  type RouteLifecycleReceipt,
} from "./contract";
import {
  dispatchRouteLifecycle, hasPendingRouteLifecycle,
  type RouteLifecycleOutcome,
} from "./command";

type Choice = { id: string; label: string };
type AuthFetch = (path: string, init?: RequestInit) => Promise<unknown>;

export function RouteLifecyclePanel({
  isOpen, onClose, route, assignment, drivers, vehicles, selectedDriver,
  selectedVehicle, onDriverChange, onVehicleChange,
  actorScope, fetch, authorized, onCommitted, initialAction,
}: {
  isOpen: boolean;
  onClose: () => void;
  route: PendingRoute | null;
  /** Fresh authorized period/custody truth; legacy fields cannot substitute. */
  assignment: RouteAssignmentProof | null;
  drivers: Choice[];
  vehicles: Choice[];
  selectedDriver: string;
  selectedVehicle: string;
  onDriverChange: (value: string) => void;
  onVehicleChange: (value: string) => void;
  actorScope: string | null;
  fetch: AuthFetch;
  authorized: () => boolean;
  onCommitted: (receipt: RouteLifecycleReceipt) => void;
  initialAction?: LifecycleAction;
}) {
  const { i18n } = useTranslation();
  const copy = lifecycleCopy(i18n.language);
  const [working, setWorking] = useState(false);
  const [pending, setPending] = useState<"checking" | "no" | "yes">("checking");
  const [result, setResult] = useState<RouteLifecycleOutcome | null>(null);
  const [signedCustody, setSignedCustody] = useState<VehicleAcceptanceProof | null>(null);
  const [probeError, setProbeError] = useState("");
  const verified = !!assignment && !!route && assignment.routeId === Number(route.id) &&
    route.can_execute === true && !!actorScope && authorized();
  const continuingPause = route?.status === "waiting" && assignment?.currentPeriodId != null;
  // Waiting may ONLY continue on the currently signed rep and vehicle; ignore
  // historic route IDs and never offer reassignment while assets are held.
  const targetDriver = continuingPause ? String(assignment?.currentDriverId ?? "") : selectedDriver;
  const targetVehicle = continuingPause ? String(assignment?.currentVehicleId ?? "") : selectedVehicle;
  const targetReady = !!signedCustody && signedCustody.accepted === true &&
    signedCustody.authorized === true &&
    String(signedCustody.driverId) === targetDriver &&
    String(signedCustody.vehicleId) === targetVehicle;
  const allowed = verified && pending === "no" && !working;
  // Only revision-one frozen V1 has M02's documented no-period POSTPONE
  // exception. Versioned periods must carry their real signed current ID.
  const canPostpone = allowed && !!assignment &&
    (assignment.currentPeriodId !== null || assignment.assignmentRevision === 1);
  const canPause = allowed && route?.status === "active" &&
    assignment?.currentPeriodId !== null && assignment?.currentPeriodId !== undefined;
  useEffect(() => {
    setSignedCustody(null);
    setProbeError("");
    if (!isOpen || !route ||
        (route.status !== "postponed" && !continuingPause) || !verified ||
        !targetDriver || !targetVehicle || !/^\d+$/.test(targetDriver) ||
        !/^\d+$/.test(targetVehicle)) return;
    const controller = new AbortController();
    const path = `/dispatch/route/${route.id}/lifecycle/readiness?` +
      `target_driver_id=${encodeURIComponent(targetDriver)}&target_vehicle_id=${encodeURIComponent(targetVehicle)}`;
    void fetch(path, { cache: "no-store", signal: controller.signal })
      .then(raw => {
        if (controller.signal.aborted || !authorized() || !assignment ||
            !raw || typeof raw !== "object" || Array.isArray(raw)) return;
        const proof = raw as Partial<VehicleAcceptanceProof> & { assignmentContextRevision?: number };
        if (proof.accepted === true && proof.authorized === true &&
            proof.driverId === Number(targetDriver) && proof.vehicleId === Number(targetVehicle) &&
            Number.isSafeInteger(proof.custodyRevision) && (proof.custodyRevision ?? 0) > 0 &&
            proof.assignmentContextRevision === assignment.assignmentRevision) {
          setSignedCustody(proof as VehicleAcceptanceProof);
        } else setProbeError(copy.noEvidence);
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = apiErrorStatus(error);
        const code = apiErrorCode(error);
        if (status === 401 || status === 403) setProbeError(copy.accessDenied);
        else if (code === "M05_TARGET_IN_USE") setProbeError(copy.targetBusy);
        else if (code?.includes("CUSTODY")) setProbeError(copy.custodyMissing);
        else if (code?.includes("STALE") || code === "M05_ROUTE_ALREADY_ASSIGNED")
          setProbeError(copy.assignmentStale);
        else setProbeError(copy.noEvidence);
      });
    return () => controller.abort();
  }, [isOpen, route?.id, route?.status, verified, continuingPause, targetDriver, targetVehicle,
    assignment?.assignmentRevision, assignment?.currentPeriodId,
    fetch, authorized, copy.noEvidence, copy.accessDenied,
    copy.targetBusy, copy.custodyMissing, copy.assignmentStale]);

  useEffect(() => {
    if (!isOpen || !route || !actorScope) { setPending("checking"); return; }
    let fresh = true;
    setPending("checking");
    setResult(null);
    void hasPendingRouteLifecycle(actorScope, Number(route.id))
      .then(exists => { if (fresh) setPending(exists ? "yes" : "no"); })
      .catch(() => { if (fresh) setPending("yes"); }); // corrupted durable record: fail closed
    return () => { fresh = false; };
  }, [isOpen, route?.id, actorScope]);

  const execute = async (action?: LifecycleAction) => {
    if (working || !route || !actorScope || !verified) return;
    if (action && pending !== "no") return;
    if (action === "RESUME" && !targetReady) return;
    setWorking(true);
    try {
      const intent = action
        ? createLifecycleIntent(action, assignment!,
          action === "RESUME" ? signedCustody! : undefined)
        : undefined;
      const outcome = await dispatchRouteLifecycle({
        actorScope, routeId: Number(route.id), intent, fetch, authorized,
      });
      setResult(outcome);
      if (outcome.kind === "committed") {
        setPending("no");
        onCommitted(outcome.receipt);
      } else if (outcome.kind === "unknown" || outcome.kind === "conflict") {
        setPending("yes"); // keep exact original command available to retry
      }
    } catch {
      setPending("yes"); // never generate another UUID on unclear evidence
      setResult({ kind: "unknown" });
    } finally {
      setWorking(false);
    }
  };

  const isPostponed = route?.status === "postponed";
  const denied = !verified;
  const statusCopy = result?.kind === "committed"
    ? copy.success : result?.kind === "denied" ? copy.accessDenied
    : result?.kind === "conflict" ? copy.conflict : copy.unknown;

  return (
    <Modal isOpen={isOpen} onClose={working ? () => undefined : onClose}
      title={copy.title} maxWidth="max-w-xl">
      <div className="space-y-3" dir={i18n.dir()} data-testid="m05-lifecycle-panel">
        <p className="text-sm font-medium">{route?.zoneName || "—"}</p>
        {(denied || ((isPostponed || continuingPause) && probeError)) && <p role="status" className="rounded-lg border border-amber-300 p-3 text-sm">
          {probeError || copy.noEvidence}
        </p>}
        {isPostponed && initialAction !== "CLOSE" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <CustomSelect label={copy.driver} value={selectedDriver}
              options={drivers} onChange={onDriverChange} disabled={working || pending !== "no"}/>
            <CustomSelect label={copy.vehicle} value={selectedVehicle}
              options={vehicles} onChange={onVehicleChange} disabled={working || pending !== "no"}/>
          </div>
        )}
        <p className="text-xs text-slate-600">{copy.separatedStock}</p>
        {result && <p role="status" className="rounded-lg border p-2 text-sm">{statusCopy}</p>}
        {pending === "yes" && (
          <button type="button" disabled={!verified || working} onClick={() => void execute()}
            className="rounded-lg border px-4 py-2 text-sm font-bold disabled:opacity-50">
            {copy.retry}
          </button>
        )}
        <div className="flex flex-wrap gap-2">
          {(isPostponed || (continuingPause && initialAction === "RESUME")) &&
           initialAction !== "CLOSE" ? (
            <button type="button" disabled={!allowed || !targetReady}
              onClick={() => void execute("RESUME")}
              className="rounded-lg bg-blue-700 px-4 py-2 text-white disabled:opacity-50">
              {continuingPause ? copy.continue : copy.resume}
            </button>
          ) : (
            <>
              {!isPostponed && initialAction === "PAUSE" && <button type="button" disabled={!canPause}
                onClick={() => void execute("PAUSE")}
                className="rounded-lg border px-4 py-2 disabled:opacity-50">
                {copy.pause}
              </button>}
              {!isPostponed && initialAction !== "CLOSE" && initialAction !== "PAUSE" &&
                <button type="button" disabled={!canPostpone}
                  onClick={() => void execute("POSTPONE")}
                  className="rounded-lg border px-4 py-2 disabled:opacity-50">
                  {copy.postpone}
                </button>}
              <button type="button" disabled={!allowed}
                onClick={() => void execute("CLOSE")}
                className="rounded-lg border px-4 py-2 disabled:opacity-50">
                {copy.close}
              </button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}
