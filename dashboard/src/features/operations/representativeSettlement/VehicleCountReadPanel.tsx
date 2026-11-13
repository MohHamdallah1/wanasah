import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { SettlementAuthFetch } from "./api";
import {
  readAuthorizedVehicleCount, type VehicleCountSheet,
} from "./vehicleCountRead";

export function VehicleCountReadPanel({
  sessionId, vehicleIds, authFetch,
}: {
  sessionId: number;
  /** Must come from signed M04 session vehicle listing, NOT an old route. */
  vehicleIds: readonly number[];
  authFetch: SettlementAuthFetch;
}) {
  const { i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const [sheets, setSheets] = useState<VehicleCountSheet[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!vehicleIds.length) { setSheets([]); return; }
    const controller = new AbortController();
    setError(false);
    void Promise.all(vehicleIds.map(vehicleId =>
      readAuthorizedVehicleCount(authFetch, sessionId, vehicleId, controller.signal)))
      .then(loaded => { if (!controller.signal.aborted) setSheets(loaded); })
      .catch(() => { if (!controller.signal.aborted) { setSheets([]); setError(true); } });
    return () => controller.abort();
  }, [sessionId, vehicleIds, authFetch]);

  return (
    <section className="space-y-3" dir={i18n.dir()} data-testid="m05-vehicle-custody-sheets">
      {error && <p role="alert" className="text-sm text-red-700">
        {ar ? "تعذر التحقق من عهدة السيارات ضمن صلاحياتك." : "Vehicle custody could not be verified under your access."}
      </p>}
      {sheets.map(sheet => (
        <article key={sheet.vehicle_id} className="rounded-xl border p-3">
          <h3 className="font-bold">{ar ? "عهدة السيارة" : "Vehicle custody"} — {sheet.vehicle_plate}</h3>
          <p className="text-xs text-slate-500">{ar ? "قراءة جرد فقط — لم يتم الاعتماد" : "Count review only — not approved"}</p>
          <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {sheet.lines.map(line => (
              <div key={line.line_key} className="flex flex-wrap justify-between gap-2 border-b py-1 text-sm">
                <span>{line.product_name} · {line.stock_status} · {line.batch_number || "—"}</span>
                <span dir="ltr">{line.expected_quantity} {line.uom}</span>
              </div>
            ))}
          </div>
          <button type="button" disabled className="mt-3 w-full rounded-lg border px-3 py-2 text-sm disabled:opacity-50">
            {ar ? "اعتماد جرد داخل السيارة — غير متاح حتى ربط الاعتماد الموقّع" :
              "Count in vehicle — awaiting signed confirmation service"}
          </button>
        </article>
      ))}
    </section>
  );
}
