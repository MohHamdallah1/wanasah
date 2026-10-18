import { useEffect, useState } from "react";
import type { CustodySnapshot, ReceivingWarehouse, RecountSheet, VarianceReview } from "./contracts";
import type { RepresentativeSettlementCopy } from "./copy";

const lineMeta = (
  line: { batch_number: string | null; expiry_date: string | null; stock_status: string; uom: string },
  copy: RepresentativeSettlementCopy,
) => ({
  batch: line.batch_number || copy.noBatch,
  expiry: line.expiry_date || copy.noExpiry,
  status: copy.statusLabels[line.stock_status] || line.stock_status,
});

export function CustodyCountStep({
  snapshot, warehouses, destinationId, onDestinationChange, actual, onActualChange,
  readOnly, confirmed, onConfirmedChange, notes, onNotesChange, busy, validation, onSubmit, copy,
}: {
  snapshot: CustodySnapshot;
  warehouses: ReceivingWarehouse[];
  destinationId: string;
  onDestinationChange: (value: string) => void;
  actual: Record<string, string>;
  onActualChange: (lineKey: string, value: string) => void;
  readOnly: boolean;
  confirmed: boolean;
  onConfirmedChange: (value: boolean) => void;
  notes: string;
  onNotesChange: (value: string) => void;
  busy: boolean;
  validation: string | null;
  onSubmit: () => void;
  copy: RepresentativeSettlementCopy;
}) {
  return (
    <div className="space-y-5" data-settlement-stage={readOnly ? "handoff" : "custody-count"}>
      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
        <h3 className="font-black text-amber-900">{readOnly ? copy.handoffTitle : copy.countTitle}</h3>
        <p className="mt-1 text-sm font-medium text-amber-800">{readOnly ? copy.handoffHint : copy.countHint}</p>
      </div>
      <label className="block text-sm font-bold text-slate-700">
        {copy.warehouse}
        <select aria-label={copy.warehouse} value={destinationId} onChange={(e) => onDestinationChange(e.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5">
          <option value="">{copy.chooseWarehouse}</option>
          {warehouses.map((warehouse) => <option key={warehouse.id} value={String(warehouse.id)}>{warehouse.name} · {warehouse.code}</option>)}
        </select>
      </label>
      {warehouses.length === 0 && <p role="status" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-bold text-red-700">{copy.noWarehouse}</p>}
      <div className="space-y-3">
        {snapshot.lines.map((line) => {
          const meta = lineMeta(line, copy);
          return (
            <div key={line.line_key} className="rounded-2xl border border-slate-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-black text-slate-800">{line.product_name}</p>
                  <p className="mt-1 text-xs font-medium text-slate-500">{copy.batch}: {meta.batch} · {copy.expiry}: {meta.expiry}</p>
                  <p className="mt-1 text-xs font-medium text-slate-500">{copy.status}: {meta.status} · {copy.uom}: {line.uom}</p>
                </div>
                <div className="text-end">
                  <p className="text-[11px] font-bold text-slate-400">{copy.expected}</p>
                  <p className="text-lg font-black text-slate-800" dir="ltr">{line.expected_quantity} {line.uom}</p>
                </div>
              </div>
              <div className="mt-3">
                {readOnly ? (
                  <label className="block text-xs font-bold text-slate-600">
                    {copy.actual}
                    <input
                      aria-label={copy.actual + ": " + line.product_name + " — " + meta.status}
                      readOnly
                      value={line.expected_quantity}
                      className="mt-1 w-full rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-base font-black text-emerald-800"
                    />
                  </label>
                ) : (
                  <label className="block text-xs font-bold text-slate-600">
                    {copy.actual}
                    <input aria-label={copy.actual + ": " + line.product_name + " — " + meta.status} inputMode="decimal" value={actual[line.line_key] ?? ""} onChange={(e) => onActualChange(line.line_key, e.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-base font-bold" />
                  </label>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <label className="block text-xs font-bold text-slate-600">{copy.notes}<textarea value={notes} onChange={(e) => onNotesChange(e.target.value)} placeholder={copy.notesPlaceholder} rows={2} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" /></label>
      <label className="flex items-start gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm font-bold text-slate-700">
        <input type="checkbox" checked={confirmed} onChange={(e) => onConfirmedChange(e.target.checked)} className="mt-1" />
        <span>{copy.confirmHandoff}</span>
      </label>
      {validation && <p role="alert" className="text-sm font-bold text-red-600">{validation}</p>}
      <button type="button" onClick={onSubmit} disabled={busy || warehouses.length === 0} className="w-full rounded-xl bg-amber-400 px-4 py-3 font-black text-slate-900 hover:bg-amber-300 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400">
        {busy ? copy.busy : readOnly ? copy.confirmReceipt : copy.receive}
      </button>
    </div>
  );
}

export function VarianceReviewStep({
  review, busy, error, onRecount, onApprove, copy,
}: {
  review: VarianceReview;
  busy: boolean;
  error: string | null;
  onRecount: (payload: { reason: string; authorizer_username: string; authorizer_password: string }) => void;
  onApprove: (payload: { password: string; notes: string | null }) => void;
  copy: RepresentativeSettlementCopy;
}) {
  const [panel, setPanel] = useState<"none" | "recount" | "approve">("none");
  const [reason, setReason] = useState("");
  const [username, setUsername] = useState("");
  const [authorizerPassword, setAuthorizerPassword] = useState("");
  const [approvalPassword, setApprovalPassword] = useState("");
  const [approvalNotes, setApprovalNotes] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  useEffect(() => { setPanel("none"); setValidation(null); }, [review.attempt_number]);
  const approveBlocked = review.requires_independent_recount && !review.independent_recount_satisfied;

  return (
    <div className="space-y-5" data-settlement-stage="variance-review">
      <div className="rounded-2xl border border-orange-200 bg-orange-50 p-4">
        <h3 className="font-black text-orange-900">{copy.reviewTitle}</h3>
        <p className="mt-1 text-sm font-medium text-orange-800">{copy.reviewHint}</p>
      </div>
      {review.requires_independent_recount && <p className={"rounded-xl border p-3 text-sm font-bold " + (review.independent_recount_satisfied ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700")}>{review.independent_recount_satisfied ? copy.independentSatisfied : copy.independentRequired}</p>}
      <div className="space-y-3">
        {review.lines.map((line, index) => {
          const meta = lineMeta(line, copy);
          return (
            <div key={line.product_name + ":" + index} className="rounded-2xl border border-slate-200 bg-white p-4">
              <p className="font-black text-slate-800">{line.product_name}</p>
              <p className="mt-1 text-xs text-slate-500">{copy.batch}: {meta.batch} · {copy.expiry}: {meta.expiry} · {copy.status}: {meta.status} · {copy.uom}: {line.uom}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-slate-50 p-2"><p className="text-[10px] text-slate-400">{copy.expected}</p><p className="font-black" dir="ltr">{line.expected_quantity}</p></div>
                <div className="rounded-lg bg-blue-50 p-2"><p className="text-[10px] text-blue-500">{copy.counted}</p><p className="font-black text-blue-800" dir="ltr">{line.actual_quantity}</p></div>
                <div className="rounded-lg bg-orange-50 p-2"><p className="text-[10px] text-orange-500">{copy.variance}</p><p className="font-black text-orange-800" dir="ltr">{line.variance_quantity}</p></div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <button type="button" onClick={() => { setPanel("recount"); setValidation(null); }} className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 font-black text-blue-800">{copy.requestRecount}</button>
        <button type="button" disabled={approveBlocked} onClick={() => { setPanel("approve"); setValidation(null); }} className="rounded-xl bg-slate-900 px-4 py-3 font-black text-white disabled:bg-slate-300">{copy.approve}</button>
      </div>
      {panel === "recount" && <div className="space-y-3 rounded-2xl border border-blue-200 bg-blue-50/50 p-4">
        <label className="block text-xs font-bold">{copy.recountReason}<textarea aria-label={copy.recountReason} value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 w-full rounded-lg border border-blue-200 bg-white p-2" /></label>
        <label className="block text-xs font-bold">{copy.authorizerUsername}<input aria-label={copy.authorizerUsername} value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-full rounded-lg border border-blue-200 bg-white p-2" /></label>
        <label className="block text-xs font-bold">{copy.authorizerPassword}<input aria-label={copy.authorizerPassword} type="password" value={authorizerPassword} onChange={(e) => setAuthorizerPassword(e.target.value)} className="mt-1 w-full rounded-lg border border-blue-200 bg-white p-2" /></label>
        <button type="button" disabled={busy} onClick={() => {
          if (!reason.trim() || !username.trim() || !authorizerPassword) { setValidation(copy.recountFieldsRequired); return; }
          onRecount({ reason: reason.trim(), authorizer_username: username.trim(), authorizer_password: authorizerPassword });
        }} className="w-full rounded-xl bg-blue-600 px-4 py-2.5 font-black text-white disabled:bg-slate-300">{busy ? copy.busy : copy.authorizeRecount}</button>
      </div>}
      {panel === "approve" && !approveBlocked && <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <label className="block text-xs font-bold">{copy.approvalPassword}<input aria-label={copy.approvalPassword} type="password" value={approvalPassword} onChange={(e) => setApprovalPassword(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white p-2" /></label>
        <label className="block text-xs font-bold">{copy.approvalNotes}<textarea aria-label={copy.approvalNotes} value={approvalNotes} onChange={(e) => setApprovalNotes(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white p-2" /></label>
        <button type="button" disabled={busy} onClick={() => {
          if (!approvalPassword) { setValidation(copy.approvalPasswordRequired); return; }
          onApprove({ password: approvalPassword, notes: approvalNotes.trim() || null });
        }} className="w-full rounded-xl bg-slate-900 px-4 py-2.5 font-black text-white disabled:bg-slate-300">{busy ? copy.busy : copy.approveFinal}</button>
      </div>}
      {(validation || error) && <p role="alert" className="text-sm font-bold text-red-600">{validation || error}</p>}
    </div>
  );
}

export function RecountStep({
  sheet, actual, onActualChange, notes, onNotesChange, busy, validation, onSubmit, copy,
}: {
  sheet: RecountSheet;
  actual: Record<string, string>;
  onActualChange: (lineKey: string, value: string) => void;
  notes: string;
  onNotesChange: (value: string) => void;
  busy: boolean;
  validation: string | null;
  onSubmit: () => void;
  copy: RepresentativeSettlementCopy;
}) {
  return (
    <div className="space-y-5" data-settlement-stage="recount">
      <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
        <h3 className="font-black text-blue-900">{copy.recountTitle}</h3>
        <p className="mt-1 text-sm font-medium text-blue-800">{copy.recountHint}</p>
      </div>
      <div className="space-y-3">
        {sheet.lines.map((line) => {
          const meta = lineMeta(line, copy);
          return <div key={line.line_key} className="rounded-2xl border border-slate-200 bg-white p-4">
            <p className="font-black text-slate-800">{line.product_name}</p>
            <p className="mt-1 text-xs text-slate-500">{copy.batch}: {meta.batch} · {copy.expiry}: {meta.expiry} · {copy.status}: {meta.status} · {copy.uom}: {line.uom}</p>
            <label className="mt-3 block text-xs font-bold text-slate-600">{copy.counted}<input aria-label={copy.actual + ": " + line.product_name + " — " + meta.status} inputMode="decimal" value={actual[line.line_key] ?? ""} onChange={(e) => onActualChange(line.line_key, e.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-base font-bold" /></label>
          </div>;
        })}
      </div>
      <label className="block text-xs font-bold text-slate-600">{copy.notes}<textarea value={notes} onChange={(e) => onNotesChange(e.target.value)} rows={2} className="mt-1 w-full rounded-xl border border-slate-200 p-2" /></label>
      {validation && <p role="alert" className="text-sm font-bold text-red-600">{validation}</p>}
      <button type="button" disabled={busy} onClick={onSubmit} className="w-full rounded-xl bg-blue-600 px-4 py-3 font-black text-white disabled:bg-slate-300">{busy ? copy.busy : copy.submitRecount}</button>
    </div>
  );
}
