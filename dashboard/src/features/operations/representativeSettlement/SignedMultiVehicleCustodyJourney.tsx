import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { SettlementAuthFetch } from "./api";
import type { ReceivingWarehouse } from "./contracts";
import { loadReceivingWarehouses } from "./api";
import { readAuthorizedVehicleCount, type VehicleCountSheet } from "./vehicleCountRead";
import {
  readSignedVehicleResponsibilities, type SignedSessionVehicleResponsibilities,
} from "./vehicleResponsibilityRead";
import { submitSignedVehicleCount, type VehicleCountMode } from "./vehicleCountCommand";
import { VehicleVariancePanel } from "./VehicleVariancePanel";

export function SignedMultiVehicleCustodyJourney({
  isOpen, onClose, driverName, sessionId, authFetch, onCountsCompleted,
}: {
  isOpen: boolean;
  onClose: () => void;
  driverName: string;
  sessionId: number;
  authFetch: SettlementAuthFetch;
  /** Refresh authoritative BO financial-status; never assert financial readiness locally. */
  onCountsCompleted: (sessionId: number) => void;
}) {
  const { i18n } = useTranslation();
  const ar = i18n.language.startsWith("ar");
  const [membership, setMembership] = useState<SignedSessionVehicleResponsibilities | null>(null);
  const [sheet, setSheet] = useState<VehicleCountSheet | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [actual, setActual] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<VehicleCountMode>("COUNT_IN_PLACE");
  const [warehouses, setWarehouses] = useState<ReceivingWarehouse[]>([]);
  const [destination, setDestination] = useState("");
  const [countConfirmed, setCountConfirmed] = useState(false);
  const [handoffConfirmed, setHandoffConfirmed] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const notified = useRef<string | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const signed = await readSignedVehicleResponsibilities(authFetch, sessionId, signal);
      if (signal?.aborted) return;
      setMembership(signed);
      setError("");
      // No partial car list and no past settled car can be counted twice.
      if (signed.all_vehicle_counts_signed && signed.work_session_ended &&
          !signed.financially_settled) {
        const signature = JSON.stringify(signed.vehicles.map(v => v.checkpoint_id));
        if (notified.current !== signature) {
          notified.current = signature;
          onCountsCompleted(sessionId);
        }
      }
    } catch (err) {
      if (!signal?.aborted) {
        setMembership(null);
        setSheet(null);
        setError(apiErrorMessage(err, ar ? "تعذر التحقق من عهدة جميع السيارات" :
          "Could not verify the full signed session vehicle membership"));
      }
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [authFetch, sessionId, onCountsCompleted, ar]);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    notified.current = null;
    setMembership(null); setSheet(null); setSelected(null); setError("");
    void refresh(controller.signal);
    return () => controller.abort();
  }, [isOpen, refresh]);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    // Destinations are optional; no implicit warehouse transfer for COUNT_IN_PLACE.
    void loadReceivingWarehouses(authFetch, controller.signal)
      .then(data => { if (!controller.signal.aborted) setWarehouses(data); })
      .catch(() => { if (!controller.signal.aborted) setWarehouses([]); });
    return () => controller.abort();
  }, [authFetch, isOpen]);

  const choose = async (vehicleId: number) => {
    if (busy || !membership || !membership.work_session_ended ||
        membership.financially_settled || membership.all_vehicle_counts_signed) return;
    const car = membership.vehicles.find(v => v.vehicle_id === vehicleId);
    if (!car || car.checkpoint_status === "COUNT_SIGNED") return;
    setBusy(true); setSheet(null); setError(""); setSelected(vehicleId);
    setMode("COUNT_IN_PLACE"); setDestination(""); setCountConfirmed(false);
    setHandoffConfirmed(false); setNotes("");
    try {
      if (car.checkpoint_status === "NOT_COUNTED" ||
          car.checkpoint_status === "RECOUNT_AND_SIGN_REQUIRED") {
        const signed = await readAuthorizedVehicleCount(authFetch, sessionId, vehicleId);
        setSheet(signed);
        setActual(Object.fromEntries(signed.lines.map(line => [line.line_key, line.expected_quantity])));
      }
      // Review statuses deliberately show ONLY the signed exact-car variance
      // workflow, no stale previous snapshot token.
    } catch (e) {
      setSelected(null);
      setError(apiErrorMessage(e, ar ? "لم يتم التحقق من ورقة الجرد" : "Invalid signed count sheet"));
    } finally { setBusy(false); }
  };

  const submit = async () => {
    if (busy || !membership?.work_session_ended || membership.financially_settled ||
        !sheet || selected == null || !countConfirmed) return;
    const car = membership.vehicles.find(v => v.vehicle_id === selected);
    if (!car || !["NOT_COUNTED", "RECOUNT_AND_SIGN_REQUIRED"].includes(car.checkpoint_status) ||
        sheet.vehicle_id !== selected || sheet.work_session_id !== sessionId ||
        sheet.lines.some(line => !actual[line.line_key]?.trim())) return;
    if (mode === "PHYSICAL_HANDOFF" && (!handoffConfirmed || !destination)) return;
    setBusy(true); setError("");
    try {
      const result = await submitSignedVehicleCount(authFetch, sessionId, selected, {
        mode, snapshot_token: sheet.snapshot_token,
        receiver_confirms_count: true,
        receiver_confirms_handoff: mode === "PHYSICAL_HANDOFF",
        destination_location_id: mode === "PHYSICAL_HANDOFF" ? Number(destination) : null,
        items: sheet.lines.map(line => ({
          line_key: line.line_key, actual_quantity: actual[line.line_key].trim(),
        })),
        notes: notes.trim() || null,
      });
      setSheet(null);
      setCountConfirmed(false);
      if (result.review_required || result.status === "REVIEW_REQUIRED") {
        // Exact-car independent review, not a falsely successful signed count.
        await refresh();
      } else {
        setSelected(null);
        await refresh();
      }
    } catch (e) {
      // Keep original snapshot/count evidence; ambiguous transport error must
      // not cause another UUID or a silent switch to another vehicle.
      setError(apiErrorMessage(e, ar ? "تعذر تأكيد الجرد" : "Vehicle count not confirmed"));
    } finally { setBusy(false); }
  };

  const chosen = membership?.vehicles.find(v => v.vehicle_id === selected);
  return <Modal isOpen={isOpen} onClose={busy ? () => undefined : onClose}
    title={(ar ? "جرد عهدة جميع السيارات — " : "Count all session vehicles — ") + driverName}
    maxWidth="max-w-5xl">
    <section dir={i18n.dir()} className="max-h-[78vh] max-w-full space-y-4 overflow-y-auto p-1"
      data-testid="m05-m04-all-cars-journey">
      {error && <p role="alert" className="rounded border border-red-300 p-3 text-sm text-red-700">{error}</p>}
      {loading && !membership && <p role="status">{ar ? "التحقق من الجلسة" : "Checking signed session"}</p>}
      {membership && <>
        {!membership.work_session_ended && <p role="alert" className="rounded border p-3 text-sm">
          {ar ? "يجب إنهاء يوم العمل أولًا. إنهاء العمل ليس تسوية مالية." :
            "End the workday first. Ending work is not financial settlement."}
        </p>}
        <p className="text-sm">
          {ar ? "السيارات المسؤولة: " : "Session vehicles: "}{membership.vehicles.length}
          {" · "}{ar ? "المعتمدة: " : "Signed: "}
          {membership.vehicles.filter(v => v.checkpoint_status === "COUNT_SIGNED").length}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {membership.vehicles.map(car => <button type="button" key={car.vehicle_id}
            disabled={busy || !membership.work_session_ended || membership.financially_settled ||
              car.checkpoint_status === "COUNT_SIGNED"}
            onClick={() => void choose(car.vehicle_id)}
            className="min-w-0 rounded-xl border p-3 text-start disabled:opacity-60"
            aria-label={(ar ? "جرد السيارة " : "Count vehicle ") + car.plate_number}>
            <span className="block font-bold">{car.plate_number}</span>
            <span className="block text-xs">{car.checkpoint_status.split("_").join(" ")}</span>
            <span className="block text-xs">{ar ? "فترات العمل: " : "Execution periods: "}{car.period_ids.join(", ")}</span>
            <span className="block text-xs">{ar ? "إثباتات العهدة: " : "Custody epochs: "}{car.custody_epoch_ids.join(", ")}</span>
            {car.checkpoint_mode && <span className="block text-xs">{car.checkpoint_mode}</span>}
          </button>)}
        </div>
        {chosen && chosen.checkpoint_status === "REVIEW_REQUIRED" && <VehicleVariancePanel
            sessionId={sessionId} vehicleId={chosen.vehicle_id} authFetch={authFetch}
            onReviewed={() => { void refresh(); }}/>}
        {sheet && (chosen?.checkpoint_status === "NOT_COUNTED" ||
          chosen?.checkpoint_status === "RECOUNT_AND_SIGN_REQUIRED") && <div className="space-y-3 rounded-xl border p-3">
          <h3 className="font-bold">{ar ? "جرد السيارة" : "Count vehicle"} {sheet.vehicle_plate}</h3>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm"><input type="radio" name="m05-count-mode"
              checked={mode === "COUNT_IN_PLACE"} onChange={() => setMode("COUNT_IN_PLACE")} disabled={busy}/>
              {ar ? "جرد داخل السيارة — دون نقل مخزون" : "Count in place — no stock movement"}</label>
            <label className="flex items-center gap-2 text-sm"><input type="radio" name="m05-count-mode"
              checked={mode === "PHYSICAL_HANDOFF"} onChange={() => setMode("PHYSICAL_HANDOFF")} disabled={busy}/>
              {ar ? "تسليم فعلي للمستودع" : "Physical warehouse handoff"}</label>
          </div>
          <div className="max-h-64 space-y-2 overflow-y-auto">
            {sheet.lines.map(line => <label key={line.line_key} className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 text-sm">
              <span>{line.product_name} · {line.stock_status} · {line.batch_number || "—"} · {line.expiry_date || "—"}
                <span className="block text-xs text-slate-500">{ar ? "المتوقع" : "Expected"}: {line.expected_quantity} {line.uom}</span>
              </span>
              <input type="text" inputMode="decimal" disabled={busy}
                className="w-32 min-w-0 rounded border px-2 py-2" aria-label={line.line_key}
                value={actual[line.line_key] || ""}
                onChange={e => setActual(v => ({ ...v, [line.line_key]: e.target.value }))}/>
            </label>)}
          </div>
          {mode === "PHYSICAL_HANDOFF" && <>
            <select aria-label={ar ? "مستودع الاستلام الفعلي" : "Receiving warehouse"}
              className="w-full rounded border p-2" value={destination} disabled={busy}
              onChange={e => setDestination(e.target.value)}>
              <option value="">{ar ? "اختر مستودع الاستلام" : "Select receiving warehouse"}</option>
              {warehouses.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}
            </select>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox"
              checked={handoffConfirmed} disabled={busy}
              onChange={e => setHandoffConfirmed(e.target.checked)}/>
              {ar ? "أؤكد استلام وتسليم البضاعة فعليًا" : "I confirm actual physical warehouse handoff"}</label>
          </>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={busy}
            checked={countConfirmed} onChange={e => setCountConfirmed(e.target.checked)}/>
            {ar ? "أؤكد الكميات الفعلية لهذه السيارة فقط" : "I confirm this vehicle's actual counted quantities"}</label>
          <input type="text" className="w-full rounded border p-2" value={notes} disabled={busy}
            placeholder={ar ? "ملاحظات اختيارية" : "Optional notes"} onChange={e => setNotes(e.target.value)}/>
          <button type="button" disabled={busy || !countConfirmed || mode === "PHYSICAL_HANDOFF" && (!handoffConfirmed || !destination)}
            className="w-full rounded-lg bg-slate-900 px-4 py-3 text-white disabled:opacity-50"
            onClick={() => void submit()}>
            {ar ? "اعتماد جرد هذه السيارة" : "Submit signed vehicle count"}
          </button>
        </div>}
        {membership.all_vehicle_counts_signed && membership.work_session_ended &&
          <p role="status" className="rounded-lg border p-3 text-sm">
            {membership.financially_settled
              ? (ar ? "تمت التسوية المالية من الخادم" : "Server confirms financial settlement closed")
              : (ar ? "جرد كل السيارات معتمد. يتم التحقق من جاهزية التسوية المالية لدى الخادم." :
                "All vehicles are signed. Financial readiness is verified by the server.")}
          </p>}
      </>}
      <button type="button" disabled={busy || loading} className="rounded border px-3 py-2 text-sm"
        onClick={() => void refresh()}>{ar ? "تحديث الحالة المعتمدة" : "Refresh signed status"}</button>
    </section>
  </Modal>;
}
