import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { lifecycleCopy } from "./copy";
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
  selectedVehicle, onDriverChange, onVehicleChange, signedCustody,
  actorScope, fetch, authorized, onCommitted,
}: {
  isOpen: boolean;
  onClose: () => void;
  route: PendingRoute | null;
  /** Fresh authorized period/custody truth; legacy fields cannot substitute. */
  assignment: RouteAssignmentProof | null;
  drivers: readonly Choice[];
  vehicles: readonly Choice[];
  selectedDriver: string;
  selectedVehicle: string;
  onDriverChange: (value: string) => void;
  onVehicleChange: (value: string) => void;
  /** Exact current accepted target Driver+Vehicle evidence from Backend. */
  signedCustody: VehicleAcceptanceProof | null;
  actorScope: string | null;
  fetch: AuthFetch;
  authorized: () => boolean;
  onCommitted: (receipt: RouteLifecycleReceipt) => void;
}) {
  const { i18n } = useTranslation();
  const copy = lifecycleCopy(i18n.language);
  const [working, setWorking] = useState(false);
  const [pending, setPending] = useState<"checking" | "no" | "yes">("checking");
  const [result, setResult] = useState<RouteLifecycleOutcome | null>(null);
  const verified = !!assignment && !!route && assignment.routeId === Number(route.id) &&
    route.can_execute === true && !!actorScope && authorized();
  const targetReady = !!signedCustody && signedCustody.accepted === true &&
    signedCustody.authorized === true &&
    String(signedCustody.driverId) === selectedDriver &&
    String(signedCustody.vehicleId) === selectedVehicle;
  const allowed = verified && pending === "no" && !working;

  useEffect(() => {
    if (!isOpen || !route || !actorScope) { setPending("checking"); return; }
    let fresh = true;
    setPending("checking");
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
        {denied && <p role="status" className="rounded-lg border border-amber-300 p-3 text-sm">
          {copy.noEvidence}
        </p>}
        {isPostponed && (
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
          {isPostponed ? (
            <button type="button" disabled={!allowed || !targetReady}
              onClick={() => void execute("RESUME")}
              className="rounded-lg bg-blue-700 px-4 py-2 text-white disabled:opacity-50">
              {copy.resume}
            </button>
          ) : (
            <>
              <button type="button" disabled={!allowed}
                onClick={() => void execute("POSTPONE")}
                className="rounded-lg border px-4 py-2 disabled:opacity-50">
                {copy.postpone}
              </button>
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
