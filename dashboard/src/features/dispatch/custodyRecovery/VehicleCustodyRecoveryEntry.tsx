import { useState } from "react";
import { useTranslation } from "react-i18next";
import { custodyCopy, custodyReason } from "./copy";
import {
  VehicleCustodyRecoveryPanel, type RecoveryDriver,
} from "./VehicleCustodyRecoveryPanel";
import type { AuthorizedFetch } from "./command";
import type { Receipt } from "./contract";

/** Small, scope-safe handoff point for LEAD's post-#973 Dispatch selector bind.
 * The original disabled option stays disabled until an actual C02 commit.
 */
export function VehicleCustodyRecoveryEntry({
  vehicleId, vehicleLabel, reasonCode, drivers, selectedDriverId,
  actorScope, fetch, authorized, onAccepted, openOnMount = false,
}: {
  vehicleId: string; vehicleLabel: string; reasonCode: string;
  drivers: readonly RecoveryDriver[]; selectedDriverId?: string;
  actorScope: string | null; fetch: AuthorizedFetch; openOnMount?: boolean;
  authorized: () => boolean; onAccepted: (receipt: Receipt) => void;
}) {
  const { i18n } = useTranslation();
  const t = custodyCopy(i18n.language);
  const [open, setOpen] = useState(openOnMount);
  if (!reasonCode || reasonCode === "AVAILABLE") return null;
  return <div data-testid="c03-blocked-car-action"
    dir={i18n.dir()} className="min-w-0 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
    <p className="break-words font-semibold">{vehicleLabel}</p>
    <p role="status" className="mt-1 text-amber-900">
      {custodyReason(reasonCode,i18n.language)}
    </p>
    {authorized() && actorScope && (
      <button type="button"
        onClick={() => setOpen(true)}
        className="mt-2 min-h-10 rounded-lg bg-sky-700 px-4 py-2 font-semibold text-white">
        {t.title}
      </button>
    )}
    {open && <VehicleCustodyRecoveryPanel
      open={open} onClose={() => setOpen(false)}
      vehicleId={vehicleId} vehicleLabel={vehicleLabel}
      drivers={drivers} selectedDriverId={selectedDriverId}
      fetch={fetch} actorScope={actorScope}
      authorized={authorized} onAccepted={receipt => {
        setOpen(false);
        onAccepted(receipt); // caller invalidates resource-read, never remounts page
      }}/>}
  </div>;
}
